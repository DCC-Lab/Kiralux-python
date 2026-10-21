"""Pure-Python driver for the ThorLabs Kiralux CS505MUP1 polarization camera,
built on PyHardwareLibrary's ``USBPort`` (pyusb) instead of a private usb1 transport.

This is the "option B" variant: the camera's command dialog goes through
``USBPort.writeData``/``readData`` and the image through ``USBPort.readStream`` — the
high-throughput bulk read added in
https://github.com/DCC-Lab/PyHardwareLibrary/pull/120. The high-level API
(``snap`` -> ``PolarFrame`` with ``.s0``/``.dolp``/``.aolp``) is unchanged.

    pip install "hardwarelibrary>=2.2.0"   # provides USBPort.readStream (PR #120, released in hardwarelibrary 2.2.0)
    # macOS with a non-standard brew prefix:
    export DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib

    from kiralux import Kiralux
    with Kiralux() as cam:
        cam.exposure_us = 20_000
        frame = cam.snap()
        dolp = frame.dolp
"""
from __future__ import annotations

from enum import Enum
from functools import cached_property
from typing import Optional

import numpy as np

from hardwarelibrary.communication.usbport import USBPort


# --------------------------------------------------------------------------- #
#  Protocol / transport constants
# --------------------------------------------------------------------------- #
VID, PID = 0x1313, 0x4001
EP_COMMAND, EP_RESPONSE, EP_IMAGE = 0x02, 0x82, 0x83
COMMAND_SIZE = 1024
HEADER_SIZE = 16384
BLOCK_SIZE = 16384
BLOCK_MAIN = BLOCK_SIZE - 1


class Command(str, Enum):
    """The camera's command vocabulary — the single source of truth, mirroring
    what the camera reports through ``discover``.

    Members are ``str`` so they can be used directly; ``Kiralux.command`` also
    accepts a plain string. ``Kiralux.validate_vocabulary()`` checks this enum
    against the live ``discover`` list at open time to catch firmware drift.
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


class KiraluxError(RuntimeError):
    """A camera command returned an error, or the device is unavailable."""


# --------------------------------------------------------------------------- #
#  Standalone helpers (identical to the usb1 driver)
# --------------------------------------------------------------------------- #
def unpack_mosaic(data: bytes, width: int, height: int) -> np.ndarray:
    """Unpack a 12-bit Mono12p frame into a (height, width) uint16 mosaic.

    Triplets do not cross the 16384-byte block boundaries; each block holds 16383
    "main" bytes plus one "tail" byte, and the tail bytes (concatenated) form the
    final pixels of the image.
    """
    body = memoryview(data)[HEADER_SIZE:]
    n = len(body) // BLOCK_SIZE
    blocks = np.frombuffer(body[: n * BLOCK_SIZE], np.uint8).reshape(n, BLOCK_SIZE)

    def triplets(raw: np.ndarray) -> np.ndarray:
        b = raw.reshape(-1, 3).astype(np.uint16)
        out = np.empty(b.shape[0] * 2, np.uint16)
        out[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
        out[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
        return out

    main = triplets(blocks[:, :BLOCK_MAIN])
    tail = np.concatenate([blocks[:, BLOCK_MAIN], np.frombuffer(body[n * BLOCK_SIZE:], np.uint8)])
    extra = triplets(tail[: len(tail) // 3 * 3]) if len(tail) >= 3 else main[:0]

    pixels = np.concatenate([main, extra])
    need = width * height
    if pixels.size < need:
        pixels = np.concatenate([pixels, np.zeros(need - pixels.size, np.uint16)])
    return pixels[:need].reshape(height, width)


def hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Vectorized HSV (each 0..1) -> RGB uint8 image."""
    h6 = (h % 1.0) * 6.0
    c = v * s
    x = c * (1 - np.abs(h6 % 2 - 1))
    z = np.zeros_like(c)
    i = h6.astype(int) % 6
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [c, x, z, z, x, c])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [x, c, c, x, z, z])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [z, z, x, c, c, x])
    m = v - c
    return (np.clip(np.stack([r + m, g + m, b + m], axis=-1), 0, 1) * 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
#  Polarization frame (identical to the usb1 driver)
# --------------------------------------------------------------------------- #
class PolarFrame:
    """A raw 2x2 polarization mosaic with lazily-computed polarimetric views.

    Sony IMX250MZR super-pixel layout (top-left origin):  [ 90  45 / 135  0 ].
    """

    def __init__(self, mosaic: np.ndarray):
        self.mosaic = mosaic

    def __array__(self, dtype=None):
        return self.mosaic if dtype is None else self.mosaic.astype(dtype)

    def __repr__(self):
        h, w = self.mosaic.shape
        return f"<PolarFrame {w}x{h} uint12>"

    @property
    def shape(self):
        return self.mosaic.shape

    @cached_property
    def channels(self):
        """The four analyser images (I0, I45, I90, I135), half-resolution."""
        m = self.mosaic
        m = m[: m.shape[0] & ~1, : m.shape[1] & ~1].astype(np.float32)
        return (m[1::2, 1::2], m[0::2, 1::2], m[0::2, 0::2], m[1::2, 0::2])

    @cached_property
    def stokes(self):
        """Linear Stokes parameters (S0, S1, S2)."""
        i0, i45, i90, i135 = self.channels
        return (i0 + i45 + i90 + i135) / 2.0, i0 - i90, i45 - i135

    @property
    def s0(self):
        return self.stokes[0]

    @property
    def dolp(self):
        s0, s1, s2 = self.stokes
        return np.hypot(s1, s2) / np.maximum(s0, 1e-6)

    @property
    def aolp(self):
        s0, s1, s2 = self.stokes
        return np.degrees(0.5 * np.arctan2(s2, s1))

    @property
    def falsecolor(self) -> np.ndarray:
        s0, s1, s2 = self.stokes
        dolp = np.clip(np.hypot(s1, s2) / np.maximum(s0, 1e-6), 0, 1)
        hue = (0.5 * np.arctan2(s2, s1) + np.pi / 2) / np.pi
        lo, hi = np.percentile(s0, [1, 99])
        value = np.clip((s0 - lo) / max(hi - lo, 1e-6), 0, 1)
        return hsv_to_rgb(hue, dolp, value)


# --------------------------------------------------------------------------- #
#  Camera (transport = USBPort)
# --------------------------------------------------------------------------- #
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
