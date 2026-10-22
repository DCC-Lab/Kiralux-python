"""The lightweight ``Kiralux`` driver, with no camera.

It builds its own ``USBPort``, so a ``FramedDebugPort`` — a ProtocolDebugPort that
answers from protocol.json and adds the camera's 1024-byte framing — is put in its
place. The text answers still come from the CommandDictionary.
"""
import numpy as np
import pytest

import kiralux.camera as camera_module
from kiralux import Kiralux, KiraluxError, Command
from support import FramedDebugPort, IDENTITY, WIDTH, HEIGHT


class ErrorPort(FramedDebugPort):
    """Adds the two replies a description of *good* answers cannot express."""

    def processInputBuffers(self, endPointIndex):
        received = bytes(self.inputBuffers[endPointIndex])
        if received.startswith(b"bogus"):
            self.inputBuffers[endPointIndex] = bytearray()
            self.writeToOutputBuffer(b"error 4,Invalid command", endPointIndex)
        elif received.endswith(b".disc"):
            self.inputBuffers[endPointIndex] = bytearray()
            self.writeToOutputBuffer(b'{"name": "%s"}' % received[:-5], endPointIndex)
        else:
            super().processInputBuffers(endPointIndex)


@pytest.fixture
def make(monkeypatch, frame):
    ports = []

    def make(identity=None, cls=FramedDebugPort, **kwargs):
        def factory(**kw):
            port = cls(image=frame[0], identity=identity)
            port.constructed_with = kw
            ports.append(port)
            return port
        monkeypatch.setattr(camera_module, "USBPort", factory)
        return Kiralux(**kwargs)
    return make


def test_opening_talks_to_the_kiralux_and_identifies_it(make):
    cam = make(serial="18658")
    port = cam.port
    assert port.constructed_with == {"idVendor": 0x1313, "idProduct": 0x4001,
                                     "serialNumber": "18658", "interfaceNumber": 0}
    assert port.isOpen and port.defaultTimeout == 3000
    assert (cam.serial, cam.model) == ("18658", "CS505MUP1")
    assert repr(cam) == "<Kiralux CS505MUP1 sn=18658>"
    assert port.sent[:3] == ["stop", "sernum", "model"]


def test_context_manager_closes_the_port(make):
    with make() as cam:
        port = cam.port
        assert port.isOpen
    assert not port.isOpen


def test_identity_properties(make):
    cam = make()
    assert cam.sensor_size == (WIDTH, HEIGHT) and cam.bit_depth == 12
    assert cam.temperature == pytest.approx(29.0)


@pytest.mark.parametrize("name, value", [
    ("exposure_us", 20_000), ("gain_db", 7), ("roi", (3, 4, 500, 600)), ("binning", (2, 3)),
])
def test_settings_round_trip(make, name, value):
    cam = make()
    setattr(cam, name, value)
    assert getattr(cam, name) == value


def test_reset_roi_restores_the_full_sensor(make):
    cam = make()
    cam.binning, cam.roi = (4, 4), (10, 10, 100, 100)
    cam.reset_roi()
    assert cam.binning == (1, 1) and cam.roi == (0, 0, 2447, 2047)


def test_command_accepts_enums_and_strings_with_arguments(make):
    cam = make()
    assert cam.command(Command.EXP, 1500) == "1500"
    assert cam.command("exp") == "1500"
    cam.command("roi", 1, 2, 300, 400)
    assert cam.roi == (1, 2, 300, 400)


def test_an_error_reply_raises_KiraluxError(make):
    cam = make(cls=ErrorPort)
    with pytest.raises(KiraluxError, match="bogus.*error 4"):
        cam.command("bogus")


def test_describe_asks_for_the_dot_disc_documentation(make):
    cam = make(cls=ErrorPort)
    assert cam.describe(Command.EXP) == '{"name": "exp"}'
    assert cam.describe("gain") == '{"name": "gain"}'


def test_matching_vocabulary_is_silent_and_drift_warns(make, recwarn):
    make()
    assert not [w for w in recwarn if "drift" in str(w.message)]
    with pytest.warns(UserWarning, match="drift"):
        make(identity={**IDENTITY, "vocabulary": "exp gain extra"})


def test_snap_sets_exposure_runs_the_dialog_and_decodes(make, frame):
    cam = make()
    del cam.port.sent[:]
    f = cam.snap(exposure_us=4321, timeout=2.0)
    np.testing.assert_array_equal(np.asarray(f), frame[1])
    assert cam.port.sent == ["exp 4321", "stop", "hwtrig none", "nframes 1", "image_width",
                             "image_height", "arm", "start", "stop"]
    assert cam.port.stream_calls[0]["timeout"] == 2000


def test_available_lists_connected_serials(monkeypatch):
    import usb.core

    class Dev:
        serial_number = "18658\x00"
    monkeypatch.setattr(usb.core, "find", lambda **kw: [Dev(), object()])
    assert Kiralux.available() == ["18658", None]
