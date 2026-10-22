"""Tests that need a real Kiralux on USB. Skipped when none is plugged in.

The same behaviour is also checked with and without a camera by the ``camera``
fixture (see ``test_contract.py``); here are the things only a real one can show:
the firmware's vocabulary, real timing, real image content, the real USB framing.
"""
import numpy as np
import pytest
from hardwarelibrary.communication.protocol import CommandDictionary

from kiralux import Kiralux, KiraluxCameraDevice, KiraluxDevice, Command, PolarFrame
from kiralux.device import PROTOCOL_PATH

pytestmark = pytest.mark.hardware


@pytest.fixture(scope="module")
def cam():
    with KiraluxCameraDevice() as c:
        c.exposure_us, c.binning, c.roi = 20_000, (1, 1), (0, 0, 2447, 2047)
        yield c


def test_a_camera_is_listed():
    serials = KiraluxCameraDevice.available()
    assert len(serials) >= 1 and all(s is None or s.isdigit() for s in serials)


def test_firmware_vocabulary_matches_the_Command_enum(cam):
    reported = set(cam.performTransaction("DISCOVER")["vocabulary"].split())
    assert reported == {c.value for c in Command}


def test_identity_matches_the_polarization_model(cam):
    assert cam.version == "CS505MUP1"
    assert cam.sensor_size == (2448, 2048) and cam.bit_depth == 12
    assert cam.polar_phase in (0, 45, 90, 135)
    assert 0 < cam.temperature < 80


def test_a_real_frame_is_a_plausible_image(cam):
    f = cam.snap()
    m = np.asarray(f).astype(int)
    assert isinstance(f, PolarFrame) and m.shape == (2048, 2448)
    assert m.max() <= 4095 and m.max() > 0
    assert np.median(np.abs(m[2:] - m[:-2])) < 500           # a smooth scene, not scrambled bits
    assert np.nanmin(f.dolp) >= 0 and np.isfinite(f.aolp).all()


def test_a_longer_exposure_is_brighter(cam):
    cam.exposure_us = 2_000
    dim = np.asarray(cam.snap()).mean()
    cam.exposure_us = 40_000
    bright = np.asarray(cam.snap()).mean()
    cam.exposure_us = 20_000
    assert bright > dim


def test_consecutive_snaps_work(cam):
    assert len(cam.captureFrames(3)) == 3


def test_the_protocol_description_is_understood_by_the_real_camera():
    with KiraluxDevice() as c:
        assert c.model == "CS505MUP1"
        assert isinstance(c.serial, int)
        assert c.snap().shape == (2048, 2448)


def test_the_standalone_driver_works_too():
    with Kiralux() as c:
        assert c.model == "CS505MUP1"
        assert c.snap(20_000).shape == (2048, 2448)
