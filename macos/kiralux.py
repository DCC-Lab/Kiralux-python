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
from functools import cached_property
from typing import Optional

import numpy as np


# --------------------------------------------------------------------------- #
#  libusb backend: make `import usb1` work even with a non-standard libusb.
# --------------------------------------------------------------------------- #
def locate_libusb() -> None:
    """Load libusb from common locations if the default search fails."""
    import ctypes.util
    import glob
    import os
    import sys

    if ctypes.util.find_library("usb-1.0"):
        return
    if sys.platform == "darwin":
        roots = ("/opt/homebrew", "/usr/local", os.path.expanduser("~/.local/homebrew"))
        patterns = [os.path.join(r, "lib", "libusb-1.0*.dylib") for r in roots]
    else:
        patterns = ["/usr/lib*/libusb-1.0.so*", "/lib*/libusb-1.0.so*"]
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                return
            except OSError:
                pass


locate_libusb()
import usb1  # noqa: E402


# --------------------------------------------------------------------------- #
#  Protocol / transport constants
# --------------------------------------------------------------------------- #
VID, PID = 0x1313, 0x4001
EP_COMMAND, EP_RESPONSE, EP_IMAGE = 0x02, 0x82, 0x83   # bulk endpoints
COMMAND_SIZE = 1024                    # fixed command buffer length
HEADER_SIZE = 16384                    # frame header, precedes the pixels
BLOCK_SIZE = 16384                     # 12-bit triplets never cross a block
BLOCK_MAIN = BLOCK_SIZE - 1            # 16383 "main" bytes (+1 tail byte) per block
READS, READ_SIZE = 256, BLOCK_SIZE     # async reads of one burst each -> ~95 MB/s


class KiraluxError(RuntimeError):
    """A camera command returned an error, or the device is unavailable."""


# --------------------------------------------------------------------------- #
#  Standalone helpers
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


def open_device(context: "usb1.USBContext", serial: Optional[str] = None):
    """Open the Kiralux USB handle (first one, or the one matching `serial`)."""
    for device in context.getDeviceList(skip_on_error=True):
        if device.getVendorID() != VID or device.getProductID() != PID:
            continue
        if serial is None:
            return device.open()
        try:
            if device.getSerialNumber().strip("\x00 ") == serial:
                return device.open()
        except usb1.USBError:
            pass
    raise KiraluxError(
        "No Kiralux camera found"
        + (f" with serial {serial!r}" if serial else "")
        + " (connected? detached from any VM?)"
    )


