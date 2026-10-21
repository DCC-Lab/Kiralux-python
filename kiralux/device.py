"""Kiralux command dialog driven by a PyHardwareLibrary ``CommandDictionary``.

This is a *protocol-described* variant of the driver. Instead of a hand-written
``command()`` method, the camera's command vocabulary lives entirely in
``protocol.json`` — one entry per command, each giving the request it
sends and the reply it expects. ``PhysicalDevice.performTransaction(name, **args)``
then carries out any exchange by name and hands back a dict.

The one thing a text description cannot express is the camera's framing: every
command travels as a 1024-byte, null-padded buffer on EP 0x02, and every reply
is a 1024-byte buffer on EP 0x82 read back and trimmed at the first null. That is
a uniform transport detail, so it lives in ``KiraluxPort`` — a thin ``USBPort``
subclass — and the dictionary stays pure text. The image itself (EP 0x83, 12-bit
packed) is *not* a text command and stays with ``Kiralux.snap`` in ``kiralux.py``.

The payoff is a mock for free: hand the same dictionary to
``ProtocolDebugPort`` and it answers every command with no camera attached, so the
driver logic can be exercised on any machine. See ``test_command_dictionary.py``.

    from kiralux import KiraluxDevice
    with KiraluxDevice() as cam:                 # real camera on USB
        cam.exposure_us = 20_000
        print(cam.serial, cam.model, cam.sensor_size)
"""
from __future__ import annotations

import os
from typing import Optional

from hardwarelibrary.physicaldevice import PhysicalDevice
from hardwarelibrary.communication.usbport import USBPort
from hardwarelibrary.communication.protocol import CommandDictionary

VID, PID = 0x1313, 0x4001
EP_COMMAND, EP_RESPONSE, EP_IMAGE = 0x02, 0x82, 0x83
COMMAND_SIZE = 1024

PROTOCOL_PATH = os.path.join(os.path.dirname(__file__), "protocol.json")


class KiraluxPort(USBPort):
    """A ``USBPort`` that speaks the Kiralux command framing.

    Every command is written as a 1024-byte, null-terminated buffer on the
    command endpoint (0x02); every reply is a 1024-byte buffer on the response
    endpoint (0x82), returned as the text up to its first null. The
    ``CommandDictionary`` above this never sees the padding — framing is a
    transport concern and belongs here, not in the protocol description.
    """

    def __init__(self, serialNumber: Optional[str] = None):
        super().__init__(idVendor=VID, idProduct=PID, serialNumber=serialNumber,
                         interfaceNumber=0)

    def open(self):
        super().open()
        self.defaultTimeout = 3000
        self.commandEndPoint = self.endPointForAddress(EP_COMMAND)
        self.responseEndPoint = self.endPointForAddress(EP_RESPONSE)

    def writeData(self, data, endPoint=None):
        if isinstance(data, str):
            data = data.encode("latin1")
        buffer = (bytes(data) + b"\x00").ljust(COMMAND_SIZE, b"\x00")
        return super().writeData(buffer, endPoint or self.commandEndPoint)

    def readString(self, endPoint=None):
        raw = bytes(super().readData(COMMAND_SIZE, endPoint or self.responseEndPoint))
        return raw.split(b"\x00")[0].decode("latin1")


