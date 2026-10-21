"""Pure-Python driver for the ThorLabs Kiralux CS505MUP1 polarization camera.

Controls the camera over USB on macOS/Linux with no ThorLabs native libraries,
using the ``USBPort`` transport from DCC-Lab's PyHardwareLibrary. Obtained by
reverse-engineering the camera's (ASCII) USB protocol — see ``protocol-analysis/``.

The main entry point is :class:`KiraluxCameraDevice`: a single PyHardwareLibrary
``CameraDevice`` that does all the USB and protocol work itself — lifecycle,
state machine, notifications, capture loop, exposure/gain capabilities, and
``PolarFrame`` output — with no separate driver underneath.

    from kiralux import KiraluxCameraDevice
    with KiraluxCameraDevice() as cam:
        cam.exposure_us = 20_000
        frame = cam.snap()            # -> PolarFrame (.s0 / .dolp / .aolp / .falsecolor)

Also available: :class:`Kiralux`, a lightweight non-PhysicalDevice driver for
quick scripts, and :class:`KiraluxDevice`, a variant whose protocol is described
by a PyHardwareLibrary ``CommandDictionary`` (with a hardware-free mock).
"""
from .frame import PolarFrame, unpack_mosaic, hsv_to_rgb
from .camera_device import (
    KiraluxCameraDevice,
    ExposureCapability,
    GainCapability,
    Command,
    KiraluxError,
)
from .camera import Kiralux
from .device import KiraluxDevice, KiraluxPort

try:  # populated from the installed distribution's metadata
    from importlib.metadata import version, PackageNotFoundError

    try:
        __version__ = version("kiralux")
    except PackageNotFoundError:
        __version__ = "0+unknown"
except ImportError:  # pragma: no cover
    __version__ = "0+unknown"

__all__ = [
    "KiraluxCameraDevice",
    "ExposureCapability",
    "GainCapability",
    "Command",
    "KiraluxError",
    "Kiralux",
    "KiraluxDevice",
    "KiraluxPort",
    "PolarFrame",
    "unpack_mosaic",
    "hsv_to_rgb",
    "__version__",
]
