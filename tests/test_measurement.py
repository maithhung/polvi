"""Protocol and sequencing regressions using a fake VISA message resource."""

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

# Scripts also import each other directly when invoked as python src/main.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from instruments import PCU200, SantecMPM
from instruments.visa import VisaInstrument
from measure_scan import acquire, main, measure, parser
from scan_plan import Target, load_plan, make_plan


class Resource:
    def __init__(self, kind="pcu", events=None):
        self.kind = kind
        self.events = events if events is not None else []
        self.commands = []
        self.closed = False
        self.angles = [0., 0.]
        self.responses = {}
        self.mainframe = "MPM-220"
        self.module = "MPM-211"

    def write(self, command):
        self.commands.append(command)
        self.events.append((self.kind, command))
        if command.startswith("POL") and "?" not in command:
            name, angle = command.split()
            self.angles[int(name[-1])] = float(angle)

    def read(self):
        command = self.commands[-1]
        if command in self.responses:
            response = self.responses[command]
            if isinstance(response, list):
                response = response.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response
        if command == "*IDN?":
            return f"SANTEC,{'PCU-200' if self.kind == 'pcu' else self.mainframe},123,1.0"
        if command == "STAT:OPER:COND?":
            return "0"
        if command.startswith("POL"):
            return str(self.angles[int(command[-2])])
        if command.startswith("MMVER?"):
            return f"SANTEC,{self.module},456,1.0"
        if command.startswith("DWAV?"):
            return "1550"
        if command.startswith("DAUTO?"):
            return "1"
        return {"ERR?": '0,"No Error"', "UNIT?": "0", "AVG?": "5",
                "READ? 0": "-10,-11,-12,-13"}[command]

    def close(self):
        self.closed = True


class Manager:
    def __init__(self, resources):
        self.resources = resources
        self.closed = False

    def open_resource(self, address, **kwargs):
        item = self.resources[address]
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


