"""Adapt existing Poincare scans and exported schedules to measurement targets."""

import csv
from dataclasses import dataclass

import numpy as np

from instruments.visa import finite, integer
from poincare_scan import raster_targets, stokes


@dataclass(frozen=True)
class Target:
    target_id: int
    q_deg: float
    h_deg: float

    def __post_init__(self):
        integer(self.target_id, "target_id")
        finite(self.q_deg, "QWP target")
        finite(self.h_deg, "HWP target")

    @property
    def stokes(self):
        return stokes(self.q_deg, self.h_deg)


def make_plan(scan="equal-area", samples=4096, *, q_steps=31, h_steps=61,
              ratio=np.sqrt(2)):
    samples = integer(samples, "samples", 1)
    if scan in ("equal-area", "uniform-angle"):
        from poincare_equal_area_scan import scan_targets
        _, _, _, q, h, _ = scan_targets(samples, scan)
    elif scan == "torus":
        from poincare_torus_scan import trajectory
        # trajectory(N) includes both endpoints; CLI samples means total targets.
        _, q, h, _, _ = trajectory(max(1, samples - 1), ratio)
        q, h = q[:samples], h[:samples]
    elif scan == "raster":
        q, h = raster_targets(q_steps, h_steps).T
    else:
        raise ValueError(f"Unknown scan: {scan}")
    return [Target(i, float(qi), float(hi)) for i, (qi, hi) in enumerate(zip(q, h))]


def load_plan(path):
    """Read the existing equal-area, torus, or optimizer CSV formats.

    Optimizer 'encoder' columns are ideal model angles (possibly unwrapped),
    prior to applying PCU calibration. Preserve their order and target IDs.
    """
    targets = []
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        names = reader.fieldnames or []
        pairs = (("q_deg", "h_deg"), ("q_encoder_deg", "h_encoder_deg"),
                 ("q_unwrapped_deg", "h_unwrapped_deg"))
        columns = next((pair for pair in pairs if all(name in names for name in pair)), None)
        if columns is None:
            raise ValueError("CSV needs q_deg/h_deg or the existing optimizer/torus angle columns")
        for i, row in enumerate(reader):
            try:
                target = Target(integer(row.get("target_id", row.get("n", i)), "target_id"),
                                finite(row[columns[0]], "q_deg"), finite(row[columns[1]], "h_deg"))
                if all(name in names for name in ("s1", "s2", "s3")):
                    supplied = [finite(row[name], name) for name in ("s1", "s2", "s3")]
                    if not np.allclose(target.stokes, supplied, atol=1e-7, rtol=0):
                        raise ValueError("Stokes columns disagree with the waveplate angles")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid target at CSV line {i + 2}: {exc}") from exc
            targets.append(target)
    if not targets:
        raise ValueError("Scan CSV contains no targets")
    return targets
