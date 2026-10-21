"""PyHardwareLibrary capabilities exposed by the Kiralux CS505MUP1.

Each capability is a mixin in the library's own style: a ``<Name>Notification``
enum, public methods bracketed by ``@notifies`` that delegate to abstract
``do*`` hooks, and (where a value is bounded) a module-level validator wired
through ``@notifies(validate=...)``. A driver — here
:class:`~kiralux.camera_device.KiraluxCameraDevice` — mixes these alongside a
``PhysicalDevice`` and implements the hooks.

Ranges come from the camera's own self-documentation (``<cmd>.disc``):

* exposure   — microseconds
* gain       — 0..480 (tenths of a dB)
* black level — 0..4095 (ADU)
* binning    — 1..16 per axis
* ROI        — left 0..2188, top 0..2044, right 259..2447, bottom 3..2047
* frame count — 0..4294967280 (0 = continuous)
* temperature — read-only, deg C
* polarization phase — read-only, one of {0, 45, 90, 135} degrees
"""
from __future__ import annotations

from abc import abstractmethod
from enum import Enum

from hardwarelibrary.capabilities import Capability, notifies
from hardwarelibrary.validation import requireWithinRange


# --------------------------------------------------------------------------- #
#  Exposure
# --------------------------------------------------------------------------- #
class ExposureNotification(Enum):
    willSetExposure = "willSetExposure"
    didSetExposure = "didSetExposure"
    didGetExposure = "didGetExposure"


class ExposureCapability(Capability):
    """A device whose integration time can be read and set, in microseconds."""

    unit = "us"
    isReadable = True
    isWritable = True
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


# --------------------------------------------------------------------------- #
#  Gain
# --------------------------------------------------------------------------- #
class GainNotification(Enum):
    willSetGain = "willSetGain"
    didSetGain = "didSetGain"
    didGetGain = "didGetGain"


def validateGain(self, value: int):
    requireWithinRange(value, (0, 480), "gain", "dB/10")


class GainCapability(Capability):
    """A device with a settable gain (0..480, in tenths of a dB)."""

    unit = "dB"
    isReadable = True
    isWritable = True
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
#  Black level
# --------------------------------------------------------------------------- #
class BlackLevelNotification(Enum):
    willSetBlackLevel = "willSetBlackLevel"
    didSetBlackLevel = "didSetBlackLevel"
    didGetBlackLevel = "didGetBlackLevel"


def validateBlackLevel(self, value: int):
    requireWithinRange(value, (0, 4095), "black level", "ADU")


class BlackLevelCapability(Capability):
    """A device with a settable black-level offset (0..4095 ADU)."""

    unit = "ADU"
    isReadable = True
    isWritable = True
    notification = BlackLevelNotification

    @notifies(did=BlackLevelNotification.didGetBlackLevel)
    def getBlackLevel(self) -> int:
        return self.doGetBlackLevel()

    @notifies(will=BlackLevelNotification.willSetBlackLevel, did=BlackLevelNotification.didSetBlackLevel,
              validate=validateBlackLevel)
    def setBlackLevel(self, value: int):
        self.doSetBlackLevel(value)

    @abstractmethod
    def doGetBlackLevel(self) -> int: ...

    @abstractmethod
    def doSetBlackLevel(self, value: int): ...


# --------------------------------------------------------------------------- #
#  Binning
# --------------------------------------------------------------------------- #
class BinningNotification(Enum):
    willSetBinning = "willSetBinning"
    didSetBinning = "didSetBinning"
    didGetBinning = "didGetBinning"


def validateBinning(self, binning):
    horizontal, vertical = binning
    requireWithinRange(horizontal, (1, 16), "horizontal binning")
    requireWithinRange(vertical, (1, 16), "vertical binning")


class BinningCapability(Capability):
    """A device with settable horizontal/vertical pixel binning (1..16 each)."""

    isReadable = True
    isWritable = True
    notification = BinningNotification

    @notifies(did=BinningNotification.didGetBinning)
    def getBinning(self) -> tuple:
        return self.doGetBinning()

    @notifies(will=BinningNotification.willSetBinning, did=BinningNotification.didSetBinning,
              validate=validateBinning)
    def setBinning(self, binning: tuple):
        self.doSetBinning(binning)

    @abstractmethod
    def doGetBinning(self) -> tuple: ...

    @abstractmethod
    def doSetBinning(self, binning: tuple): ...