class DriversTest(unittest.TestCase):
    def test_move_wrap_calibration_busy_and_readback(self):
        r = Resource()
        r.responses["STAT:OPER:COND?"] = ["0", "4", "0", "0"]
        with PCU200("pcu", manager=Manager({"pcu": r}), q_offset_deg=10, h_sign=-1) as pcu:
            self.assertEqual(pcu.move_to(-45, 30), (325, 330))
        self.assertTrue(r.closed)
        self.assertEqual(r.commands, ["STAT:OPER:COND?", "POL0:WP0 325.000000000",
                                     "STAT:OPER:COND?", "STAT:OPER:COND?",
                                     "POL0:WP1 330.000000000", "STAT:OPER:COND?",
                                     "POL0:WP0?", "POL0:WP1?"])

    def test_busy_has_deadline_and_restores_io_timeout(self):
        r = Resource()
        r.responses["STAT:OPER:COND?"] = "4"
        with PCU200("pcu", manager=Manager({"pcu": r}), motion_timeout_s=0.003,
                    poll_interval_s=0.001) as pcu:
            with self.assertRaises(TimeoutError):
                pcu.move_to(0, 0)
            self.assertEqual(r.timeout, 10000)
            self.assertFalse(any("WP" in cmd for cmd in r.commands))

    def test_bad_readback_prevents_measurement(self):
        r = Resource()
        r.responses["POL0:WP0?"] = "12"
        with PCU200("pcu", manager=Manager({"pcu": r})) as pcu:
            with self.assertRaises(RuntimeError):
                pcu.move_to(0, 0)

    def test_invalid_angles_send_nothing(self):
        r = Resource()
        with PCU200("pcu", manager=Manager({"pcu": r})) as pcu:
            with self.assertRaises(ValueError):
                pcu.move_to(0, float("nan"))
            self.assertEqual(r.commands, [])

    def test_mpm_setup_channel_mapping_and_terminations(self):
        r = Resource("mpm")
        with SantecMPM("GPIB0::16::INSTR", manager=Manager({"GPIB0::16::INSTR": r}),
                       channels=(4, 2), command_delay_s=0) as mpm:
            mpm.configure()
            self.assertEqual(mpm.read_power(), {4: -13, 2: -11})
            self.assertEqual(r.read_termination, "\r")
            self.assertEqual(r.write_termination, "\n")
        self.assertIn("DAUTO 0,1", r.commands)
        self.assertIn("DWAV 0,4,1550.000", r.commands)
        self.assertEqual(r.commands[-2:], ["READ? 0", "ERR?"])

    def test_mpm_rejects_wrong_model_and_current_module(self):
        for model, module in (("MPM-999", "MPM-211"), ("MPM-220", "MPM-213"),
                              ("MPM-220", "MPM-215"), ("MPM-220", "MPM-999")):
            with self.subTest(model=model, module=module):
                r = Resource("mpm")
                r.mainframe, r.module = model, module
                with SantecMPM("mpm", manager=Manager({"mpm": r}), command_delay_s=0) as mpm:
                    with self.assertRaises(RuntimeError):
                        mpm.configure()
                self.assertNotIn("STOP", r.commands)

    def test_mpm220_module_detection_and_legacy_compatibility(self):
        cases = (("MPM-220", "MPM-211", 4), ("MPM-220", "MPM-212", 2),
                 ("MPM-220", "MPM-217", 4), ("MPM-210", "MPM-211", 4),
                 ("MPM-210H", "MPM-211", 4))
        for model, module, count in cases:
            with self.subTest(model=model, module=module):
                address = "TCPIP0::192.168.1.161::5000::SOCKET"
                r = Resource("mpm")
                r.mainframe, r.module = model, module
                r.responses["READ? 3"] = ",".join(str(-10 - i) for i in range(count))
                with SantecMPM(address, manager=Manager({address: r}), module=3,
                               channels=tuple(range(1, count + 1)), command_delay_s=0) as meter:
                    ids = meter.configure()
                    self.assertIn(model, ids["identity"])
                    self.assertIn(module, ids["module_identity"])
                    self.assertEqual(meter.read_power()[count], -9 - count)
                    self.assertEqual(r.read_termination, "\n")
                    self.assertEqual(r.write_termination, "\n")
                self.assertIn("MMVER? 3", r.commands)
                self.assertIn("DAUTO 3,1", r.commands)
                self.assertIn(f"DWAV 3,{count},1550.000", r.commands)
                self.assertIn("READ? 3", r.commands)

    def test_mpm220_linear_power_units(self):
        r = Resource("mpm")
        r.responses.update({"UNIT?": "1", "READ? 0": "0.1,0.2,0.3,0.4"})
        with SantecMPM("mpm", manager=Manager({"mpm": r}), command_delay_s=0) as meter:
            meter.configure(unit="mW")
            self.assertEqual(meter.unit, "mW")
            self.assertEqual(meter.read_power(), {1: 0.1})
        self.assertIn("UNIT 1", r.commands)

    def test_invalid_power_error_and_wrong_channel_count(self):
        for response in ("nan,-11,-12,-13", "-10", "OVER,-11,-12,-13"):
            with self.subTest(response=response):
                r = Resource("mpm")
                with SantecMPM("mpm", manager=Manager({"mpm": r}), command_delay_s=0) as mpm:
                    mpm.configure()
                    r.responses["READ? 0"] = response
                    with self.assertRaises(RuntimeError):
                        mpm.read_power()
        r = Resource("mpm")
        r.responses["ERR?"] = '-222,"Data out of range"'
        with SantecMPM("mpm", manager=Manager({"mpm": r}), command_delay_s=0) as mpm:
            with self.assertRaisesRegex(RuntimeError, "-222"):
                mpm.configure()

    def test_invalid_channel_or_timeout_before_setup_writes(self):
        r = Resource("mpm")
        r.module = "MPM-212"
        with SantecMPM("mpm", manager=Manager({"mpm": r}), channels=(3,), command_delay_s=0) as mpm:
            with self.assertRaises(ValueError):
                mpm.configure()
            self.assertNotIn("STOP", r.commands)
        with SantecMPM("mpm", manager=Manager({"mpm": r}), command_delay_s=0) as mpm:
            with self.assertRaises(ValueError):
                mpm.configure(averaging_ms=10000)

    def test_owned_manager_cleanup_on_open_failure(self):
        manager = Manager({"bad": OSError("cannot open")})
        with patch("instruments.visa.resource_manager", return_value=manager):
            with self.assertRaises(OSError):
                VisaInstrument("bad")
        self.assertTrue(manager.closed)


class PlanTest(unittest.TestCase):
    def test_all_generators_and_torus_sample_count(self):
        from poincare_equal_area_scan import scan_targets
        from poincare_torus_scan import trajectory
        for mode in ("equal-area", "uniform-angle"):
            plan = make_plan(mode, 12)
            np.testing.assert_allclose([p.stokes for p in plan], scan_targets(12, mode)[-1])
        np.testing.assert_allclose([p.stokes for p in make_plan("torus", 12)], trajectory(11)[-1])
        self.assertEqual(len(make_plan("torus", 1)), 1)
        raster = make_plan("raster", q_steps=2, h_steps=3)
        self.assertEqual([p.h_deg for p in raster], [0, 45, 90, 90, 45, 0])

    def test_exported_optimizer_and_equal_area_files(self):
        root = Path(__file__).resolve().parents[1] / "data"
        for name in ("poincare_equal_area_targets.csv", "movement_balanced_results/batches_of_256.csv"):
            path = root / name
            if path.exists():
                targets = load_plan(path)
                self.assertEqual(len(targets), 4096)
                self.assertEqual(targets[0].target_id, 0)

    def test_bad_csv_before_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            for content in ("q_deg,h_deg\nnan,0\n", "q_deg,h_deg\n", "foo,bar\n1,2\n",
                            "q_deg,h_deg,s1,s2,s3\n0,0,0,0,1\n"):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    load_plan(path)


