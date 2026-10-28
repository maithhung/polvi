# Polvi

Poincaré scan visualization and discrete optical-power measurements with a
Santec PCU-200 polarization controller and Santec MPM-220 over PyVISA
(with MPM-210/210H compatibility).

## Project layout

```text
config.toml              Scan, instrument, measurement and optimizer settings
src/                     Python entry points, scan logic and instrument drivers
  instruments/           Separate PCU-200 and Santec MPM drivers
data/                    Target CSVs and measurement CSV/JSON output
  movement_results/      Travel-optimized schedules and summary
  movement_balanced_results/  Balanced schedules and summary
fig/                     Scan figures and optimizer plots
  previews/              Saved HTML/PNG previews
tests/                   Hardware-free regression tests
```

Run the commands below from the project root. Default measurement output is
`data/measurements.csv`. The optimizer writes data to `data/movement_results/`
and plots to `fig/movement_results/`; use `--output` and `--figure-output`
to choose other destinations. Relative CLI paths are relative to your shell;
relative paths in TOML are relative to the file containing them.

## Configuration

Edit `config.toml` to configure scans, VISA backend/timeouts, PCU resource and
calibration, MPM resource/channels/wavelength, measurement settling/output,
and optimization parameters. Measurement and optimizer commands load this file
automatically, regardless of the working directory. Instrument drivers keep
their standalone API defaults and receive the selected settings from the runner.

The PCU and MPM resource strings start empty; fill in your instrument addresses
before measuring. Previewing a scan needs no instrument addresses:

```powershell
uv run python src/main.py --dry-run --output data/preview.csv
uv run python src/main.py
```

An alternate TOML file can override only the settings specific to a lab or run:

```toml
[scan]
samples = 256

[pcu]
resource = "TCPIP0::192.168.1.10::5025::SOCKET"

[mpm]
resource = "TCPIP0::192.168.1.161::5000::SOCKET"
channels = [1, 2]

[measurement]
output = "data/run001.csv"
```

Save this example as `lab.toml` in the project root, then run:

```powershell
uv run python src/main.py --config lab.toml
uv run python src/main.py --config lab.toml --samples 64 --dry-run --output data/preview64.csv
uv run python src/optimize_waveplate_scan.py --config lab.toml --objective balanced --plot
```

Precedence is project `config.toml`, then the alternate file, then explicit CLI
options. Paths inherited from the project config remain relative to the project;
paths supplied by an alternate file are relative to that file. Empty optional
strings disable the corresponding setting (for example `targets_csv = ""`).
Unknown keys, invalid types, and invalid values are rejected before connecting
to instruments. Both measurement metadata and optimizer summaries save the
effective settings and config path. Use `--no-plot` to override `plot = true` in
the optimizer config. `--dry-run` and `--list-resources` are command-line actions.

## Install

Python 3.12 or later:

```powershell
uv sync
# Or, in your Python environment:
python -m pip install -r requirements.txt
```

Install a vendor VISA runtime (NI, Keysight, or R&S) for USB/GPIB access.
For Ethernet sockets you can instead use `uv sync --extra visa-py` and pass
`--backend @py`. PyVISA itself is the Python interface, not the hardware driver.

## Instrument support

| Driver | Supported hardware and acquisition |
| --- | --- |
| `src/instruments/pcu200.py` | PCU-200 USBTMC or Ethernet port 5025; QWP/HWP positions, completion polling, encoder verification |
| `src/instruments/santec_mpm.py` | MPM-220 mainframe with MPM-211/217 (4 ports) or MPM-212 (2 ports); fresh `READ?` acquisition via Ethernet port 5000 or GPIB. Also supports MPM-210/210H with MPM-211/212. |
| `src/instruments/visa.py` | Shared session ownership, timeouts and message transport |

The lab mainframe is an MPM-220. The driver identifies the mainframe with
`*IDN?` and the module in `--mpm-module` with `MMVER?` before configuring it;
the module model does not need to be supplied manually. MPM-213 current modules
and MPM-215 modules are not supported by this acquisition path. In particular,
MPM-215 requires a different acquisition mode; do not bypass the model check.
RS-232 is only supported on the legacy MPM-210/210H, using 115200 baud, 8N1,
with instrument echo off. The MPM-220 uses Ethernet or GPIB.
GPIB read termination is CR; Ethernet/serial use LF with whitespace stripped.
MPM commands retain a 10 ms delay for compatibility with the legacy models.

References:

