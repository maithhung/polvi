"""Load TOML settings and merge explicit CLI overrides without opening hardware.

The project config.toml is the default source. An alternate config overlays it;
paths are resolved relative to the file supplying each value. Drivers remain
independent of application configuration.
"""

import argparse
import math
from pathlib import Path
import sys
import tomllib

from project_paths import PROJECT_ROOT

DEFAULT_CONFIG = PROJECT_ROOT / "config.toml"

# TOML section/key -> command-line destination and required value type.
FIELDS = {
    "scan": {
        "mode": ("scan", str), "samples": ("samples", int),
        "q_steps": ("q_steps", int), "h_steps": ("h_steps", int),
        "ratio": ("ratio", float), "targets_csv": ("targets_csv", str),
    },
    "visa": {"backend": ("backend", str), "timeout_ms": ("timeout_ms", int)},
    "pcu": {
        "resource": ("pcu_resource", str), "module": ("pcu_module", int),
        "q_offset_deg": ("q_offset", float), "h_offset_deg": ("h_offset", float),
        "q_sign": ("q_sign", int), "h_sign": ("h_sign", int),
        "motion_timeout_s": ("motion_timeout", float),
        "poll_interval_s": ("poll_interval", float),
        "angle_tolerance_deg": ("angle_tolerance", float),
    },
    "mpm": {
        "resource": ("mpm_resource", str), "module": ("mpm_module", int),
        "channels": ("channels", list), "wavelength_nm": ("wavelength_nm", float),
        "averaging_ms": ("averaging_ms", float), "unit": ("unit", str),
        "command_delay_s": ("mpm_command_delay", float),
    },
    "measurement": {
        "output": ("output", str), "settle_s": ("settle", float),
        "progress_every": ("progress_every", int),
    },
    "optimization": {
        "samples": ("samples", int), "batch_size": ("batch_size", int),
        "passes": ("passes", int), "objective": ("objective", str),
        "q_speed": ("q_speed", float), "h_speed": ("h_speed", float),
        "output": ("output", str), "figure_output": ("figure_output", str),
        "plot": ("plot", bool),
    },
}
SECTIONS = {
    "measurement": ("scan", "visa", "pcu", "mpm", "measurement"),
    "optimization": ("optimization",),
}
OPTIONAL = {"backend", "pcu_resource", "mpm_resource", "targets_csv", "figure_output"}
PATHS = {"output", "targets_csv", "figure_output"}
LIMITS = {
    "samples": (1, None), "q_steps": (1, None), "h_steps": (1, None),
    "ratio": (1e-15, None), "timeout_ms": (1, None),
    "pcu_module": (0, None), "mpm_module": (0, 4),
    "motion_timeout": (0.001, None), "poll_interval": (0.001, None),
    "angle_tolerance": (0, 180), "wavelength_nm": (1250, 1630),
    "averaging_ms": (0.01, 10000), "mpm_command_delay": (0.01, None),
    "settle": (0, None), "progress_every": (1, None),
    "batch_size": (1, None), "passes": (0, None),
    "q_speed": (1e-15, None), "h_speed": (1e-15, None),
}
CHOICES = {
    "scan": ("raster", "torus", "equal-area", "uniform-angle"),
    "unit": ("dBm", "mW"), "q_sign": (-1, 1), "h_sign": (-1, 1),
    "objective": ("travel", "time", "balanced"),
}


def validate_value(name, value, expected):
    if value is None and name in OPTIONAL:
        return
    valid_type = type(value) in (int, float) if expected is float else type(value) is expected
    if not valid_type:
        raise ValueError(f"{name} must be {expected.__name__}, got {value!r}")
    if expected in (int, float):
        low, high = LIMITS.get(name, (None, None))
        if (not math.isfinite(value) or (low is not None and value < low) or
                (high is not None and value > high)):
            raise ValueError(f"Invalid {name}: {value}")
    if name in CHOICES and value not in CHOICES[name]:
        raise ValueError(f"{name} must be one of {CHOICES[name]}")
    if expected is str and not value.strip() and name not in OPTIONAL:
        raise ValueError(f"{name} must not be empty")
    if name == "channels" and (not value or any(type(ch) is not int or ch not in range(1, 5) for ch in value)
                               or len(set(value)) != len(value)):
        raise ValueError("channels must contain unique integers from 1 to 4")


def load_settings(path=DEFAULT_CONFIG):
    """Load all sections, rejecting misspellings, wrong types and invalid values."""
    path = Path(path).resolve()
    merged = {section: {} for section in FIELDS}
    sources = [DEFAULT_CONFIG] if path == DEFAULT_CONFIG else [DEFAULT_CONFIG, path]
    for source in sources:
        with source.open("rb") as stream:
            document = tomllib.load(stream)
        for section, values in document.items():
            if section not in FIELDS or not isinstance(values, dict):
                raise ValueError(f"{source}: unknown or invalid section [{section}]")
            for key, value in values.items():
                if key not in FIELDS[section]:
                    raise ValueError(f"{source}: unknown setting {section}.{key}")
                name, expected = FIELDS[section][key]
                validate_value(name, value, expected)
                if name in OPTIONAL and isinstance(value, str) and not value.strip():
                    value = None
                if name in PATHS and value is not None:
                    value = str((source.parent / value).resolve())
                merged[section][key] = value
    for section, fields in FIELDS.items():
        missing = fields.keys() - merged[section].keys()
        if missing:
            raise ValueError(f"Missing settings in [{section}]: {', '.join(sorted(missing))}")
    return merged


class ConfigParser(argparse.ArgumentParser):
    """Standard argparse interface with TOML defaults and CLI precedence."""

    def __init__(self, *args, config_kind="measurement", **kwargs):
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)
        self.config_kind = config_kind
        self.add_argument("--config", default=str(DEFAULT_CONFIG), metavar="TOML",
                          help="Settings file to overlay on the project config.toml")

    def parse_args(self, args=None, namespace=None):
        argv = list(sys.argv[1:] if args is None else args)
        selector = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
        selector.add_argument("--config", default=str(DEFAULT_CONFIG))
        selected, _ = selector.parse_known_args(argv)
        path = Path(selected.config).resolve()
        try:
            settings = load_settings(path)
            defaults = {FIELDS[section][key][0]: value
                        for section in SECTIONS[self.config_kind]
                        for key, value in settings[section].items()}
            self.set_defaults(**defaults)
            result = super().parse_args(argv, namespace)
            result.config = str(path)
            for section in SECTIONS[self.config_kind]:
                for name, expected in FIELDS[section].values():
                    validate_value(name, getattr(result, name), expected)
            if self.config_kind == "measurement":
                if result.timeout_ms <= result.averaging_ms + 1000:
                    raise ValueError("Timeout must exceed averaging time by more than 1000 ms")
                if abs(result.averaging_ms * 100 - round(result.averaging_ms * 100)) > 1e-7:
                    raise ValueError("Averaging time must be a multiple of 0.01 ms")
            return result
        except (OSError, ValueError) as exc:
            self.error(str(exc))
