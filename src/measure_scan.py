"""Measure existing Poincare scans using a PCU-200 and Santec MPM via PyVISA.

Examples and calibration assumptions are in README.md. All scans use discrete
move/wait/read acquisition; torus sampling does not command continuous motion.
"""

from contextlib import ExitStack
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

from instruments import PCU200, SantecMPM
from instruments.visa import finite, resource_manager
from scan_plan import load_plan, make_plan
from config import ConfigParser


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def acquire(targets, controller, meter, *, settle_s=0.1):
    """Yield only completed measurements; drivers can be replaced independently."""
    settle_s = finite(settle_s, "settle_s", 0)
    start = time.monotonic()
    for step, target in enumerate(targets):
        commanded = controller.encoder_angles(target.q_deg, target.h_deg)
        actual = controller.move_to(target.q_deg, target.h_deg)
        time.sleep(settle_s)
        powers = meter.read_power()
        yield {"step": step, "target_id": target.target_id,
               "timestamp_utc": utc_now(), "elapsed_s": time.monotonic() - start,
               "q_deg": target.q_deg, "h_deg": target.h_deg,
               "q_command_deg": commanded[0], "h_command_deg": commanded[1],
               "q_readback_deg": actual[0], "h_readback_deg": actual[1],
               **dict(zip(("s1_model", "s2_model", "s3_model"), target.stokes)),
               **{f"power_ch{ch}_{meter.unit}": value for ch, value in powers.items()}}


def preview(targets, output, args):
    """Export model and calibrated command angles without importing PyVISA."""
    with output.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["step", "target_id", "q_deg", "h_deg", "q_command_deg",
                         "h_command_deg", "s1", "s2", "s3"])
        for step, target in enumerate(targets):
            q = (args.q_sign * target.q_deg + args.q_offset) % 360
            h = (args.h_sign * target.h_deg + args.h_offset) % 360
            writer.writerow([step, target.target_id, target.q_deg, target.h_deg, q, h, *target.stokes])
    print(f"Preview: {len(targets)} targets saved to {output}; no instruments connected.")


