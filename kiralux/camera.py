"""The lightweight, standalone ``Kiralux`` driver (no PyHardwareLibrary device).

``Kiralux`` is the simplest way to drive the camera from a script: open, set a
few properties, ``snap()`` a :class:`~kiralux.frame.PolarFrame`, close. It is not
a ``PhysicalDevice`` — it has no state machine, notifications or capability
introspection. For those, use :class:`~kiralux.camera_device.KiraluxCameraDevice`,
which does the same USB/protocol work as a single PyHardwareLibrary CameraDevice.

Both reuse one command vocabulary (:class:`Command`) and one frame decoder, so
this class only adds the thin open/property/snap convenience on top.

    from kiralux import Kiralux
    with Kiralux() as cam:
        cam.exposure_us = 20_000
        frame = cam.snap()
        dolp = frame.dolp
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from hardwarelibrary.communication.usbport import USBPort

from .frame import PolarFrame, unpack_mosaic, HEADER_SIZE
from .camera_device import (
    drain_image_endpoint,
    Command,
    KiraluxError,
    VID,
    PID,
    EP_COMMAND,
    EP_RESPONSE,
    EP_IMAGE,
    COMMAND_SIZE,
)


class Kiralux:
    """A ThorLabs Kiralux CS505MUP1, driven through PyHardwareLibrary's USBPort."""

    def __init__(self, serial: Optional[str] = None):
        self.port = USBPort(idVendor=VID, idProduct=PID, serialNumber=serial, interfaceNumber=0)
        self.port.open()
        self.port.defaultTimeout = 3000
        self.commandEndPoint = self.port.endPointForAddress(EP_COMMAND)
        self.responseEndPoint = self.port.endPointForAddress(EP_RESPONSE)
        self.imageEndPoint = self.port.endPointForAddress(EP_IMAGE)
        self.command(Command.STOP)
        drain_image_endpoint(self.port, self.imageEndPoint)
        self.serial = self.command(Command.SERNUM)
        self.model = self.command(Command.MODEL)
        self.validate_vocabulary()

    @staticmethod
    def available() -> list[str]:
        import usb.core
        out = []
        for d in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
            try:
                out.append(d.serial_number.strip("\x00 "))
            except Exception:
                out.append(None)
        return out

    def close(self):
        self.port.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f"<Kiralux {self.model} sn={self.serial}>"

    # -- protocol ----------------------------------------------------------- #
    def command(self, name, *args) -> str:
        """Send a command (a :class:`Command` or plain string) with optional
        arguments, and return the camera's text response.

        Raises :class:`KiraluxError` on an ``error ...`` reply. With no argument
        most commands report their current value (``command(Command.EXP)``).
        """
        text = name.value if isinstance(name, Command) else str(name)
        if args:
            text = text + " " + " ".join(str(a) for a in args)
        self.port.writeData((text.encode() + b"\x00").ljust(COMMAND_SIZE, b"\x00"),
                            endPoint=self.commandEndPoint)
        reply = bytes(self.port.readData(COMMAND_SIZE, endPoint=self.responseEndPoint))
        reply = reply.split(b"\x00")[0].decode("latin1").strip()
        if reply.startswith("error"):
            raise KiraluxError(f"{text!r} -> {reply}")
        return reply

    def describe(self, command) -> str:
        """Return the camera's self-documentation (JSON) for a command."""
        name = command.value if isinstance(command, Command) else str(command)
        return self.command(name + ".disc")

    def validate_vocabulary(self):
        """Warn if the camera's live ``discover`` list differs from :class:`Command`.

        Surfaces firmware drift (a command we name that the camera no longer has,
        or one the camera gained that we don't know) without blocking use.
        """
        import warnings
        reported = set(self.command(Command.DISCOVER).split())
        known = {c.value for c in Command}
        unknown, missing = reported - known, known - reported
        if unknown or missing:
            warnings.warn(
                f"Kiralux command-set drift vs firmware: unknown to driver="
                f"{sorted(unknown)}, not reported by camera={sorted(missing)}",
                stacklevel=2)

    # -- identity ----------------------------------------------------------- #
    @property
    def sensor_size(self) -> tuple[int, int]:
        return int(self.command(Command.IMAGE_WIDTH)), int(self.command(Command.IMAGE_HEIGHT))

    @property
    def bit_depth(self) -> int:
        return int(self.command(Command.PIXEL_BIT_DEPTH))

    @property
    def temperature(self) -> float:
        return float(self.command(Command.TEMPERATURE))

    # -- settings ----------------------------------------------------------- #
    @property
    def exposure_us(self) -> int:
        return int(self.command(Command.EXP))

    @exposure_us.setter
    def exposure_us(self, microseconds: int):
        self.command(Command.EXP, int(microseconds))

    @property
    def gain_db(self) -> int:
        return int(self.command(Command.GAIN))

    @gain_db.setter
    def gain_db(self, value: int):
        self.command(Command.GAIN, int(value))

    @property
    def roi(self) -> tuple[int, int, int, int]:
        return tuple(int(x) for x in self.command(Command.ROI).split())

    @roi.setter
    def roi(self, box: tuple[int, int, int, int]):
        self.command(Command.ROI, *box)

    @property
    def binning(self) -> tuple[int, int]:
        return int(self.command(Command.HBIN)), int(self.command(Command.VBIN))

    @binning.setter
    def binning(self, hv: tuple[int, int]):
        h, v = hv
        self.command(Command.HBIN, int(h))
        self.command(Command.VBIN, int(v))

    def reset_roi(self):
        self.command(Command.STOP)
        self.command(Command.HBIN, 1)
        self.command(Command.VBIN, 1)
        self.command(Command.ROI, 0, 0, 2447, 2047)

    # -- acquisition -------------------------------------------------------- #
    def snap(self, exposure_us: Optional[int] = None, *, timeout: float = 3.0) -> PolarFrame:
        """Acquire one software-triggered frame and return it as a PolarFrame."""
        if exposure_us is not None:
            self.exposure_us = exposure_us
        self.command(Command.STOP)
        self.command(Command.HWTRIG, "none")
        self.command(Command.NFRAMES, 1)
        width, height = self.sensor_size
        self.command(Command.ARM)
        self.command(Command.START)
        raw = self.port.readStream(HEADER_SIZE + width * height * 3 // 2,
                                   endPoint=self.imageEndPoint, timeout=int(timeout * 1000))
        self.command(Command.STOP)
        return PolarFrame(unpack_mosaic(bytes(raw), width, height))


if __name__ == "__main__":
    with Kiralux() as cam:
        print(cam, "| T =", cam.temperature, "C | available:", Kiralux.available())
        cam.exposure_us = 20_000
        frame = cam.snap()
        m = np.asarray(frame).astype(int)
        print("frame", repr(frame), "vmed", float(np.median(np.abs(m[1:] - m[:-1]))),
              "dolp %.3f" % float(frame.dolp.mean()))