# --------------------------------------------------------------------------- #
#  Region of interest
# --------------------------------------------------------------------------- #
class RegionOfInterestNotification(Enum):
    willSetRegionOfInterest = "willSetRegionOfInterest"
    didSetRegionOfInterest = "didSetRegionOfInterest"
    didGetRegionOfInterest = "didGetRegionOfInterest"


def validateRegionOfInterest(self, box):
    left, top, right, bottom = box
    requireWithinRange(left, (0, 2188), "roi left")
    requireWithinRange(top, (0, 2044), "roi top")
    requireWithinRange(right, (259, 2447), "roi right")
    requireWithinRange(bottom, (3, 2047), "roi bottom")
    if right <= left or bottom <= top:
        raise ValueError(f"empty ROI: {box!r} (need right>left and bottom>top)")


class RegionOfInterestCapability(Capability):
    """A device with a settable image region of interest (left, top, right, bottom)."""

    isReadable = True
    isWritable = True
    notification = RegionOfInterestNotification

    @notifies(did=RegionOfInterestNotification.didGetRegionOfInterest)
    def getRegionOfInterest(self) -> tuple:
        return self.doGetRegionOfInterest()

    @notifies(will=RegionOfInterestNotification.willSetRegionOfInterest,
              did=RegionOfInterestNotification.didSetRegionOfInterest,
              validate=validateRegionOfInterest)
    def setRegionOfInterest(self, box: tuple):
        self.doSetRegionOfInterest(box)

    @abstractmethod
    def doGetRegionOfInterest(self) -> tuple: ...

    @abstractmethod
    def doSetRegionOfInterest(self, box: tuple): ...


# --------------------------------------------------------------------------- #
#  Frame count
# --------------------------------------------------------------------------- #
class FrameCountNotification(Enum):
    willSetFrameCount = "willSetFrameCount"
    didSetFrameCount = "didSetFrameCount"
    didGetFrameCount = "didGetFrameCount"


def validateFrameCount(self, value: int):
    requireWithinRange(value, (0, 4294967280), "frame count")


class FrameCountCapability(Capability):
    """A device with a settable number of frames to acquire (0 = continuous)."""

    isReadable = True
    isWritable = True
    notification = FrameCountNotification

    @notifies(did=FrameCountNotification.didGetFrameCount)
    def getFrameCount(self) -> int:
        return self.doGetFrameCount()

    @notifies(will=FrameCountNotification.willSetFrameCount, did=FrameCountNotification.didSetFrameCount,
              validate=validateFrameCount)
    def setFrameCount(self, value: int):
        self.doSetFrameCount(value)

    @abstractmethod
    def doGetFrameCount(self) -> int: ...

    @abstractmethod
    def doSetFrameCount(self, value: int): ...


# --------------------------------------------------------------------------- #
#  Temperature (read-only)
# --------------------------------------------------------------------------- #
class TemperatureNotification(Enum):
    didGetTemperature = "didGetTemperature"


class TemperatureCapability(Capability):
    """A device that reports its sensor temperature, in degrees Celsius."""

    unit = "C"
    isReadable = True
    isWritable = False
    notification = TemperatureNotification

    @notifies(did=TemperatureNotification.didGetTemperature)
    def getTemperature(self) -> float:
        return self.doGetTemperature()

    @abstractmethod
    def doGetTemperature(self) -> float: ...


# --------------------------------------------------------------------------- #
#  Polarization phase (read-only)
# --------------------------------------------------------------------------- #
class PolarizationPhaseNotification(Enum):
    didGetPolarizationPhase = "didGetPolarizationPhase"


class PolarizationPhaseCapability(Capability):
    """A polarization camera that reports its fixed micro-polarizer phase offset.

    One of {0, 45, 90, 135} degrees — the orientation of the top-left pixel of
    each 2x2 super-pixel on the sensor's polarizer mosaic.
    """

    unit = "deg"
    isReadable = True
    isWritable = False
    notification = PolarizationPhaseNotification

    @notifies(did=PolarizationPhaseNotification.didGetPolarizationPhase)
    def getPolarizationPhase(self) -> int:
        return self.doGetPolarizationPhase()

    @abstractmethod
    def doGetPolarizationPhase(self) -> int: ...
