"""Kiralux as a PyHardwareLibrary device.

Adapts the standalone, dependency-free driver (``kiralux.Kiralux``) to the DCC-Lab
``hardwarelibrary`` ecosystem. ``KiraluxCamera`` subclasses ``CameraDevice`` (and
therefore ``PhysicalDevice``), inheriting the connection lifecycle + state machine,
notifications, the threaded capture loop (``start``/``stop``/``captureFrames``) and
capability introspection (``capabilities()``/``hasCapability()``). It mixes in two
camera capabilities written exactly like the library's own (``@notifies`` public
methods delegating to abstract ``do*`` hooks).

The USB/protocol logic is NOT reimplemented: ``KiraluxCamera`` *owns* a ``Kiralux``
and forwards to it. The standalone driver stays usable on its own, and nothing
Kiralux-specific lives inside hardwarelibrary.

    from kiralux import KiraluxCamera, ExposureCapability

    cam = KiraluxCamera()
    cam.initializeDevice()                 # open -> Ready (posts will/didInitialize)
    cam.setExposure(20_000)                # validated, notified, guarded by validateReady
    if cam.hasCapability(ExposureCapability):
        print(cam.capabilities())
    frame = cam.captureFrames(1)[0]        # -> PolarFrame; frame.dolp, frame.aolp, ...
    cam.shutdownDevice()

Requires the GitHub (master) hardwarelibrary:
    pip install "git+https://github.com/DCC-Lab/PyHardwareLibrary@master"
"""
from __future__ import annotations

from abc import abstractmethod
from enum import Enum

from hardwarelibrary.capabilities import Capability, notifies
from hardwarelibrary.cameras.camera import CameraDevice
from hardwarelibrary.validation import requireWithinRange

from .camera import Kiralux, PolarFrame


# --------------------------------------------------------------------------- #
#  Camera capabilities (same shape as OnOffCapability / PowerCapability)
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
#  The driver
# --------------------------------------------------------------------------- #
class KiraluxCamera(CameraDevice, ExposureCapability, GainCapability):
    """ThorLabs Kiralux CS505MUP1 as a hardwarelibrary CameraDevice.

    Implements only the ``do*`` hooks; all USB work is delegated to a composed
    :class:`kiralux.Kiralux`. ``doCaptureFrame`` returns a :class:`kiralux.PolarFrame`,
    so ``captureFrames``/``start`` yield frames carrying ``.s0``/``.dolp``/``.aolp``.
    """

    classIdVendor = 0x1313
    classIdProduct = 0x4001

    def __init__(self, serialNumber: str = None):
        super().__init__(serialNumber, self.classIdProduct, self.classIdVendor)
        self.link: Kiralux | None = None

    # -- lifecycle hooks ---------------------------------------------------- #
    def doInitializeDevice(self):
        wanted = None if self.serialNumber in (".*", None) else self.serialNumber
        self.link = Kiralux(serial=wanted)
        self.version = self.link.model

    def doShutdownDevice(self):
        super().doShutdownDevice()           # stop the capture loop if running
        if self.link is not None:
            self.link.close()
            self.link = None

    # -- camera hook -------------------------------------------------------- #
    def doCaptureFrame(self) -> PolarFrame:
        return self.link.snap()

    # -- capability hooks --------------------------------------------------- #
    def doGetExposure(self) -> int:
        return self.link.exposure_us

    def doSetExposure(self, microseconds: int):
        self.link.exposure_us = microseconds

    def doGetGain(self) -> int:
        return self.link.gain_db

    def doSetGain(self, value: int):
        self.link.gain_db = value


if __name__ == "__main__":
    from notificationcenter import NotificationCenter

    heard = []
    NotificationCenter().add_observer(
        heard, lambda note: heard.append(note.name),
        ExposureNotification.didSetExposure)

    cam = KiraluxCamera()
    print("state:", cam.state.name)
    cam.initializeDevice()
    print("state:", cam.state.name, "| version:", cam.version)
    print("capabilities:", [c.__name__ for c in cam.capabilities()])
    print("hasCapability(ExposureCapability):", cam.hasCapability(ExposureCapability))
    cam.setExposure(20_000)
    print("getExposure:", cam.getExposure(), cam.unit)
    cam.setGain(0)
    frame = cam.captureFrames(1)[0]
    print("frame:", repr(frame), "| dolp mean %.3f" % float(frame.dolp.mean()))
    cam.shutdownDevice()
    print("state:", cam.state.name, "| ExposureNotifications heard:", heard)
