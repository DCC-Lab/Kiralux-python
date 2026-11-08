"""A hardware-free stand-in for KiraluxCameraDevice, to develop the example apps with
no camera attached.

This is a different mock than the one already described in ``device.py`` (a
``ProtocolDebugPort`` that answers ``KiraluxDevice``'s text commands with no USB
attached): that one mocks the wire protocol. This one mocks the camera-device API
itself -- ``streaming``/``startStreaming``/``stopStreaming``/``snap``/``setExposure`` --
which is the level the example apps (``preview_mytk*.py``) actually call, and fabricates
a synthetic :class:`~kiralux.frame.PolarFrame` (a fake birefringent-slide scene, with
shot noise that scales with exposure like the real sensor) instead of decoding real USB
bytes.

    from kiralux.debug import KiraluxDebug
    camera = KiraluxDebug()
    camera.initializeDevice()
    camera.startStreaming()
    frame = camera.snap()                 # synthetic PolarFrame
"""
from __future__ import annotations

import time

import numpy as np

from .frame import PolarFrame

SENSOR_WIDTH, SENSOR_HEIGHT = 2448, 2048
FULL_12_BIT = 4095
REFERENCE_EXPOSURE_US = 10_000    # exposure at which the synthetic scene reaches full well
FRAME_INTERVAL_S = 1 / 30         # matches the real camera's streaming frame rate
PHOTON_GAIN = 40                  # ADU per "photon" bucket -- higher = less shot noise per ADU


def _synthetic_truth(width, height):
    """A fake birefringent-slide scene: a round "slide" with smoothly varying axis and
    retardance (axis wanders, retardance peaks in a ring), close in spirit to last
    night's tissue data, plus a uniform low-retardance background outside it."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    xn, yn = x / width - 0.5, y / height - 0.5
    axis_deg = 45 * np.sin(6 * xn) * np.cos(5 * yn)
    radius = np.hypot(xn, yn)
    inside = radius < 0.38
    delta_deg = np.where(inside, 20 * np.exp(-((radius - 0.2) ** 2) / 0.02), 0.5)
    return axis_deg, delta_deg


class KiraluxDebug:
    """Duck-types the handful of ``KiraluxCameraDevice`` members the example apps
    use: ``initializeDevice``/``shutdownDevice``, ``setExposure``,
    ``streaming``/``startStreaming``/``stopStreaming``, ``snap()``. No USB, no
    protocol dialog -- just a synthetic frame with plausible shot noise.
    """

    def __init__(self, sensor_size: tuple[int, int] = (SENSOR_WIDTH, SENSOR_HEIGHT)):
        self.sensor_size = sensor_size
        self.streaming = False
        self._exposure_us = REFERENCE_EXPOSURE_US
        width, height = sensor_size[0] // 2, sensor_size[1] // 2
        self._axis_deg, self._delta_deg = _synthetic_truth(width, height)
        self._rng = np.random.default_rng()

    def __repr__(self):
        return f"<KiraluxDebug (no camera) {self.sensor_size[0]}x{self.sensor_size[1]}>"

    # -- lifecycle (no-ops: nothing to open/close) --------------------------- #
    def initializeDevice(self):
        pass

    def shutdownDevice(self):
        self.streaming = False

    def __enter__(self):
        self.initializeDevice()
        return self

    def __exit__(self, *exc):
        self.shutdownDevice()

    # -- settings ------------------------------------------------------------ #
    def getExposure(self) -> int:
        return self._exposure_us

    def setExposure(self, microseconds: int):
        self._exposure_us = int(microseconds)

    # -- continuous acquisition ----------------------------------------------- #
    def startStreaming(self):
        self.streaming = True

    def stopStreaming(self):
        self.streaming = False

    # -- acquisition ----------------------------------------------------------- #
    def snap(self) -> PolarFrame:
        """A synthetic frame of the fake scene, with shot noise that scales with
        exposure (less noise, and more saturation, at a longer exposure -- same
        trade-off as the real sensor)."""
        if self.streaming:
            time.sleep(FRAME_INTERVAL_S)

        s0 = FULL_12_BIT * np.clip(self._exposure_us / REFERENCE_EXPOSURE_US, 0, 1.3)
        dolp = np.clip(np.sin(np.radians(self._delta_deg)), 0, 1)
        aolp_rad = np.radians(self._axis_deg)
        s1 = s0 * dolp * np.cos(2 * aolp_rad)
        s2 = s0 * dolp * np.sin(2 * aolp_rad)
        i0, i90 = (s0 + s1) / 2, (s0 - s1) / 2
        i45, i135 = (s0 + s2) / 2, (s0 - s2) / 2

        height, width = self._axis_deg.shape
        mosaic = np.zeros((height * 2, width * 2), np.uint16)
        for channel, (ry, rx) in zip((i0, i45, i90, i135), ((1, 1), (0, 1), (0, 0), (1, 0))):
            noisy = self._rng.poisson(np.clip(channel, 0, None) * PHOTON_GAIN) / PHOTON_GAIN
            mosaic[ry::2, rx::2] = np.clip(np.rint(noisy), 0, FULL_12_BIT).astype(np.uint16)
        return PolarFrame(mosaic)
