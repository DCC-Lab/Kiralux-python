"""Pure-Python driver for the ThorLabs Kiralux CS505MUP1 polarization camera.

Controls the camera over USB on macOS/Linux with no ThorLabs native libraries,
using the ``USBPort`` transport from DCC-Lab's PyHardwareLibrary. Obtained by
reverse-engineering the camera's (ASCII) USB protocol — see ``protocol-analysis/``.

Three entry points, all depending only on ``hardwarelibrary`` + ``numpy``:

* :class:`Kiralux` — the simple, direct driver. ``snap()`` returns a
  :class:`PolarFrame` carrying ``.s0`` / ``.dolp`` / ``.aolp`` / ``.falsecolor``.
* :class:`KiraluxDevice` — the same camera described by a PyHardwareLibrary
  ``CommandDictionary`` (see :mod:`kiralux.device`); comes with a hardware-free mock.
* :class:`KiraluxCamera` — a PyHardwareLibrary ``CameraDevice`` adapter with the
  state machine, notifications, capture loop and capability introspection.

    from kiralux import Kiralux
    with Kiralux() as cam:
        cam.exposure_us = 20_000
        frame = cam.snap()        # -> PolarFrame
"""
from .camera import (
    Kiralux,
    PolarFrame,
    KiraluxError,
    unpack_mosaic,
    hsv_to_rgb,
)
from .device import KiraluxDevice, KiraluxPort
from .phl import (
    KiraluxCamera,
    ExposureCapability,
    GainCapability,
)

try:  # populated from the installed distribution's metadata
    from importlib.metadata import version, PackageNotFoundError

    try:
        __version__ = version("kiralux")
    except PackageNotFoundError:
        __version__ = "0+unknown"
except ImportError:  # pragma: no cover
    __version__ = "0+unknown"

__all__ = [
    "Kiralux",
    "PolarFrame",
    "KiraluxError",
    "unpack_mosaic",
    "hsv_to_rgb",
    "KiraluxDevice",
    "KiraluxPort",
    "KiraluxCamera",
    "ExposureCapability",
    "GainCapability",
    "__version__",
]
