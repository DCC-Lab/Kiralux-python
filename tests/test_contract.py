"""One contract, two backends: the ``camera`` fixture is the debug-port camera, and
(when one is plugged in) a real one. Nothing here may depend on a particular value
the mock was seeded with."""
import numpy as np
import pytest

from kiralux import PolarFrame, KiraluxCameraDevice


def test_identity_is_sane(camera):
    w, h = camera.sensor_size
    assert w > 0 and h > 0 and w % 2 == 0 and h % 2 == 0
    assert camera.bit_depth == 12
    assert camera.getPolarizationPhase() in (0, 45, 90, 135)
    assert isinstance(camera.getTemperature(), float)
    assert str(camera.serial).isdigit()


def test_exposure_round_trips(camera):
    camera.setExposure(10_000)
    assert camera.getExposure() == pytest.approx(10_000, rel=0.05)


@pytest.mark.parametrize("setter, getter, value", [
    ("setGain", "getGain", 0),
    ("setBlackLevel", "getBlackLevel", 5),
    ("setBinning", "getBinning", (1, 1)),
    ("setRegionOfInterest", "getRegionOfInterest", (0, 0, 2447, 2047)),
    ("setFrameCount", "getFrameCount", 1),
])
def test_settings_round_trip(camera, setter, getter, value):
    getattr(camera, setter)(value)
    assert getattr(camera, getter)() == value


def test_out_of_range_values_are_refused_before_the_camera_hears_of_it(camera):
    before = camera.getGain()
    with pytest.raises(ValueError):
        camera.setGain(481)
    assert camera.getGain() == before


def test_snap_gives_a_polar_frame_of_the_sensor_size(camera):
    camera.setBinning((1, 1))
    camera.setRegionOfInterest((0, 0, 2447, 2047))
    w, h = camera.sensor_size
    f = camera.snap()
    assert isinstance(f, PolarFrame) and f.shape == (h, w)
    assert np.asarray(f).max() <= 4095
    assert f.s0.shape == (h // 2, w // 2)
    assert f.falsecolor.shape == (h // 2, w // 2, 3)
