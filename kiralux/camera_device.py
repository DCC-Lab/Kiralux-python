"""The Kiralux CS505MUP1 as a single PyHardwareLibrary ``CameraDevice``.

``KiraluxCameraDevice`` does everything in one class: it owns the USB port,
speaks the camera's ASCII command protocol directly, exposes exposure and gain
as PyHardwareLibrary capabilities, and turns a captured frame into a
:class:`~kiralux.frame.PolarFrame`. There is no separate standalone driver
underneath and no composition — the lifecycle hooks (``doInitializeDevice`` /
``doCaptureFrame`` / ``doShutdownDevice``) carry out the USB work themselves.

    from kiralux import KiraluxCameraDevice

    with KiraluxCameraDevice() as cam:       # initialize -> Ready, shutdown on exit
        cam.exposure_us = 20_000             # Pythonic properties (direct protocol)
        cam.setExposure(20_000)              # or the notified, validated capability
        frame = cam.snap()                   # -> PolarFrame; .s0 / .dolp / .aolp
        for f in cam.captureFrames(10):      # inherited capture loop
            ...

Requires ``hardwarelibrary>=2.2.0`` (for ``USBPort.readStream`` and the camera
capability base classes).
"""
from __future__ import annotations

from abc import abstractmethod
from enum import Enum
from typing import Optional

import numpy as np

from hardwarelibrary.capabilities import Capability, notifies
from hardwarelibrary.cameras.camera import CameraDevice
from hardwarelibrary.validation import requireWithinRange
from hardwarelibrary.communication.usbport import USBPort

from .frame import PolarFrame, unpack_mosaic, HEADER_SIZE

# --------------------------------------------------------------------------- #
#  Protocol / transport constants
# --------------------------------------------------------------------------- #
VID, PID = 0x1313, 0x4001
EP_COMMAND, EP_RESPONSE, EP_IMAGE = 0x02, 0x82, 0x83
COMMAND_SIZE = 1024


class KiraluxError(RuntimeError):
    """A camera command returned an error, or the device is unavailable."""


class Command(str, Enum):
    """The camera's command vocabulary, mirroring what ``discover`` reports.

    Members are ``str`` so they can be used directly;
    :meth:`KiraluxCameraDevice.command` also accepts a plain string.
    """
    # protocol / meta
    DISCOVER = "discover"; ERROR = "error"; ECHO = "echo"; PING = "ping"
    ID = "id"; INFO = "info"; VER = "ver"; MODEL = "model"; NAME = "name"
    SERNUM = "sernum"; UNLOCK = "unlock"; STATE = "state"; TAGS = "tags"
    NVSTOR = "nvstor"; CAMERA_RADIX = "camera_radix"; DEBUG_RADIX = "debug_radix"
    # acquisition
    STOP = "stop"; START = "start"; ARM = "arm"; DISARM = "disarm"
    HWTRIG = "hwtrig"; NFRAMES = "nframes"; SFR = "sfr"; GPO = "gpo"
    # exposure / gain / level
    EXP = "exp"; GAIN = "gain"; BLKLVL = "blklvl"
    # geometry
    ROI = "roi"; HBIN = "hbin"; VBIN = "vbin"; VFLIP = "vflip"; HFLIP = "hflip"
    IMAGE_DIMS = "image_dims"; IMAGE_WIDTH = "image_width"; IMAGE_HEIGHT = "image_height"
    # pixel / sensor
    PIXEL_BIT_DEPTH = "pixel_bit_depth"; PIXEL_SIZE = "pixel_size"
    PIXEL_WIDTH_NM = "pixel_width_nm"; PIXEL_HEIGHT_NM = "pixel_height_nm"
    PIXEL_BYTE_ORDERING = "pixel_byte_ordering"; PIXEL_CLOCK_COUNT_BASE = "pixel_clock_count_base"
    SENSOR_READOUT_TIME = "sensor_readout_time"; FRAMETIME = "frametime"; TIME = "time"
    IMGPACK = "imgpack"; HOT_PIXEL_CORRECTION = "hot_pixel_correction"
    STATUSLED = "statusled"; TEMPERATURE = "temperature"
    # polarization
    POLAR_PHASE = "polar_phase"
    # color (not applicable on the mono polarization model, but reported)
    COLOR = "color"; COLOR_FILTER_PHASE = "color_filter_phase"; IR_FILTER_TYPE = "ir_filter_type"
    COLOR_CORRECTION_MATRIX = "color_correction_matrix"; OUTPUT_COLOR_SPACE = "output_color_space"
    DEFAULT_WHITE_BALANCE_MATRIX = "default_white_balance_matrix"


# --------------------------------------------------------------------------- #
#  Camera capabilities (same shape as the library's OnOffCapability / PowerCapability)
# --------------------------------------------------------------------------- #
class ExposureNotification(Enum):
    willSetExposure = "willSetExposure"
    didSetExposure = "didSetExposure"
    didGetExposure = "didGetExposure"


class ExposureCapability(Capability):
    """A device whose integration time can be read and set, in microseconds."""

    unit = "us"
    notification = ExposureNotification

    @notifies(did=ExposureNotification.didGetExposure)
    def getExposure(self) -> int:
        return self.doGetExposure()

    @notifies(will=ExposureNotification.willSetExposure, did=ExposureNotification.didSetExposure)
    def setExposure(self, microseconds: int):
        self.doSetExposure(microseconds)

    @abstractmethod
    def doGetExposure(self) -> int: ...

    @abstractmethod
    def doSetExposure(self, microseconds: int): ...