- [PCU-200 manual, programming guide pp. 17–22](https://santec-inst.files.svdcdn.com/production/PCU-200-User-Manual.pdf?dm=1785166150)
- [MPM-220 manual, remote control chapter 5](https://downloads.santec.com/api/downloads?name=MPM_220_Product_Manual)
- [MPM-210H manual, remote control chapter 5](https://www.santec.com/dcms_media/other/instruments_MPM-210H-M-E.pdf)
- [PyVISA communication and backend setup](https://pyvisa.readthedocs.io/en/latest/introduction/communication.html)

## Preview a scan without hardware

```powershell
uv run python src/main.py --scan equal-area --samples 256 --dry-run --output data/preview.csv
uv run python src/main.py --scan raster --q-steps 31 --h-steps 61 --dry-run --output data/raster_preview.csv
uv run python src/main.py --scan torus --samples 1000 --dry-run --output data/torus_preview.csv
uv run python src/main.py --targets-csv data/movement_balanced_results/batches_of_256.csv --dry-run --output data/optimized_preview.csv
```

`--scan` accepts `raster`, `torus`, `equal-area`, and `uniform-angle`.
It reuses the existing scan functions. `--samples` counts total measurement
targets; raster size is `q_steps * h_steps`. `--ratio` controls the torus ratio.
`--targets-csv` overrides the generated scan and preserves row order and target
IDs. Existing equal-area, torus, and movement-optimizer CSV formats are accepted.
Stokes columns, when supplied, are checked against the angles before connection.
Preview files contain targets and calibrated command angles, without power data.

## Measure

Discover available VISA resources:

```powershell
uv run python src/main.py --list-resources
```

Ethernet socket instruments may need to be specified explicitly even if discovery
does not list them. Replace the example IP addresses with your instruments:

```powershell
uv run python src/main.py --scan equal-area --samples 256 --pcu-resource "TCPIP0::192.168.1.10::5025::SOCKET" --mpm-resource "TCPIP0::192.168.1.161::5000::SOCKET" --mpm-module 0 --channels 1 2 --wavelength-nm 1550 --averaging-ms 5 --settle 0.1 --output data/run001.csv
```

Use a discovered USB resource for the PCU or, for example,
`GPIB0::16::INSTR` for the MPM if those interfaces are connected.
`python src/measure_scan.py` and `python src/main.py` are equivalent entry points.

Each point performs these steps:

1. Map model angles to calibrated PCU encoder angles in [0, 360).
2. Move QWP, then HWP, polling `STAT:OPER:COND?` after each move.
3. Verify both encoder positions, then wait the additional `--settle` interval.
4. Issue a fresh MPM `READ?` for the selected module and check its error queue.
5. Flush the completed measurement to CSV and update the metadata sidecar.

MPM setup selects auto range, power units (`--unit dBm` or `mW`), averaging
time, and wavelength compensation for the selected ports. It stops any existing
MPM logging run. Averaging time is in milliseconds, in 0.01 ms increments;
`--timeout-ms` must exceed it by more than 1000 ms. Wavelength compensation
does not tune the optical source. No laser/source control is included.
The wavelength command range is limited to 1250–1630 nm as specified for
`DWAV` in the MPM-220 manual, even though its optical specifications list a
wider range. Firmware-specific support beyond that command range is not assumed.

The CSV records UTC timestamps, elapsed time, original target ID, model angles,
commanded angles, encoder readbacks, model Stokes coordinates, and power per
selected channel. `run001.csv.json` records configuration, instrument IDs,
completion count and `complete`, `failed`, or `interrupted` status. Existing
outputs are never overwritten. Ctrl+C or a device error preserves completed
rows and closes both sessions. It does not issue a motor stop or return-to-home
command; a move already accepted by the PCU may finish. No automatic resume is
implemented. The instruments retain their final positions and meter settings.

## Optical calibration and motion assumptions

The scan model assumes horizontal input followed by QWP then HWP, with the
angle/Stokes convention in `src/poincare_scan.py`. Establish the actual optical
reference and rotation signs on your bench. The PCU manual does not establish
that its encoder zeros match this model, and output fiber can rotate the SOP.

The mapping is `encoder = (sign * model_angle + offset) % 360` for each plate.
Use `--q-offset`, `--h-offset`, `--q-sign` and `--h-sign` for measured calibration
values. Defaults are zero offsets and positive signs, an uncalibrated assumption.
An MPM measures power, not polarization: `s1_model/s2_model/s3_model` are
predictions, not measured Stokes vectors. Encoder verification cannot confirm SOP.

All acquisition is step-and-measure, including torus scans. Neither constant
motor speed nor simultaneous plate movement is commanded. The optimizer's
unwrapped angle columns are treated as model angles and wrapped to the PCU's
documented position range. Target SOPs/order are preserved, but its predicted
shortest motor travel and timing are not guaranteed by the PCU interface.
`--motion-timeout` bounds each completion wait and `--angle-tolerance` sets
the encoder comparison tolerance (default 0.1 degrees). Set additional settling
based on bench measurements; the default 0.1 seconds is not an accuracy guarantee.

## Modular use

`src/scan_plan.py` produces `Target` objects. `measure_scan.acquire()` accepts a
controller exposing `encoder_angles()` / `move_to()` and a meter exposing
`unit` / `read_power()`. It has no instrument-specific command strings, so
future drivers can reuse the scan workflow. Both concrete drivers are context
managers. A supplied VISA manager remains owned by the caller; a driver-created
manager is closed with the driver.

The existing interactive visualizers still run independently:

```powershell
uv run python src/poincare_scan.py
uv run python src/poincare_torus_scan.py
uv run python src/poincare_equal_area_scan.py
```

Generate optimization data and its figure:

```powershell
uv run python src/optimize_waveplate_scan.py --objective balanced --output data/movement_balanced_results --plot
```

## Validation

```powershell
uv run python -m unittest discover -s tests -v
uv run python src/poincare_scan.py --check
uv run python src/poincare_torus_scan.py --check
uv run python src/poincare_equal_area_scan.py --check
```

Tests use fake VISA resources to check command sequencing, calibration/wrapping,
timeouts, malformed replies, module selection, partial output and cleanup.
Physical instrument communication and optical calibration require a bench test.