class WorkflowTest(unittest.TestCase):
    def test_complete_scan_metadata_and_resource_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            pcu_r, mpm_r = Resource(), Resource("mpm")
            manager = Manager({"pcu": pcu_r, "mpm": mpm_r})
            config_path = Path(tmp) / "lab.toml"
            config_path.write_text('[pcu]\nresource = "pcu"\nq_offset_deg = 12.0\n'
                                   'poll_interval_s = 0.002\n[mpm]\nresource = "mpm"\n'
                                   'channels = [1, 4]\ncommand_delay_s = 0.02\n'
                                   '[measurement]\nsettle_s = 0.0\nprogress_every = 1\n')
            args = parser().parse_args(["--config", str(config_path)])
            output = Path(tmp) / "run.csv"
            with patch("measure_scan.resource_manager", return_value=manager):
                measure(make_plan(samples=2), output, args)
            metadata = json.loads(output.with_suffix(".csv.json").read_text())
            self.assertEqual(metadata["status"], "complete")
            self.assertEqual(metadata["completed_points"], 2)
            self.assertEqual(metadata["settings"]["config"], str(config_path.resolve()))
            self.assertEqual(metadata["settings"]["q_offset"], 12)
            self.assertEqual(metadata["settings"]["mpm_command_delay"], 0.02)
            self.assertIn("MPM-211", metadata["mpm"]["module_identity"])
            self.assertIn("MPM-220", metadata["mpm"]["identity"])
            with output.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 2)
            self.assertEqual(float(rows[1]["power_ch4_dBm"]), -13)
            self.assertEqual(float(rows[0]["q_command_deg"]), 12)
            self.assertTrue(manager.closed and pcu_r.closed and mpm_r.closed)

    def test_settle_before_fresh_measurement(self):
        events = []
        pcu_r, mpm_r = Resource(events=events), Resource("mpm", events)
        manager = Manager({"pcu": pcu_r, "mpm": mpm_r})
        with PCU200("pcu", manager=manager) as pcu, SantecMPM("mpm", manager=manager, command_delay_s=0) as meter:
            meter.configure()
            events.clear()
            with patch("measure_scan.time.sleep", side_effect=lambda seconds: events.append(("sleep", seconds))):
                rows = list(acquire([Target(7, -45, 22.5)], pcu, meter, settle_s=0.123))
        self.assertLess(events.index(("pcu", "POL0:WP1?")), events.index(("sleep", 0.123)))
        self.assertLess(events.index(("sleep", 0.123)), events.index(("mpm", "READ? 0")))
        self.assertEqual(rows[0]["target_id"], 7)
        self.assertEqual(rows[0]["power_ch1_dBm"], -10)

    def test_partial_csv_and_cleanup_on_failure_or_interrupt(self):
        for failure in (OSError("read failed"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                pcu_r, mpm_r = Resource(), Resource("mpm")
                # A completed point, then a failed point must leave exactly one row.
                mpm_r.responses["READ? 0"] = ["-10,-11,-12,-13", failure]
                manager = Manager({"pcu": pcu_r, "mpm": mpm_r})
                args = parser().parse_args(["--pcu-resource", "pcu", "--mpm-resource", "mpm", "--settle", "0"])
                output = Path(tmp) / "measurements.csv"
                with patch("measure_scan.resource_manager", return_value=manager):
                    with self.assertRaises(type(failure)):
                        measure(make_plan(samples=2), output, args)
                with output.open(newline="") as stream:
                    self.assertEqual(len(list(csv.DictReader(stream))), 1)
                metadata = json.loads(output.with_suffix(".csv.json").read_text())
                self.assertEqual(metadata["completed_points"], 1)
                self.assertIn(metadata["status"], ("failed", "interrupted"))
                self.assertTrue(manager.closed and pcu_r.closed and mpm_r.closed)

    def test_second_open_failure_closes_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Resource()
            manager = Manager({"pcu": r, "mpm": OSError("missing MPM")})
            args = parser().parse_args(["--pcu-resource", "pcu", "--mpm-resource", "mpm"])
            with patch("measure_scan.resource_manager", return_value=manager):
                with self.assertRaises(OSError):
                    measure(make_plan(samples=1), Path(tmp) / "data.csv", args)
            self.assertTrue(r.closed and manager.closed)

    def test_dry_run_never_opens_visa_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "preview.csv"
            with patch("measure_scan.resource_manager", side_effect=AssertionError("No hardware")):
                args = ["--dry-run", "--samples", "3", "--output", str(output)]
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 1)
            with output.open(newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 3)


if __name__ == "__main__":
    unittest.main()