def measure(targets, output, args):
    metadata_path = output.with_suffix(output.suffix + ".json")
    # Refuse overwrite before opening instruments or changing their state.
    if output.exists() or metadata_path.exists():
        raise FileExistsError(f"Choose a new output path: {output} or its metadata already exists")
    metadata = {"started_utc": utc_now(), "status": "initializing", "completed_points": 0,
                "total_points": len(targets), "settings": vars(args),
                "stokes_source": "ideal model, not measured; requires optical calibration"}
    fields = ["step", "target_id", "timestamp_utc", "elapsed_s", "q_deg", "h_deg",
              "q_command_deg", "h_command_deg", "q_readback_deg", "h_readback_deg",
              "s1_model", "s2_model", "s3_model"]
    fields += [f"power_ch{ch}_{args.unit}" for ch in args.channels]
    with output.open("x", newline="", encoding="utf-8") as stream, metadata_path.open("x", encoding="utf-8") as meta:
        def save_metadata():
            meta.seek(0)
            json.dump(metadata, meta, indent=2)
            meta.truncate()
            meta.flush()

        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        stream.flush()
        save_metadata()
        try:
            with ExitStack() as stack:
                manager = resource_manager(args.backend)
                stack.callback(manager.close)
                pcu = stack.enter_context(PCU200(
                    args.pcu_resource, manager=manager, timeout_ms=args.timeout_ms,
                    module=args.pcu_module, q_offset_deg=args.q_offset, h_offset_deg=args.h_offset,
                    q_sign=args.q_sign, h_sign=args.h_sign, motion_timeout_s=args.motion_timeout,
                    poll_interval_s=args.poll_interval,
                    angle_tolerance_deg=args.angle_tolerance))
                pcu_id = pcu.identify()
                if "PCU-200" not in pcu_id.upper().replace("PCU200", "PCU-200"):
                    raise RuntimeError(f"Expected PCU-200, got {pcu_id!r}")
                meter = stack.enter_context(SantecMPM(
                    args.mpm_resource, manager=manager, timeout_ms=args.timeout_ms,
                    module=args.mpm_module, channels=args.channels,
                    command_delay_s=args.mpm_command_delay))
                meter_ids = meter.configure(wavelength_nm=args.wavelength_nm,
                                           averaging_ms=args.averaging_ms, unit=args.unit)
                metadata.update(pcu_identity=pcu_id, mpm=meter_ids, status="running")
                save_metadata()
                for row in acquire(targets, pcu, meter, settle_s=args.settle):
                    writer.writerow(row)
                    stream.flush()
                    metadata["completed_points"] += 1
                    save_metadata()
                    count = metadata["completed_points"]
                    if count == 1 or count % args.progress_every == 0 or count == len(targets):
                        print(f"Measured {count}/{len(targets)}", flush=True)
            metadata["status"] = "complete"
        except BaseException as exc:
            metadata["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            metadata["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            metadata["finished_utc"] = utc_now()
            save_metadata()
    print(f"Saved {len(targets)} measurements to {output}")


def parser():
    p = ConfigParser(description=__doc__)
    p.add_argument("--scan", choices=("raster", "torus", "equal-area", "uniform-angle"))
    p.add_argument("--samples", type=int, help="Total targets (raster uses q/h steps)")
    p.add_argument("--q-steps", type=int)
    p.add_argument("--h-steps", type=int)
    p.add_argument("--ratio", type=float, help="Torus frequency ratio")
    p.add_argument("--targets-csv", help="Use an exported scan/optimizer CSV instead of --scan")
    p.add_argument("--output")
    p.add_argument("--dry-run", action="store_true", help="Export target/command angles without hardware")
    p.add_argument("--list-resources", action="store_true")
    p.add_argument("--backend", help="PyVISA backend, e.g. @py, or a vendor VISA library path")
    p.add_argument("--pcu-resource", help="PCU VISA address, e.g. TCPIP0::192.168.1.10::5025::SOCKET")
    p.add_argument("--mpm-resource", help="MPM VISA address, e.g. TCPIP0::192.168.1.161::5000::SOCKET")
    p.add_argument("--pcu-module", type=int)
    p.add_argument("--mpm-module", type=int, choices=range(5))
    p.add_argument("--channels", type=int, nargs="+")
    p.add_argument("--wavelength-nm", type=float)
    p.add_argument("--averaging-ms", type=float)
    p.add_argument("--unit", choices=("dBm", "mW"))
    p.add_argument("--settle", type=float, help="Extra settle seconds after verified motion")
    p.add_argument("--timeout-ms", type=int)
    p.add_argument("--motion-timeout", type=float, help="Deadline per motion wait, seconds")
    p.add_argument("--angle-tolerance", type=float, help="Encoder readback tolerance, degrees")
    p.add_argument("--q-offset", type=float)
    p.add_argument("--h-offset", type=float)
    p.add_argument("--q-sign", type=int, choices=(-1, 1))
    p.add_argument("--h-sign", type=int, choices=(-1, 1))
    p.add_argument("--poll-interval", type=float, help="PCU status polling interval, seconds")
    p.add_argument("--mpm-command-delay", type=float, help="MPM command delay, seconds (at least 0.01)")
    p.add_argument("--progress-every", type=int, help="Progress report interval in completed points")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.list_resources:
            with resource_manager(args.backend) as manager:
                print("\n".join(manager.list_resources("?*")))
            return 0
        targets = load_plan(args.targets_csv) if args.targets_csv else make_plan(
            args.scan, args.samples, q_steps=args.q_steps, h_steps=args.h_steps, ratio=args.ratio)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if args.dry_run:
            preview(targets, output, args)
        else:
            if not args.pcu_resource or not args.mpm_resource:
                p.error("Set PCU and MPM resources in config.toml or via --pcu-resource/--mpm-resource")
            if args.pcu_resource == args.mpm_resource:
                p.error("PCU and MPM must use different resources")
            measure(targets, output, args)
    except KeyboardInterrupt:
        print("Interrupted. Completed measurements are preserved; VISA sessions closed.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Measurement failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
