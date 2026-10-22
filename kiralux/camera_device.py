"""The Kiralux CS505MUP1 as a single PyHardwareLibrary ``CameraDevice``.

``KiraluxCameraDevice`` does everything in one class: it owns the USB port,
drives the camera's command dialog through a PyHardwareLibrary
``CommandDictionary`` (``self.protocol`` + ``performTransaction``, framed by
:class:`~kiralux.device.KiraluxPort`), exposes eight features as capabilities,
and turns a captured frame into a :class:`~kiralux.frame.PolarFrame`. There is
no separate standalone driver underneath and no composition — the lifecycle
hooks (``doInitializeDevice`` / ``doCaptureFrame`` / ``doShutdownDevice``) carry
out the work themselves. The vocabulary lives in ``protocol.json``; the
:class:`Command` enum is kept as the vocabulary of record that
``validate_vocabulary`` checks against the camera's live ``discover`` list.

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

from enum import Enum
from typing import Optional

import numpy as np

from hardwarelibrary.cameras.camera import CameraDevice
from hardwarelibrary.communication.protocol import CommandDictionary

from .frame import PolarFrame, unpack_mosaic, HEADER_SIZE, BLOCK_SIZE
from .device import KiraluxPort, PROTOCOL_PATH
from .capabilities import (
    ExposureCapability,
    GainCapability,
    BlackLevelCapability,
    BinningCapability,
    RegionOfInterestCapability,
    FrameCountCapability,
    TemperatureCapability,
    PolarizationPhaseCapability,
)

# --------------------------------------------------------------------------- #
#  Protocol / transport constants
# --------------------------------------------------------------------------- #
VID, PID = 0x1313, 0x4001
EP_COMMAND, EP_RESPONSE, EP_IMAGE = 0x02, 0x82, 0x83
COMMAND_SIZE = 1024


def drain_image_endpoint(port, endPoint, timeout: int = 100, limit: int = 256):
    """Discard what is left on the image endpoint after an abrupt stop.

    A process killed in the middle of a capture leaves part of the frame in the
    camera's pipe, and every following capture then starts with that leftover and
    comes out shifted and striped. Reading until the endpoint times out clears it.
    """
    for _ in range(limit):
        try:
            port.readStream(BLOCK_SIZE, endPoint=endPoint, timeout=timeout)
        except Exception:
            return


class KiraluxError(RuntimeError):
    """A camera command returned an error, or the device is unavailable."""


class Command(str, Enum):
    """The camera's command vocabulary, mirroring what ``discover`` reports.

    The protocol dialog goes through the ``CommandDictionary`` in
    ``protocol.json``; this enum is the vocabulary of record that
    :meth:`KiraluxCameraDevice.validate_vocabulary` checks against the live
    ``discover`` list to catch firmware drift.
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
#  The single, self-contained driver
# --------------------------------------------------------------------------- #
class KiraluxCameraDevice(CameraDevice,
                          ExposureCapability,
                          GainCapability,
                          BlackLevelCapability,
                          BinningCapability,
                          RegionOfInterestCapability,
                          FrameCountCapability,
                          TemperatureCapability,
                          PolarizationPhaseCapability):
    """ThorLabs Kiralux CS505MUP1 as one PyHardwareLibrary CameraDevice.

    All USB and protocol work is done by this class directly. From
    PyHardwareLibrary it gets the connection lifecycle + state machine,
    notifications, the threaded capture loop (``start``/``stop``/``captureFrames``)
    and capability introspection (``capabilities()``/``hasCapability()``): exposure,
    gain, black level, binning, region of interest, frame count, temperature and
    polarization phase are each exposed as a capability.
    """

    classIdVendor = VID
    classIdProduct = PID

    def __init__(self, serialNumber: Optional[str] = None, port=None):
        super().__init__(serialNumber, self.classIdProduct, self.classIdVendor)
        self.serial: Optional[str] = None
        self.imageEndPoint = None
        self.port = port   # None -> real KiraluxPort; inject a ProtocolDebugPort to mock

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
        if self.port is None:
            wanted = None if self.serialNumber in (".*", None) else self.serialNumber
            self.port = KiraluxPort(serialNumber=wanted)
            self.port.open()
            self.imageEndPoint = self.port.endPointForAddress(EP_IMAGE)
        if self.protocol is None:
            self.protocol = CommandDictionary.fromFile(PROTOCOL_PATH)
        self.performTransaction("STOP")
        drain_image_endpoint(self.port, self.imageEndPoint)
        self.serial = self.performTransaction("SERNUM")["serial"]
        self.version = self.performTransaction("MODEL")["model"]
        self.validate_vocabulary()

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
    def validate_vocabulary(self):
        """Warn if the camera's live ``discover`` list differs from :class:`Command`.

        The protocol dialog itself goes through the :class:`CommandDictionary`
        (``performTransaction``); this keeps the :class:`Command` enum as the
        vocabulary of record and surfaces firmware drift (a command we name that
        the camera no longer has, or one it gained that we don't know) without
        blocking use.
        """
        import warnings
        reported = set(self.performTransaction("DISCOVER")["vocabulary"].split())
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
        return (self.performTransaction("IMAGE_WIDTH")["width"],
                self.performTransaction("IMAGE_HEIGHT")["height"])

    @property
    def bit_depth(self) -> int:
        return self.performTransaction("PIXEL_BIT_DEPTH")["depth"]

    @property
    def temperature(self) -> float:
        return self.performTransaction("TEMPERATURE")["temperature"]

    # -- settings (direct properties, via the CommandDictionary) ------------ #
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

    @property
    def black_level(self) -> int:
        return self.performTransaction("BLKLVL_GET")["blacklevel"]

    @black_level.setter
    def black_level(self, value: int):
        self.performTransaction("BLKLVL_SET", blacklevel=int(value))

    @property
    def frame_count(self) -> int:
        return self.performTransaction("NFRAMES_GET")["nframes"]

    @frame_count.setter
    def frame_count(self, value: int):
        self.performTransaction("NFRAMES_SET", nframes=int(value))

    @property
    def polar_phase(self) -> int:
        return self.performTransaction("POLAR_PHASE")["phase"]

    # -- capability hooks (notified + validated, via the mixins) ------------ #
    def doGetExposure(self) -> int:
        return self.exposure_us

    def doSetExposure(self, microseconds: int):
        self.exposure_us = microseconds

    def doGetGain(self) -> int:
        return self.gain_db

    def doSetGain(self, value: int):
        self.gain_db = value

    def doGetBlackLevel(self) -> int:
        return self.black_level

    def doSetBlackLevel(self, value: int):
        self.black_level = value

    def doGetBinning(self) -> tuple:
        return self.binning

    def doSetBinning(self, binning: tuple):
        self.binning = binning

    def doGetRegionOfInterest(self) -> tuple:
        return self.roi

    def doSetRegionOfInterest(self, box: tuple):
        self.roi = box

    def doGetFrameCount(self) -> int:
        return self.frame_count

    def doSetFrameCount(self, value: int):
        self.frame_count = value

    def doGetTemperature(self) -> float:
        return self.temperature

    def doGetPolarizationPhase(self) -> int:
        return self.polar_phase

    # -- acquisition -------------------------------------------------------- #
    def doCaptureFrame(self) -> PolarFrame:
        """Acquire one software-triggered frame as a :class:`PolarFrame`.

        The CameraDevice capture loop (``captureFrames``/``start``) calls this.
        """
        self.performTransaction("STOP")
        self.performTransaction("HWTRIG_SET", mode="none")
        self.performTransaction("NFRAMES_SET", nframes=1)
        width, height = self.sensor_size
        self.performTransaction("ARM")
        self.performTransaction("START")
        raw = self.port.readStream(HEADER_SIZE + width * height * 3 // 2,
                                   endPoint=self.imageEndPoint, timeout=3000)
        self.performTransaction("STOP")
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
        print("available:", KiraluxCameraDevice.available())
        cam.setExposure(20_000)
        cam.setGain(0)
        cam.setBlackLevel(5)
        cam.setBinning((1, 1))
        cam.setRegionOfInterest((0, 0, 2447, 2047))
        cam.setFrameCount(1)
        print("exposure   :", cam.getExposure(), "us")
        print("gain       :", cam.getGain(), "dB/10")
        print("black level:", cam.getBlackLevel(), "ADU")
        print("binning    :", cam.getBinning())
        print("roi        :", cam.getRegionOfInterest())
        print("frame count:", cam.getFrameCount())
        print("temperature:", cam.getTemperature(), "C")
        print("polar phase:", cam.getPolarizationPhase(), "deg")
        frame = cam.snap()
        m = np.asarray(frame).astype(int)
        print("frame", repr(frame), "vmed", float(np.median(np.abs(m[1:] - m[:-1]))),
              "dolp %.3f" % float(frame.dolp.mean()))
