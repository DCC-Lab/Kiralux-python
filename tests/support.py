"""Test doubles shared by the Kiralux test suite. No camera needed.

* :func:`pack_mosaic` — the inverse of ``unpack_mosaic``: builds the exact bytes the
  camera streams on EP 0x83 (16384-byte packets: a 3-byte header, 12-bit packed
  pixels, one padding byte; packet 0 also carries the tag list, ending with ENDT).
* :class:`FakeCameraPort` — a ``ProtocolDebugPort`` (answers every command of
  ``protocol.json`` from what it was last told) that also serves an image stream.
* :class:`FramedDebugPort` — the same, plus the camera's 1024-byte framing, for the
  standalone ``Kiralux`` driver that talks to a ``USBPort`` directly.

No hand-written camera emulator: every text answer comes from the CommandDictionary.
"""
from __future__ import annotations

import numpy as np

from hardwarelibrary.communication.protocol import CommandDictionary
from hardwarelibrary.communication.debugport import ProtocolDebugPort

from kiralux.camera_device import Command
from kiralux.device import PROTOCOL_PATH, COMMAND_SIZE
from kiralux.frame import BLOCK_SIZE, PACKET_HEADER, PACKET_DATA, TAG_SIZE, END_TAG

WIDTH, HEIGHT = 2448, 2048

IDENTITY = {"serial": 18658, "model": "CS505MUP1", "width": WIDTH, "height": HEIGHT,
            "depth": 12, "temperature": 29.0, "phase": 90,
            "vocabulary": " ".join(c.value for c in Command)}


def pack_mosaic(mosaic: np.ndarray) -> bytes:
    """Encode a (height, width) 12-bit mosaic into the camera's wire format."""
    pixels = np.asarray(mosaic, np.uint16).ravel()
    if pixels.size % 2:
        pixels = np.append(pixels, np.uint16(0))
    stream = np.empty(pixels.size // 2 * 3, np.uint8)
    even, odd = pixels[0::2], pixels[1::2]
    stream[0::3] = even & 0xFF
    stream[1::3] = (even >> 8) | ((odd & 0x0F) << 4)
    stream[2::3] = odd >> 4

    tags = bytearray(52)                            # magic + tag list, then the end-of-tags marker
    tags[:3] = b"\x90\x90\x00"
    tags += END_TAG + bytes(TAG_SIZE - len(END_TAG))
    first = BLOCK_SIZE - 1 - len(tags)
    chunks = [stream[:first]] + [stream[i:i + PACKET_DATA] for i in range(first, stream.size, PACKET_DATA)]
    packets = []
    for number, chunk in enumerate(chunks):
        head = bytes(tags) if number == 0 else bytes([0x90, 0x90, number & 0xFF])
        full = len(head) + chunk.size == BLOCK_SIZE - 1
        packets.append(head + chunk.tobytes() + (b"\x00" if full else b""))
    return b"".join(packets)


def frame_bytes(width=WIDTH, height=HEIGHT, seed=0) -> tuple[bytes, np.ndarray]:
    """A random 12-bit frame and the bytes the camera would stream for it."""
    mosaic = np.random.default_rng(seed).integers(0, 4096, (height, width), dtype=np.uint16)
    return pack_mosaic(mosaic), mosaic


def mosaic_from_channels(i0, i45, i90, i135) -> np.ndarray:
    """Interleave four half-resolution analyser images into a mosaic.

    Sony IMX250MZR super-pixel layout (top-left origin):  [ 90  45 / 135  0 ].
    """
    h, w = np.shape(i0)
    m = np.empty((2 * h, 2 * w), np.float32)
    m[0::2, 0::2], m[0::2, 1::2] = i90, i45
    m[1::2, 0::2], m[1::2, 1::2] = i135, i0
    return m


class FakeCameraPort(ProtocolDebugPort):
    """A ProtocolDebugPort that also streams image data and records what was asked."""

    def __init__(self, image: bytes = b"", identity: dict | None = None):
        super().__init__(CommandDictionary.fromFile(PROTOCOL_PATH))
        self.values.update(IDENTITY if identity is None else identity)
        self.image = image
        self.stream_calls = []
        self.sent = []                       # decoded text of every command written
        self.streaming = False               # like the camera: only a started capture has data to read

    def writeData(self, data, endPoint=None):
        text = bytes(data).split(b"\x00")[0].decode("latin1")
        self.sent.append(text)
        if text.split(" ")[0] in ("start", "stop"):
            self.streaming = text.startswith("start")
        return super().writeData(data, endPoint)

    def endPointForAddress(self, address):
        return address

    def readStream(self, length, endPoint=None, chunkSize=None, timeout=None):
        if not self.streaming:
            raise TimeoutError("nothing to read: no capture was started")
        self.stream_calls.append({"length": length, "endPoint": endPoint, "timeout": timeout})
        return bytearray(self.image[:length])


class FramedDebugPort(FakeCameraPort):
    """A ``FakeCameraPort`` that speaks the camera's *framing* too.

    ``KiraluxPort`` (and the standalone ``Kiralux``) write every command as a
    1024-byte null-padded buffer on EP 0x02 and read every reply as a 1024-byte buffer
    on EP 0x82. The description knows nothing of that padding — it is a transport
    detail — so this strips it on the way in and restores it on the way out, and the
    protocol answering is still the dictionary's. It also insists on the endpoints.
    """

    def writeData(self, data, endPoint=None):
        assert endPoint == 0x02, "commands go out on EP 0x02"
        assert len(data) == COMMAND_SIZE, "a command is always one 1024-byte buffer"
        return super().writeData(bytes(data).rstrip(b"\x00"), 0)

    def readData(self, length, endPoint=None):
        assert endPoint == 0x82 and length == COMMAND_SIZE, "replies come in on EP 0x82"
        reply = bytes(super().readData(len(self.outputBuffers[0]), 0))
        return bytearray(reply.ljust(COMMAND_SIZE, b"\x00"))

    def readStream(self, length, endPoint=None, chunkSize=None, timeout=None):
        assert endPoint == 0x83, "images come in on EP 0x83"
        return super().readStream(length, endPoint, chunkSize, timeout)
