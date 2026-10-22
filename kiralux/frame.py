"""Pure frame decoding and polarimetry for the Kiralux CS505MUP1.

No USB, no PyHardwareLibrary — just numpy. These are shared by every driver
variant (``Kiralux``, ``KiraluxDevice``, ``KiraluxCameraDevice``): they turn the
raw bytes read off endpoint 0x83 into a :class:`PolarFrame` and compute its
polarimetric views.
"""
from __future__ import annotations

from functools import cached_property

import numpy as np

# Image framing on endpoint 0x83: the stream is a sequence of 16384-byte packets.
#
#   packet 0  : 0x90 0x90 <seq16> | tag list (TSI, FCNT, PCKH, PCKL, IFMT, IOFF, ENDT;
#               8 bytes each) | pixels, up to the end of the packet
#   packet n  : 0x90 0x90 <seq16> | 16380 bytes of pixels
#
# Once the headers are stripped (60 bytes on packet 0, 4 on the others) the pixels are
# one continuous 12-bit packed stream: a triplet may straddle two packets, and the last
# byte of a packet is pixel data (not padding).
HEADER_SIZE = 16384                  # packet 0 (tags + first pixels)
BLOCK_SIZE = 16384                   # every packet
PACKET_HEADER = 4
PACKET_DATA = BLOCK_SIZE - PACKET_HEADER
TAG_SIZE = 8
END_TAG = b"ENDT"


def triplets(raw: np.ndarray) -> np.ndarray:
    """Unpack 12-bit Mono12p bytes (2 pixels per 3 bytes) into uint16 pixels."""
    b = raw[: raw.size // 3 * 3].reshape(-1, 3).astype(np.uint16)
    out = np.empty(b.shape[0] * 2, np.uint16)
    out[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
    out[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    return out


def unpack_mosaic(data: bytes, width: int, height: int) -> np.ndarray:
    """Unpack a 12-bit Mono12p frame into a (height, width) uint16 mosaic.

    Packet 0 carries a tag list followed by the first pixels; the other packets carry
    a 4-byte header followed by pixels. Missing pixels are zero-padded.
    """
    raw = np.frombuffer(data, np.uint8)
    tags_end = bytes(raw[:BLOCK_SIZE]).find(END_TAG)
    start = tags_end + TAG_SIZE if tags_end >= 0 else PACKET_HEADER
    payload = [raw[start:BLOCK_SIZE]] + [raw[offset + PACKET_HEADER: offset + BLOCK_SIZE]
                                         for offset in range(BLOCK_SIZE, raw.size, BLOCK_SIZE)]
    pixels = triplets(np.concatenate(payload))
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
    def raw_channels(self):
        """The four analyser images (I0, I45, I90, I135) as uint16 views of the mosaic.

        Half-resolution, with a stride of 2 in each direction: no copy, no conversion,
        they share the mosaic's memory (and are overwritten if it is).
        """
        m = self.mosaic
        m = m[: m.shape[0] & ~1, : m.shape[1] & ~1]
        return (m[1::2, 1::2], m[0::2, 1::2], m[0::2, 0::2], m[1::2, 0::2])

    @cached_property
    def channels(self):
        """The four analyser images (I0, I45, I90, I135), half-resolution, as float32."""
        return tuple(c.astype(np.float32) for c in self.raw_channels)

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
