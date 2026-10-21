"""Pure-Python driver for the ThorLabs Kiralux CS505MUP1 polarization camera.

No ThorLabs software required — talks the camera's native USB protocol directly
through libusb. Reverse-engineered; see HANDOFF.md / docs/PROTOCOL.md.

    from kiralux import Kiralux

    with Kiralux() as cam:
        cam.exposure_us = 20_000
        frame = cam.snap()              # -> PolarFrame (2048 x 2448 uint16 mosaic)
        intensity = frame.s0            # demosaiced Stokes views, computed lazily
        dolp      = frame.dolp          # degree of linear polarization  (0..1)
        angle     = frame.aolp          # angle of linear polarization   (-90..90 deg)
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np


# --------------------------------------------------------------------------- #
#  libusb backend: make `import usb1` work even with a non-standard libusb.
# --------------------------------------------------------------------------- #
def _preload_libusb() -> None:
    import ctypes.util
    import glob
    import os
    import sys

    if ctypes.util.find_library("usb-1.0"):
        return
    if sys.platform == "darwin":
        roots = ("/opt/homebrew", "/usr/local", os.path.expanduser("~/.local/homebrew"))
        pats = [os.path.join(r, "lib", "libusb-1.0*.dylib") for r in roots]
    else:
        pats = ["/usr/lib*/libusb-1.0.so*", "/lib*/libusb-1.0.so*"]
    for pat in pats:
        for path in sorted(glob.glob(pat)):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                return
            except OSError:
                pass


_preload_libusb()
import usb1  # noqa: E402


# --------------------------------------------------------------------------- #
#  Protocol / transport constants
# --------------------------------------------------------------------------- #
_VID, _PID = 0x1313, 0x4001
_EP_CMD, _EP_RSP, _EP_IMG = 0x02, 0x82, 0x83   # bulk: command / response / image
_CMD_LEN = 1024                                # fixed command buffer size
_HEADER = 16384                                # frame header, precedes the pixels
_BLOCK = 16384                                 # 12-bit triplets never cross a block
_MAIN = _BLOCK - 1                             # 16383 "main" bytes (+1 tail byte)
_N_XFER, _XFER = 256, _BLOCK                   # async reads of one burst each -> ~95 MB/s


class KiraluxError(RuntimeError):
    """A camera command returned an error, or the device is unavailable."""


# --------------------------------------------------------------------------- #
#  Polarization frame
# --------------------------------------------------------------------------- #
class PolarFrame:
    """A raw 2x2 polarization mosaic with lazily-computed polarimetric views.

    Sony IMX250MZR super-pixel layout (top-left origin):  [ 90  45 / 135  0 ].
    Stokes/DoLP/AoLP are half-resolution (one value per 2x2 super-pixel) and
    cached on first access.
    """

    __slots__ = ("mosaic", "_c")

    def __init__(self, mosaic: np.ndarray):
        self.mosaic = mosaic
        self._c: dict = {}

    def __array__(self, dtype=None):
        return self.mosaic if dtype is None else self.mosaic.astype(dtype)

    def __repr__(self):
        h, w = self.mosaic.shape
        return f"<PolarFrame {w}x{h} uint12>"

    @property
    def shape(self):
        return self.mosaic.shape

    @property
    def channels(self):
        """The four analyser images (I0, I45, I90, I135), half-resolution."""
        if "ch" not in self._c:
            m = self.mosaic
            m = m[: m.shape[0] & ~1, : m.shape[1] & ~1].astype(np.float32)
            self._c["ch"] = (m[1::2, 1::2], m[0::2, 1::2],   # I0,  I45
                             m[0::2, 0::2], m[1::2, 0::2])    # I90, I135
        return self._c["ch"]

    @property
    def stokes(self):
        """Linear Stokes parameters (S0, S1, S2)."""
        if "s" not in self._c:
            i0, i45, i90, i135 = self.channels
            self._c["s"] = ((i0 + i45 + i90 + i135) / 2.0,   # S0 total intensity
                            i0 - i90,                         # S1
                            i45 - i135)                       # S2
        return self._c["s"]

    @property
    def s0(self):
        """Total intensity image."""
        return self.stokes[0]

    @property
    def dolp(self):
        """Degree of linear polarization, 0..1."""
        s0, s1, s2 = self.stokes
        return np.hypot(s1, s2) / np.maximum(s0, 1e-6)

    @property
    def aolp(self):
        """Angle of linear polarization, in degrees (-90..90)."""
        _, s1, s2 = self.stokes
        return np.degrees(0.5 * np.arctan2(s2, s1))

    @property
    def falsecolor(self) -> np.ndarray:
        """HSV composite (hue=AoLP, saturation=DoLP, value=S0) as RGB uint8."""
        s0, s1, s2 = self.stokes
        dolp = np.clip(np.hypot(s1, s2) / np.maximum(s0, 1e-6), 0, 1)
        hue = (0.5 * np.arctan2(s2, s1) + np.pi / 2) / np.pi      # 0..1
        lo, hi = np.percentile(s0, [1, 99])
        val = np.clip((s0 - lo) / max(hi - lo, 1e-6), 0, 1)
        return _hsv_to_rgb(hue, dolp, val)


def _hsv_to_rgb(h, s, v) -> np.ndarray:
    h6 = (h % 1.0) * 6.0
    c = v * s
    x = c * (1 - np.abs(h6 % 2 - 1))
    i = h6.astype(int) % 6
    z = np.zeros_like(c)
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [c, x, z, z, x, c])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [x, c, c, x, z, z])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [z, z, x, c, c, x])
    m = v - c
    rgb = np.stack([r + m, g + m, b + m], axis=-1)
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


# --------------------------------------------------------------------------- #
#  Camera
# --------------------------------------------------------------------------- #
class Kiralux:
    """A ThorLabs Kiralux CS505MUP1 polarization camera.

    Open the first camera (or one by serial), set acquisition parameters through
    plain attributes, and read frames with :meth:`snap`.
    """

    def __init__(self, serial: Optional[str] = None):
        self._ctx = usb1.USBContext()
        self._ctx.open()
        self._dev = self._open_handle(serial)
        try:
            self._dev.setAutoDetachKernelDriver(True)
        except usb1.USBError:
            pass
        try:
            if self._dev.kernelDriverActive(0):
                self._dev.detachKernelDriver(0)
        except usb1.USBError:
            pass
        self._dev.claimInterface(0)
        self.command("stop")
        self.serial = self.command("sernum")
        self.model = self.command("model")

    # -- discovery / lifecycle --------------------------------------------- #
    @staticmethod
    def available() -> list[str]:
        """Serial numbers (USB iSerial) of all connected Kiralux cameras."""
        with usb1.USBContext() as ctx:
            found = []
            for d in ctx.getDeviceList(skip_on_error=True):
                if d.getVendorID() == _VID and d.getProductID() == _PID:
                    try:
                        found.append(d.getSerialNumber().strip("\x00 "))
                    except usb1.USBError:
                        found.append(None)
            return found

    def _open_handle(self, serial):
        for d in self._ctx.getDeviceList(skip_on_error=True):
            if d.getVendorID() != _VID or d.getProductID() != _PID:
                continue
            if serial is None:
                return d.open()
            try:
                if d.getSerialNumber() == serial:
                    return d.open()
            except usb1.USBError:
                pass
        raise KiraluxError(
            f"No Kiralux camera found"
            + (f" with serial {serial!r}" if serial else "")
            + " (connected? detached from any VM?)"
        )

    def close(self):
        try:
            self._dev.releaseInterface(0)
        except usb1.USBError:
            pass
        self._ctx.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f"<Kiralux {self.model} sn={self.serial}>"

    # -- low-level protocol ------------------------------------------------- #
    def command(self, text: str, timeout: int = 3000) -> str:
        """Send an ASCII command and return the camera's response.

        Raises :class:`KiraluxError` on an ``error ...`` reply. With no argument
        most commands return their current value (e.g. ``command("exp")``).
        """
        self._dev.bulkWrite(_EP_CMD, (text.encode() + b"\x00").ljust(_CMD_LEN, b"\x00"), timeout)
        resp = bytes(self._dev.bulkRead(_EP_RSP, _CMD_LEN, timeout)).split(b"\x00")[0]
        resp = resp.decode("latin1").strip()
        if resp.startswith("error"):
            raise KiraluxError(f"{text!r} -> {resp}")
        return resp

    def describe(self, command: str) -> str:
        """Return the camera's self-documentation (JSON) for a command."""
        return self.command(f"{command}.disc")

    # -- identity (read-only) ---------------------------------------------- #
    @property
    def sensor_size(self) -> tuple[int, int]:
        """(width, height) in pixels for the current ROI/binning."""
        return int(self.command("image_width")), int(self.command("image_height"))

    @property
    def bit_depth(self) -> int:
        return int(self.command("pixel_bit_depth"))

    @property
    def temperature(self) -> float:
        """Sensor temperature in degrees Celsius."""
        return float(self.command("temperature"))

    # -- acquisition settings (read/write) --------------------------------- #
    @property
    def exposure_us(self) -> int:
        return int(self.command("exp"))

    @exposure_us.setter
    def exposure_us(self, microseconds: int):
        self.command(f"exp {int(microseconds)}")

    @property
    def gain_db(self) -> int:
        return int(self.command("gain"))

    @gain_db.setter
    def gain_db(self, value: int):
        self.command(f"gain {int(value)}")

    @property
    def black_level(self) -> int:
        return int(self.command("blklvl"))

    @black_level.setter
    def black_level(self, value: int):
        self.command(f"blklvl {int(value)}")

    @property
    def roi(self) -> tuple[int, int, int, int]:
        """Region of interest as (left, top, right, bottom)."""
        return tuple(int(x) for x in self.command("roi").split())

    @roi.setter
    def roi(self, box: tuple[int, int, int, int]):
        left, top, right, bottom = box
        self.command(f"roi {left} {top} {right} {bottom}")

    @property
    def binning(self) -> tuple[int, int]:
        return int(self.command("hbin")), int(self.command("vbin"))

    @binning.setter
    def binning(self, hv: tuple[int, int]):
        h, v = hv
        self.command(f"hbin {int(h)}")
        self.command(f"vbin {int(v)}")

    def reset_roi(self):
        """Restore the full sensor (2448 x 2048) and 1x1 binning."""
        self.command("stop")
        self.command("hbin 1")
        self.command("vbin 1")
        self.command("roi 0 0 2447 2047")

    # -- frame acquisition -------------------------------------------------- #
    def snap(self, exposure_us: Optional[int] = None, *, timeout: float = 3.0) -> PolarFrame:
        """Acquire one software-triggered frame and return it as a PolarFrame."""
        if exposure_us is not None:
            self.exposure_us = exposure_us
        self.command("stop")
        self.command("hwtrig none")
        self.command("nframes 1")
        w, h = self.sensor_size
        raw = self._read_frame(w, h, timeout)
        return PolarFrame(self._decode(raw, w, h))

    def _read_frame(self, w: int, h: int, timeout: float) -> bytes:
        """Arm, software-trigger, and drain EP 0x83 with concurrent 16 KB reads."""
        target = _HEADER + w * h * 3 // 2
        buf = bytearray()
        state = {"live": _N_XFER, "stop": False}

        def on_complete(xfer):
            if xfer.getStatus() == usb1.TRANSFER_COMPLETED:
                buf.extend(xfer.getBuffer()[: xfer.getActualLength()])
            if not state["stop"] and len(buf) < target:
                try:
                    xfer.submit()
                    return
                except usb1.USBError:
                    pass
            state["live"] -= 1

        xfers = [self._dev.getTransfer() for _ in range(_N_XFER)]
        for x in xfers:
            x.setBulk(_EP_IMG, _XFER, callback=on_complete, timeout=2000)
        self.command("arm")
        for x in xfers:
            x.submit()
        t0 = time.monotonic()
        self.command("start")
        while state["live"] and len(buf) < target and time.monotonic() - t0 < timeout:
            self._ctx.handleEventsTimeout(0.005)
        state["stop"] = True
        for x in xfers:
            try:
                x.cancel()
            except usb1.USBError:
                pass
        t1 = time.monotonic()
        while state["live"] and time.monotonic() - t1 < 0.15:
            self._ctx.handleEventsTimeout(0.005)
        self.command("stop")
        return bytes(buf)

    @staticmethod
    def _decode(data: bytes, w: int, h: int) -> np.ndarray:
        """Unpack the 12-bit Mono12p stream into a (h, w) uint16 mosaic.

        Triplets do not cross the 16384-byte block boundaries; each block holds
        16383 "main" bytes plus one "tail" byte, and the tail bytes (concatenated)
        form the final pixels of the image.
        """
        body = memoryview(data)[_HEADER:]
        n = len(body) // _BLOCK
        blocks = np.frombuffer(body[: n * _BLOCK], np.uint8).reshape(n, _BLOCK)

        def triplets(raw: np.ndarray) -> np.ndarray:
            b = raw.reshape(-1, 3).astype(np.uint16)
            out = np.empty(b.shape[0] * 2, np.uint16)
            out[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
            out[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
            return out

        main = triplets(blocks[:, :_MAIN])
        tail = np.concatenate([blocks[:, _MAIN], np.frombuffer(body[n * _BLOCK:], np.uint8)])
        extra = triplets(tail[: (len(tail) // 3) * 3]) if len(tail) >= 3 else main[:0]

        pixels = np.concatenate([main, extra])
        need = w * h
        if pixels.size < need:
            pixels = np.concatenate([pixels, np.zeros(need - pixels.size, np.uint16)])
        return pixels[:need].reshape(h, w)