class KiraluxDevice(PhysicalDevice):
    """The Kiralux, driven entirely from its protocol description.

    Pass ``port`` to inject a transport — leave it ``None`` for the real camera
    (a :class:`KiraluxPort`), or hand in a ``ProtocolDebugPort(cam.protocol)`` to
    exercise the exact same commands with no hardware attached.
    """

    classIdVendor = VID
    classIdProduct = PID

    def __init__(self, serialNumber: str = ".*", port=None):
        super().__init__(serialNumber, PID, VID)
        self.protocol = CommandDictionary.fromFile(PROTOCOL_PATH)
        self.port = port

    # -- lifecycle ---------------------------------------------------------- #
    def doInitializeDevice(self):
        if self.port is None:
            serial = None if self.serialNumber in (".*", None) else self.serialNumber
            self.port = KiraluxPort(serialNumber=serial)
            self.port.open()
        self.performTransaction("STOP")

    def doShutdownDevice(self):
        if isinstance(self.port, KiraluxPort):
            self.port.close()

    def open(self):
        self.doInitializeDevice()
        return self

    def close(self):
        self.doShutdownDevice()

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return "<KiraluxDevice {0} sn={1}>".format(self.model, self.serial)

    # -- identity ----------------------------------------------------------- #
    @property
    def serial(self) -> int:
        return self.performTransaction("SERNUM")["serial"]

    @property
    def model(self) -> str:
        return self.performTransaction("MODEL")["model"]

    @property
    def sensor_size(self) -> tuple[int, int]:
        return (self.performTransaction("IMAGE_WIDTH")["width"],
                self.performTransaction("IMAGE_HEIGHT")["height"])

    @property
    def bit_depth(self) -> int:
        return self.performTransaction("PIXEL_BIT_DEPTH")["depth"]

    @property
    def temperature(self) -> float:
        return self.performTransaction("TEMPERATURE")["temperature"]

    # -- settings ----------------------------------------------------------- #
    @property
    def exposure_us(self) -> int:
        return self.performTransaction("EXP_GET")["exposure"]

    @exposure_us.setter
    def exposure_us(self, microseconds: int):
        self.performTransaction("EXP_SET", exposure=int(microseconds))

    @property
    def gain_db(self) -> int:
        return self.performTransaction("GAIN_GET")["gain"]

    @gain_db.setter
    def gain_db(self, value: int):
        self.performTransaction("GAIN_SET", gain=int(value))

    @property
    def roi(self) -> tuple[int, int, int, int]:
        r = self.performTransaction("ROI_GET")
        return (r["left"], r["top"], r["right"], r["bottom"])

    @roi.setter
    def roi(self, box: tuple[int, int, int, int]):
        left, top, right, bottom = box
        self.performTransaction("ROI_SET", left=left, top=top, right=right, bottom=bottom)

    @property
    def binning(self) -> tuple[int, int]:
        return (self.performTransaction("HBIN_GET")["hbin"],
                self.performTransaction("VBIN_GET")["vbin"])

    @binning.setter
    def binning(self, hv: tuple[int, int]):
        h, v = hv
        self.performTransaction("HBIN_SET", hbin=int(h))
        self.performTransaction("VBIN_SET", vbin=int(v))

    # -- acquisition -------------------------------------------------------- #
    def prepare_capture(self, nframes: int = 1, trigger: str = "none"):
        """Run the command half of an acquisition: stop, trigger mode, count, arm."""
        self.performTransaction("STOP")
        self.performTransaction("HWTRIG_SET", mode=trigger)
        self.performTransaction("NFRAMES_SET", nframes=nframes)
        self.performTransaction("ARM")

    def snap(self, exposure_us: Optional[int] = None, *, timeout: float = 3.0):
        """Acquire one software-triggered frame as a ``PolarFrame``.

        The command dialog (stop/trigger/count/arm/start) is entirely
        protocol-described; only the image bytes — binary, not a text command —
        are read off EP 0x83 with ``readStream`` and demosaiced by ``kiralux``.
        """
        from .frame import unpack_mosaic, PolarFrame, HEADER_SIZE

        if exposure_us is not None:
            self.exposure_us = exposure_us
        width, height = self.sensor_size
        self.prepare_capture(nframes=1, trigger="none")
        self.performTransaction("START")
        raw = self.port.readStream(HEADER_SIZE + width * height * 3 // 2,
                                   endPoint=self.port.endPointForAddress(EP_IMAGE),
                                   timeout=int(timeout * 1000))
        self.performTransaction("STOP")
        return PolarFrame(unpack_mosaic(bytes(raw), width, height))


if __name__ == "__main__":
    with KiraluxDevice() as cam:
        print(repr(cam))
        print("serial     ", cam.serial)
        print("model      ", cam.model)
        print("sensor_size", cam.sensor_size)
        print("bit_depth  ", cam.bit_depth)
        print("temperature", cam.temperature, "C")
        cam.exposure_us = 20_000
        print("exposure_us", cam.exposure_us)
        cam.gain_db = 0
        print("gain_db    ", cam.gain_db)
        print("roi        ", cam.roi)
        print("binning    ", cam.binning)

        import numpy as np
        frame = cam.snap()
        m = np.asarray(frame).astype(int)
        vmed = float(np.median(np.abs(m[1:] - m[:-1])))
        print("frame      ", repr(frame), "vmed", vmed, "max", int(m.max()),
              "dolp %.3f" % float(frame.dolp.mean()))
