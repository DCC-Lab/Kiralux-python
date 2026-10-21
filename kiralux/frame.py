"""Pure frame decoding and polarimetry for the Kiralux CS505MUP1.

No USB, no PyHardwareLibrary — just numpy. These are shared by every driver
variant (``Kiralux``, ``KiraluxDevice``, ``KiraluxCameraDevice``): they turn the
raw bytes read off endpoint 0x83 into a :class:`PolarFrame` and compute its
polarimetric views.
"""
from __future__ import annotations

from functools import cached_property

import numpy as np

# Image framing on endpoint 0x83: a 16384-byte header, then 12-bit packed pixels
# in 16384-byte blocks. 12-bit triplets do NOT cross a block boundary, so each
# block holds 16383 "main" bytes + 1 "tail" byte.
HEADER_SIZE = 16384
BLOCK_SIZE = 16384
BLOCK_MAIN = BLOCK_SIZE - 1


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
