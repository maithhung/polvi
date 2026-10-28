"""Small shared PyVISA transport; injected managers permit hardware-free tests."""

import math
import time


def finite(value, name, minimum=None, maximum=None):
    value = float(value)
    if (not math.isfinite(value) or
            (minimum is not None and value < minimum) or
            (maximum is not None and value > maximum)):
        raise ValueError(f"Invalid {name}: {value}")
    return value


def integer(value, name, minimum=0, maximum=None):
    number = finite(value, name, minimum, maximum)
    if number != int(number):
        raise ValueError(f"{name} must be an integer")
    return int(number)


def resource_manager(backend=None):
    import pyvisa
    return pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()


class VisaInstrument:
    def __init__(self, address, *, manager=None, backend=None, timeout_ms=10000,
                 read_termination="\n", write_termination="\n", command_delay_s=0):
        self.address = address
        timeout_ms = integer(timeout_ms, "timeout_ms", 1)
        self.command_delay_s = finite(command_delay_s, "command_delay_s", 0)
        self._owns_manager = manager is None
        self.manager = manager if manager is not None else resource_manager(backend)
        self.resource = None
        try:
            self.resource = self.manager.open_resource(address, open_timeout=timeout_ms)
            self.resource.timeout = timeout_ms
            self.resource.read_termination = read_termination
            self.resource.write_termination = write_termination
        except BaseException:
            self.close()
            raise

    def write(self, command):
        self.resource.write(command)
        if self.command_delay_s:
            time.sleep(self.command_delay_s)

    def query(self, command):
        # Explicit write/read also observes the MPM's delay before reading.
        self.write(command)
        return self.resource.read().strip()

    def identify(self):
        return self.query("*IDN?")

    def close(self):
        resource, self.resource = self.resource, None
        try:
            if resource is not None:
                resource.close()
        finally:
            if self._owns_manager:
                self._owns_manager = False
                self.manager.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