class GainNotification(Enum):
    willSetGain = "willSetGain"
    didSetGain = "didSetGain"
    didGetGain = "didGetGain"


def validateGain(self, value: int):
    requireWithinRange(value, (0, 480), "gain")


class GainCapability(Capability):
    """A device with a settable gain (0..480, in tenths of a dB)."""

    unit = "dB"
    notification = GainNotification

    @notifies(did=GainNotification.didGetGain)
    def getGain(self) -> int:
        return self.doGetGain()

    @notifies(will=GainNotification.willSetGain, did=GainNotification.didSetGain, validate=validateGain)
    def setGain(self, value: int):
        self.doSetGain(value)

    @abstractmethod
    def doGetGain(self) -> int: ...

    @abstractmethod
    def doSetGain(self, value: int): ...


# --------------------------------------------------------------------------- #
#  The single, self-contained driver
# --------------------------------------------------------------------------- #
class KiraluxCameraDevice(CameraDevice, ExposureCapability, GainCapability):
    """ThorLabs Kiralux CS505MUP1 as one PyHardwareLibrary CameraDevice.

    All USB and protocol work is done by this class directly. From
    PyHardwareLibrary it gets the connection lifecycle + state machine,
    notifications, the threaded capture loop (``start``/``stop``/``captureFrames``)
    and capability introspection (``capabilities()``/``hasCapability()``).
    """

    classIdVendor = VID
    classIdProduct = PID

    def __init__(self, serialNumber: Optional[str] = None):
        super().__init__(serialNumber, self.classIdProduct, self.classIdVendor)
        self.serial: Optional[str] = None
        self.commandEndPoint = None
        self.responseEndPoint = None
        self.imageEndPoint = None

    @staticmethod
    def available() -> list[str]:
        """Serial numbers of every connected Kiralux."""
        import usb.core
        out = []
        for d in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
            try:
                out.append(d.serial_number.strip("\x00 "))
            except Exception:
                out.append(None)
        return out

    # -- lifecycle hooks ---------------------------------------------------- #
    def doInitializeDevice(self):
        wanted = None if self.serialNumber in (".*", None) else self.serialNumber
        self.port = USBPort(idVendor=VID, idProduct=PID, serialNumber=wanted, interfaceNumber=0)
        self.port.open()
        self.port.defaultTimeout = 3000
        self.commandEndPoint = self.port.endPointForAddress(EP_COMMAND)
        self.responseEndPoint = self.port.endPointForAddress(EP_RESPONSE)
        self.imageEndPoint = self.port.endPointForAddress(EP_IMAGE)
        self.command(Command.STOP)
        self.serial = self.command(Command.SERNUM)
        self.version = self.command(Command.MODEL)

    def doShutdownDevice(self):
        super().doShutdownDevice()           # stop the capture loop if running
        if self.port is not None:
            self.port.close()
            self.port = None

    def __enter__(self):
        self.initializeDevice()
        return self

    def __exit__(self, *exc):
        self.shutdownDevice()

    def __repr__(self):
        return f"<KiraluxCameraDevice {self.version} sn={self.serial}>"

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

    # -- settings (direct properties) --------------------------------------- #
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

    # -- capability hooks (notified + validated, via the mixins) ------------ #
    def doGetExposure(self) -> int:
        return self.exposure_us

    def doSetExposure(self, microseconds: int):
        self.exposure_us = microseconds

    def doGetGain(self) -> int:
        return self.gain_db

    def doSetGain(self, value: int):
        self.gain_db = value

    # -- acquisition -------------------------------------------------------- #
    def doCaptureFrame(self) -> PolarFrame:
        """Acquire one software-triggered frame as a :class:`PolarFrame`.

        The CameraDevice capture loop (``captureFrames``/``start``) calls this.
        """
        self.command(Command.STOP)
        self.command(Command.HWTRIG, "none")
        self.command(Command.NFRAMES, 1)
        width, height = self.sensor_size
        self.command(Command.ARM)
        self.command(Command.START)
        raw = self.port.readStream(HEADER_SIZE + width * height * 3 // 2,
                                   endPoint=self.imageEndPoint, timeout=3000)
        self.command(Command.STOP)
        return PolarFrame(unpack_mosaic(bytes(raw), width, height))

    def snap(self, exposure_us: Optional[int] = None) -> PolarFrame:
        """Convenience: optionally set the exposure, then capture one frame."""
        if exposure_us is not None:
            self.exposure_us = exposure_us
        return self.doCaptureFrame()


if __name__ == "__main__":
    with KiraluxCameraDevice() as cam:
        print(repr(cam), "| state:", cam.state.name)
        print("capabilities:", [c.__name__ for c in cam.capabilities()])
        print("T =", cam.temperature, "C | available:", KiraluxCameraDevice.available())
        cam.setExposure(20_000)
        print("getExposure:", cam.getExposure(), cam.unit)
        frame = cam.snap()
        m = np.asarray(frame).astype(int)
        print("frame", repr(frame), "vmed", float(np.median(np.abs(m[1:] - m[:-1]))),
              "dolp %.3f" % float(frame.dolp.mean()))
