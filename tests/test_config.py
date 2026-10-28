"""Configuration precedence, path handling and failures before hardware access."""

from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import DEFAULT_CONFIG, load_settings
from measure_scan import main, parser


class ConfigurationTest(unittest.TestCase):
    def test_project_defaults_are_loaded(self):
        args = parser().parse_args([])
        self.assertEqual(args.config, str(DEFAULT_CONFIG))
        self.assertEqual(args.samples, 4096)
        self.assertEqual(args.channels, [1])
        self.assertEqual(args.output, str(DEFAULT_CONFIG.parent / "data" / "measurements.csv"))
        self.assertIsNone(args.pcu_resource)
        self.assertIsNone(args.mpm_resource)

    def test_partial_file_and_explicit_cli_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.toml"
            path.write_text('[scan]\nsamples = 12\n[mpm]\nchannels = [2, 4]\n'
                            '[pcu]\nresource = "pcu"\nq_offset_deg = 8.0\n')
            args = parser().parse_args(["--config", str(path), "--samples", "3", "--q-offset", "0"])
            self.assertEqual(args.samples, 3)
            self.assertEqual(args.channels, [2, 4])
            self.assertEqual(args.q_offset, 0)
            self.assertEqual(args.pcu_resource, "pcu")
            self.assertEqual(args.wavelength_nm, 1550)

    def test_paths_use_the_file_that_defined_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            path = folder / "lab.toml"
            path.write_text('[scan]\ntargets_csv = "targets.csv"\n'
                            '[measurement]\noutput = "results/out.csv"\n')
            args = parser().parse_args(["--config", str(path)])
            self.assertEqual(args.targets_csv, str(folder / "targets.csv"))
            self.assertEqual(args.output, str(folder / "results" / "out.csv"))
            override = parser().parse_args(["--config", str(path), "--output", "explicit.csv"])
            self.assertEqual(override.output, "explicit.csv")
            self.assertEqual(load_settings(path)["optimization"]["output"],
                             str(DEFAULT_CONFIG.parent / "data" / "movement_results"))

    def test_invalid_settings_fail_before_visa_or_output(self):
        invalid = ('[scna]\nsamples = 2', '[mpm]\nchanels = [1]',
                   '[scan]\nsamples = true', '[scan]\nsamples = "2"',
                   '[scan]\nsamples = 0', '[scan]\nratio = nan',
                   '[scan]\nmode = "wrong"', '[mpm]\nchannels = [1, 1]',
                   '[mpm]\nchannels = []', '[pcu]\nq_sign = 0',
                   '[measurement]\noutput = ""', '[measurement]\nprogress_every = 0',
                   '[mpm]\naveraging_ms = 0.011', '[mpm]\naveraging_ms = 10000',
                   '[scan\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.toml"
            output = Path(tmp) / "output.csv"
            for content in invalid:
                with self.subTest(content=content):
                    path.write_text(content)
                    with patch("measure_scan.resource_manager") as manager, redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as failure:
                            main(["--config", str(path), "--dry-run", "--output", str(output)])
                        self.assertEqual(failure.exception.code, 2)
                        manager.assert_not_called()
                    self.assertFalse(output.exists())

    def test_missing_config_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser().parse_args(["--config", str(Path(tmp) / "missing.toml")])

    def test_parser_reuse_does_not_keep_previous_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.toml"
            path.write_text('[scan]\nsamples = 2\n')
            instance = parser()
            self.assertEqual(instance.parse_args(["--config", str(path)]).samples, 2)
            self.assertEqual(instance.parse_args([]).samples, 4096)

    def test_default_config_is_independent_of_working_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                self.assertEqual(parser().parse_args([]).config, str(DEFAULT_CONFIG))
            finally:
                os.chdir(original)


if __name__ == "__main__":
    unittest.main()
