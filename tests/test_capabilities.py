"""The eight capabilities: validation, notifications and read-only-ness.

Validators are tested on their own and through the device; a refused call must
touch neither the camera nor the notification centre.
"""
import pytest
from notificationcenter.core import NotificationCenter

from kiralux import capabilities as caps
from kiralux import (ExposureCapability, GainCapability, BlackLevelCapability, BinningCapability,
                     RegionOfInterestCapability, FrameCountCapability, TemperatureCapability,
                     PolarizationPhaseCapability, KiraluxCameraDevice)
from hardwarelibrary.physicaldevice import PhysicalDevice

ALL = [ExposureCapability, GainCapability, BlackLevelCapability, BinningCapability,
       RegionOfInterestCapability, FrameCountCapability, TemperatureCapability,
       PolarizationPhaseCapability]
FULL_ROI = (0, 0, 2447, 2047)


class Recorder:
    """Collects every notification of the given enum posted by one device."""

    def __init__(self, device, notification_enum):
        self.events = []
        for name in notification_enum:
            NotificationCenter().add_observer(self, self.seen, name, device)

    def seen(self, notification):
        self.events.append((notification.name.value, notification.user_info))

    @property
    def names(self):
        return [name for name, _ in self.events]


# --------------------------------------------------------------------------- #
#  validators
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("validator, ok, bad", [
    (caps.validateGain, [0, 1, 480], [-1, 481]),
    (caps.validateBlackLevel, [0, 4095], [-1, 4096]),
    (caps.validateFrameCount, [0, 1, 4294967280], [-1, 4294967281]),
])
def test_scalar_validators_include_their_limits(validator, ok, bad):
    for value in ok:
        validator(None, value)
    for value in bad:
        with pytest.raises(ValueError):
            validator(None, value)


@pytest.mark.parametrize("value", ["5", None, True, [1]])
def test_validators_refuse_non_numbers(value):
    with pytest.raises(TypeError):
        caps.validateGain(None, value)


@pytest.mark.parametrize("binning", [(1, 1), (16, 16), (1, 16), (4, 2)])
def test_binning_accepts_1_to_16(binning):
    caps.validateBinning(None, binning)


@pytest.mark.parametrize("binning", [(0, 1), (1, 0), (17, 1), (1, 17)])
def test_binning_refuses_outside_1_to_16(binning):
    with pytest.raises(ValueError):
        caps.validateBinning(None, binning)


@pytest.mark.parametrize("box", [FULL_ROI, (0, 0, 259, 3), (2188, 2044, 2447, 2047), (100, 100, 400, 400)])
def test_roi_accepts_valid_boxes(box):
    caps.validateRegionOfInterest(None, box)


@pytest.mark.parametrize("box", [
    (-1, 0, 2447, 2047), (2189, 0, 2447, 2047), (0, -1, 2447, 2047), (0, 2045, 2447, 2047),
    (0, 0, 258, 2047), (0, 0, 2448, 2047), (0, 0, 2447, 2), (0, 0, 2447, 2048),
])
def test_roi_refuses_out_of_range_edges(box):
    with pytest.raises(ValueError):
        caps.validateRegionOfInterest(None, box)


@pytest.mark.parametrize("box", [(300, 0, 300 - 1 + 1, 100), (400, 0, 300, 100), (0, 200, 400, 200), (0, 300, 400, 100)])
def test_roi_refuses_empty_or_inverted_boxes(box):
    with pytest.raises(ValueError):
        caps.validateRegionOfInterest(None, box)


# --------------------------------------------------------------------------- #
#  declared contract
# --------------------------------------------------------------------------- #
def test_the_device_has_all_eight_capabilities(mock_camera):
    assert set(mock_camera.capabilities()) >= set(ALL)
    assert all(mock_camera.hasCapability(c) for c in ALL)


@pytest.mark.parametrize("capability, writable", [
    (ExposureCapability, True), (GainCapability, True), (BlackLevelCapability, True),
    (BinningCapability, True), (RegionOfInterestCapability, True), (FrameCountCapability, True),
    (TemperatureCapability, False), (PolarizationPhaseCapability, False),
])
def test_read_write_flags(capability, writable):
    assert capability.isReadable is True
    assert capability.isWritable is writable