# --------------------------------------------------------------------------- #
#  Polarization frame
# --------------------------------------------------------------------------- #
class PolarFrame:
    """A raw 2x2 polarization mosaic with lazily-computed polarimetric views.

    Sony IMX250MZR super-pixel layout (top-left origin):  [ 90  45 / 135  0 ].
    Stokes/DoLP/AoLP are half-resolution (one value per 2x2 super-pixel).
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
        return (m[1::2, 1::2], m[0::2, 1::2],    # I0,  I45
                m[0::2, 0::2], m[1::2, 0::2])     # I90, I135

    @cached_property
    def stokes(self):
        """Linear Stokes parameters (S0, S1, S2)."""
        i0, i45, i90, i135 = self.channels
        return (i0 + i45 + i90 + i135) / 2.0, i0 - i90, i45 - i135

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
        s0, s1, s2 = self.stokes
        return np.degrees(0.5 * np.arctan2(s2, s1))

    @property
    def falsecolor(self) -> np.ndarray:
        """HSV composite (hue=AoLP, saturation=DoLP, value=S0) as RGB uint8."""
        s0, s1, s2 = self.stokes
        dolp = np.clip(np.hypot(s1, s2) / np.maximum(s0, 1e-6), 0, 1)
        hue = (0.5 * np.arctan2(s2, s1) + np.pi / 2) / np.pi
        lo, hi = np.percentile(s0, [1, 99])
        value = np.clip((s0 - lo) / max(hi - lo, 1e-6), 0, 1)
        return hsv_to_rgb(hue, dolp, value)


# --------------------------------------------------------------------------- #
#  Camera
# --------------------------------------------------------------------------- #
class Kiralux:
    """A ThorLabs Kiralux CS505MUP1 polarization camera.

    Open the first camera (or one by serial), set acquisition parameters through
    plain attributes, and read frames with :meth:`snap`.
    """

    def __init__(self, serial: Optional[str] = None):
        self.context = usb1.USBContext()
        self.context.open()
        self.device = open_device(self.context, serial)
        try:
            self.device.setAutoDetachKernelDriver(True)
        except usb1.USBError:
            pass
        try:
            if self.device.kernelDriverActive(0):
                self.device.detachKernelDriver(0)
        except usb1.USBError:
            pass
        self.device.claimInterface(0)
        self.command("stop")
        self.serial = self.command("sernum")
        self.model = self.command("model")

    # -- discovery / lifecycle --------------------------------------------- #
    @staticmethod
    def available() -> list[str]:
        """Serial numbers (USB iSerial) of all connected Kiralux cameras."""
        with usb1.USBContext() as context:
            found = []
            for device in context.getDeviceList(skip_on_error=True):
                if device.getVendorID() == VID and device.getProductID() == PID:
                    try:
                        found.append(device.getSerialNumber().strip("\x00 "))
                    except usb1.USBError:
                        found.append(None)
            return found

    def close(self):
        try:
            self.device.releaseInterface(0)
        except usb1.USBError:
            pass
        self.context.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f"<Kiralux {self.model} sn={self.serial}>"

    # -- protocol ----------------------------------------------------------- #
    def command(self, text: str, timeout: int = 3000) -> str:
        """Send an ASCII command and return the camera's response.

        Raises :class:`KiraluxError` on an ``error ...`` reply. With no argument
        most commands return their current value (e.g. ``command("exp")``).
        """
        self.device.bulkWrite(EP_COMMAND, (text.encode() + b"\x00").ljust(COMMAND_SIZE, b"\x00"), timeout)
        reply = bytes(self.device.bulkRead(EP_RESPONSE, COMMAND_SIZE, timeout)).split(b"\x00")[0]
        reply = reply.decode("latin1").strip()
        if reply.startswith("error"):
            raise KiraluxError(f"{text!r} -> {reply}")
        return reply

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
        width, height = self.sensor_size
        raw = self.acquire(HEADER_SIZE + width * height * 3 // 2, timeout)
        return PolarFrame(unpack_mosaic(raw, width, height))

    def acquire(self, nbytes: int, timeout: float = 3.0) -> bytes:
        """Arm, software-trigger, and read `nbytes` from the image endpoint.

        Reads with many concurrent 16 KB transfers (one SuperSpeed burst each),
        which is what keeps the camera from overrunning (~95 MB/s).
        """
        buffer = bytearray()
        state = {"live": READS, "stop": False}

        def on_complete(transfer):
            if transfer.getStatus() == usb1.TRANSFER_COMPLETED:
                buffer.extend(transfer.getBuffer()[: transfer.getActualLength()])
            if not state["stop"] and len(buffer) < nbytes:
                try:
                    transfer.submit()
                    return
                except usb1.USBError:
                    pass
            state["live"] -= 1

        transfers = [self.device.getTransfer() for _ in range(READS)]
        for transfer in transfers:
            transfer.setBulk(EP_IMAGE, READ_SIZE, callback=on_complete, timeout=2000)
        self.command("arm")
        for transfer in transfers:
            transfer.submit()
        start = time.monotonic()
        self.command("start")
        while state["live"] and len(buffer) < nbytes and time.monotonic() - start < timeout:
            self.context.handleEventsTimeout(0.005)
        state["stop"] = True
        for transfer in transfers:
            try:
                transfer.cancel()
            except usb1.USBError:
                pass
        drain = time.monotonic()
        while state["live"] and time.monotonic() - drain < 0.15:
            self.context.handleEventsTimeout(0.005)
        self.command("stop")
        return bytes(buffer)
