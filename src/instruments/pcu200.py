"""Santec PCU-200, manual M-PCU-200-001.02, programming guide pp. 17–22.

WP0 is QWP; WP1 is HWP. Public angles are the scan's model angles.
Encoder = (sign * model_angle + offset) modulo 360 degrees. Offsets and
signs require optical calibration; encoder readback is not polarimetry.
"""

import time

from .visa import VisaInstrument, finite, integer


class PCU200(VisaInstrument):
    def __init__(self, address, *, module=0, q_offset_deg=0, h_offset_deg=0,
                 q_sign=1, h_sign=1, motion_timeout_s=30, poll_interval_s=0.05,
                 angle_tolerance_deg=0.1, **kwargs):
        self.module = integer(module, "PCU module")
        self.offsets = (finite(q_offset_deg, "QWP offset"), finite(h_offset_deg, "HWP offset"))
        if q_sign not in (-1, 1) or h_sign not in (-1, 1):
            raise ValueError("Waveplate signs must be +1 or -1")
        self.signs = (q_sign, h_sign)
        self.motion_timeout_s = finite(motion_timeout_s, "motion timeout", 0.001)
        self.poll_interval_s = finite(poll_interval_s, "poll interval", 0.001)
        self.angle_tolerance_deg = finite(angle_tolerance_deg, "angle tolerance", 0, 180)
        super().__init__(address, **kwargs)

    def encoder_angles(self, q_deg, h_deg):
        return tuple((sign * finite(angle, "waveplate angle") + offset) % 360
                     for angle, sign, offset in zip((q_deg, h_deg), self.signs, self.offsets))

    def wait_until_idle(self):
        deadline = time.monotonic() + self.motion_timeout_s
        original_timeout = self.resource.timeout
        try:
            # The manual's polling example delays before its first query so
            # the asynchronous command can enter the operation state.
            time.sleep(min(self.poll_interval_s, self.motion_timeout_s))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("PCU-200 motion did not finish before the deadline")
                self.resource.timeout = max(1, min(original_timeout, int(remaining * 1000)))
                status = integer(self.query("STAT:OPER:COND?"), "PCU operation status")
                if status == 0:
                    return
                time.sleep(min(self.poll_interval_s, max(0, deadline - time.monotonic())))
        finally:
            self.resource.timeout = original_timeout

    def read_angles(self):
        """Return actual encoder QWP/HWP positions in degrees."""
        return tuple(finite(self.query(f"POL{self.module}:WP{wp}?"), "encoder angle", 0, 360)
                     for wp in (0, 1))

    def move_to(self, q_deg, h_deg):
        """Move, wait, and verify both positions before returning readbacks.

        Commands are serialized because the manual does not promise concurrent
        waveplate motion. No assumption is made about shortest-path rotation.
        """
        targets = self.encoder_angles(q_deg, h_deg)
        self.wait_until_idle()
        for wp, angle in enumerate(targets):
            self.write(f"POL{self.module}:WP{wp} {angle:.9f}")
            self.wait_until_idle()
        actual = self.read_angles()
        for wp, (expected, measured) in enumerate(zip(targets, actual)):
            error = abs((measured - expected + 180) % 360 - 180)
            if error > self.angle_tolerance_deg:
                raise RuntimeError(f"PCU WP{wp}: requested {expected:g}°, read {measured:g}°")
        return actual
