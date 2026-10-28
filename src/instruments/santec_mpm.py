"""Santec MPM-220 and compatible MPM-210/210H READ? driver.

References: MPM-220 Operation Manual, chapter 5 (especially 5.4.2–5.4.4),
and MPM-210H Operation Manual, chapter 5. MPM-211/212/217 optical modules
are supported. MPM-213 is a current meter; MPM-215 needs a different
acquisition mode. Neither is accepted here.
"""

from .visa import VisaInstrument, finite, integer


def model_from_idn(response):
    fields = response.split(",")
    if len(fields) < 2 or "SANTEC" not in fields[0].upper():
        raise RuntimeError(f"Unexpected Santec identification: {response!r}")
    return fields[1].strip().upper()


class SantecMPM(VisaInstrument):
    def __init__(self, address, *, module=0, channels=(1,), **kwargs):
        self.module = integer(module, "MPM module", 0, 4)
        self.channels = tuple(integer(ch, "MPM channel", 1, 4) for ch in channels)
        if not self.channels or len(set(self.channels)) != len(self.channels):
            raise ValueError("Select at least one channel, without duplicates")
        self.module_model = None
        self.mainframe_model = None
        self.unit = None
        if address.upper().startswith("GPIB"):
            kwargs.setdefault("read_termination", "\r")
        else:
            kwargs.setdefault("read_termination", "\n")
        kwargs.setdefault("command_delay_s", 0.01)
        super().__init__(address, **kwargs)
        if address.upper().startswith("ASRL"):
            try:
                from pyvisa.constants import Parity, StopBits
                self.resource.baud_rate = 115200
                self.resource.data_bits = 8
                self.resource.parity = Parity.none
                self.resource.stop_bits = StopBits.one
            except BaseException:
                self.close()
                raise

    def check_error(self):
        response = self.query("ERR?")
        try:
            code = int(response.split(",", 1)[0])
        except ValueError as exc:
            raise RuntimeError(f"Invalid MPM error response: {response!r}") from exc
        if code:
            raise RuntimeError(f"MPM instrument error: {response}")

    def configure(self, *, wavelength_nm=1550, averaging_ms=5, unit="dBm"):
        wavelength_nm = finite(wavelength_nm, "wavelength_nm", 1250, 1630)
        averaging_ms = finite(averaging_ms, "averaging_ms", 0.01, 10000)
        if abs(averaging_ms * 100 - round(averaging_ms * 100)) > 1e-7:
            raise ValueError("Averaging time must be a multiple of 0.01 ms")
        if unit not in ("dBm", "mW"):
            raise ValueError("Power unit must be dBm or mW")
        if self.resource.timeout <= averaging_ms + 1000:
            raise ValueError("VISA timeout must exceed averaging time by more than 1000 ms")
        identity = self.identify()
        self.mainframe_model = model_from_idn(identity)
        if self.mainframe_model not in ("MPM-210", "MPM-210H", "MPM-220"):
            raise RuntimeError(f"Unsupported MPM mainframe: {identity}")
        module_identity = self.query(f"MMVER? {self.module}")
        self.module_model = model_from_idn(module_identity)
        supported = ("MPM-211", "MPM-212", "MPM-217") if self.mainframe_model == "MPM-220" else ("MPM-211", "MPM-212")
        if self.module_model not in supported:
            raise RuntimeError(f"READ power acquisition on {self.mainframe_model} supports "
                               f"{', '.join(supported)}, got {module_identity}")
        if self.module_model == "MPM-212" and max(self.channels) > 2:
            raise ValueError("MPM-212 only has channels 1 and 2")
        self.check_error()
        self.write("STOP")
        self.write(f"UNIT {0 if unit == 'dBm' else 1}")
        self.write(f"AVG {averaging_ms:.2f}")
        self.write(f"DAUTO {self.module},1")
        for channel in self.channels:
            self.write(f"DWAV {self.module},{channel},{wavelength_nm:.3f}")
        self.check_error()
        if int(self.query("UNIT?")) != (0 if unit == "dBm" else 1):
            raise RuntimeError("MPM did not accept the power unit")
        if abs(finite(self.query("AVG?"), "average readback") - averaging_ms) > 0.005:
            raise RuntimeError("MPM did not accept the averaging time")
        if int(self.query(f"DAUTO? {self.module}")) != 1:
            raise RuntimeError("MPM did not accept auto range")
        for channel in self.channels:
            actual = finite(self.query(f"DWAV? {self.module},{channel}"), "wavelength readback")
            if abs(actual - wavelength_nm) > 0.001:
                raise RuntimeError("MPM did not accept the wavelength")
        self.unit = unit
        return {"identity": identity, "module_identity": module_identity}

    def read_power(self):
        """One fresh acquisition for the selected module, mapped to channel IDs."""
        if self.unit is None:
            raise RuntimeError("Configure the MPM before reading power")
        response = self.query(f"READ? {self.module}")
        fields = response.split(",")
        expected = (2, 4) if self.module_model == "MPM-212" else (4,)
        if len(fields) not in expected:
            raise RuntimeError(f"Unexpected MPM channel count: {response!r}")
        try:
            values = {ch: finite(fields[ch - 1], f"power channel {ch}") for ch in self.channels}
        except ValueError as exc:
            raise RuntimeError(f"Invalid MPM power response: {response!r}") from exc
        self.check_error()
        return values