@pytest.mark.parametrize("capability, unit", [
    (ExposureCapability, "us"), (GainCapability, "dB"), (BlackLevelCapability, "ADU"),
    (TemperatureCapability, "C"), (PolarizationPhaseCapability, "deg"),
])
def test_units(capability, unit):
    assert capability.unit == unit


@pytest.mark.parametrize("capability", [TemperatureCapability, PolarizationPhaseCapability])
def test_read_only_capabilities_have_no_setter(capability):
    assert not any(n.startswith("set") for n in vars(capability))


# --------------------------------------------------------------------------- #
#  through the device
# --------------------------------------------------------------------------- #
SETTERS = [
    ("setExposure", "getExposure", 12_345, caps.ExposureNotification),
    ("setGain", "getGain", 7, caps.GainNotification),
    ("setBlackLevel", "getBlackLevel", 8, caps.BlackLevelNotification),
    ("setBinning", "getBinning", (2, 4), caps.BinningNotification),
    ("setRegionOfInterest", "getRegionOfInterest", (10, 20, 400, 500), caps.RegionOfInterestNotification),
    ("setFrameCount", "getFrameCount", 3, caps.FrameCountNotification),
]


@pytest.mark.parametrize("setter, getter, value, notification", SETTERS)
def test_what_was_set_is_what_is_read(mock_camera, setter, getter, value, notification):
    getattr(mock_camera, setter)(value)
    assert getattr(mock_camera, getter)() == value


@pytest.mark.parametrize("setter, getter, value, notification", SETTERS)
def test_a_set_posts_will_then_did_and_a_get_posts_did(mock_camera, setter, getter, value, notification):
    recorder = Recorder(mock_camera, notification)
    getattr(mock_camera, setter)(value)
    getattr(mock_camera, getter)()
    names = recorder.names
    assert names[0].startswith("willSet") and names[1].startswith("didSet") and names[2].startswith("didGet")
    assert recorder.events[1][1]["error"] is None
    assert recorder.events[2][1]["result"] == value


def test_notifications_carry_the_argument_by_name(mock_camera):
    recorder = Recorder(mock_camera, caps.ExposureNotification)
    mock_camera.setExposure(500)
    assert recorder.events[0][1] == {"microseconds": 500}


@pytest.mark.parametrize("setter, bad", [
    ("setGain", 500), ("setGain", -1), ("setBlackLevel", 9000), ("setBinning", (0, 1)),
    ("setRegionOfInterest", (0, 0, 10, 10)), ("setFrameCount", -5),
])
def test_a_refused_value_sends_nothing_and_announces_nothing(mock_camera, port, setter, bad):
    sent_before = list(port.sent)
    recorder = Recorder(mock_camera, caps.GainNotification)
    for enum in (caps.BlackLevelNotification, caps.BinningNotification,
                 caps.RegionOfInterestNotification, caps.FrameCountNotification):
        for name in enum:
            NotificationCenter().add_observer(recorder, recorder.seen, name, mock_camera)
    with pytest.raises((ValueError, TypeError)):
        getattr(mock_camera, setter)(bad)
    assert port.sent == sent_before
    assert recorder.events == []


def test_a_hook_that_fails_still_posts_did_with_the_error(mock_camera, monkeypatch):
    def broken(microseconds):
        raise RuntimeError("usb unplugged")
    monkeypatch.setattr(mock_camera, "doSetExposure", broken)
    recorder = Recorder(mock_camera, caps.ExposureNotification)
    with pytest.raises(RuntimeError, match="usb unplugged"):
        mock_camera.setExposure(1000)
    assert recorder.names == ["willSetExposure", "didSetExposure"]
    assert isinstance(recorder.events[1][1]["error"], RuntimeError)


def test_read_only_values_come_from_the_camera(mock_camera):
    assert mock_camera.getTemperature() == 29.0
    assert mock_camera.getPolarizationPhase() == 90
    recorder = Recorder(mock_camera, caps.TemperatureNotification)
    mock_camera.getTemperature()
    assert recorder.names == ["didGetTemperature"]


@pytest.mark.parametrize("call", [
    lambda c: c.getExposure(), lambda c: c.setGain(1), lambda c: c.getTemperature(),
])
def test_capabilities_refuse_to_run_before_the_device_is_initialized(call):
    cam = KiraluxCameraDevice(port=object())
    with pytest.raises(PhysicalDevice.NotInitialized):
        call(cam)
