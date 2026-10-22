"""The command description (protocol.json) and KiraluxDevice, with no camera.

``ProtocolDebugPort`` stands in for the instrument using the *same* description the
real driver sends with: a request's values are remembered by name, and a reply
answers from that memory.
"""
import json
import pathlib
import re

import numpy as np
import pytest
from hardwarelibrary.communication.protocol import CommandDictionary, RequestDidNotMatch
from hardwarelibrary.physicaldevice import DeviceState

import kiralux.device as device
from kiralux import KiraluxDevice
from kiralux.device import PROTOCOL_PATH
from support import FakeCameraPort, WIDTH, HEIGHT

PACKAGE = pathlib.Path(device.__file__).parent


@pytest.fixture(scope="module")
def protocol():
    return CommandDictionary.fromFile(PROTOCOL_PATH)


class TestDescription:
    def test_every_command_round_trips_a_specimen(self, protocol):
        protocol.validate()

    def test_usage_lists_the_commands(self, protocol):
        usage = protocol.usage()
        assert "EXP_SET(exposure: int)" in usage and "ROI_SET" in usage

    def test_every_command_the_drivers_call_is_described(self, protocol):
        used = set()
        for source in PACKAGE.glob("*.py"):
            used |= set(re.findall(r'performTransaction\(\s*"([A-Z_]+)"', source.read_text()))
        assert used, "found no performTransaction calls: the pattern is stale"
        assert used <= set(protocol.names), sorted(used - set(protocol.names))

    def test_every_described_command_is_used_by_a_driver(self, protocol):
        used = set()
        for source in PACKAGE.glob("*.py"):
            used |= set(re.findall(r'performTransaction\(\s*"([A-Z_]+)"', source.read_text()))
        assert set(protocol.names) <= used, sorted(set(protocol.names) - used)

    def test_the_file_is_plain_json_naming_the_camera(self):
        assert "Kiralux" in json.loads(open(PROTOCOL_PATH).read())["device"]

    def test_an_unknown_request_is_refused_rather_than_ignored(self):
        with pytest.raises(RequestDidNotMatch):
            FakeCameraPort().writeData(b"no_such_command")

    def test_every_setting_reads_back_what_was_set(self, protocol):
        port = FakeCameraPort()
        for setter, getter, args, expected in [
            ("EXP_SET", "EXP_GET", {"exposure": 123}, {"exposure": 123}),
            ("GAIN_SET", "GAIN_GET", {"gain": 45}, {"gain": 45}),
            ("BLKLVL_SET", "BLKLVL_GET", {"blacklevel": 6}, {"blacklevel": 6}),
            ("HBIN_SET", "HBIN_GET", {"hbin": 3}, {"hbin": 3}),
            ("VBIN_SET", "VBIN_GET", {"vbin": 2}, {"vbin": 2}),
            ("NFRAMES_SET", "NFRAMES_GET", {"nframes": 8}, {"nframes": 8}),
            ("ROI_SET", "ROI_GET", dict(left=1, top=2, right=300, bottom=400),
             dict(left=1, top=2, right=300, bottom=400)),
        ]:
            set_cmd, get_cmd = protocol[setter], protocol[getter]
            port.writeData(set_cmd.encode(**args))
            port.readString()
            port.writeData(get_cmd.encode())
            assert get_cmd.decode(port.readString()) == expected, setter


@pytest.fixture
def cam(frame):
    port = FakeCameraPort(image=frame[0])
    cam = KiraluxDevice(port=port)
    cam.open()
    yield cam
    cam.close()


class TestKiraluxDevice:
    def test_identity_comes_back_as_seeded(self, cam):
        assert cam.serial == 18658 and cam.model == "CS505MUP1"
        assert cam.sensor_size == (WIDTH, HEIGHT) and cam.bit_depth == 12
        assert cam.temperature == pytest.approx(29.0)
        assert repr(cam) == "<KiraluxDevice CS505MUP1 sn=18658>"

    @pytest.mark.parametrize("name, value", [
        ("exposure_us", 20_000), ("gain_db", 7), ("roi", (0, 0, 2447, 2047)), ("binning", (2, 2)),
    ])
    def test_settings_round_trip(self, cam, name, value):
        setattr(cam, name, value)
        assert getattr(cam, name) == value

    def test_prepare_capture_recognizes_the_whole_command_half(self, cam):
        del cam.port.sent[:]
        cam.prepare_capture(nframes=4, trigger="hi")
        assert cam.port.sent == ["stop", "hwtrig hi", "nframes 4", "arm"]

    def test_snap_returns_the_frame(self, cam, frame):
        f = cam.snap(exposure_us=5000)
        np.testing.assert_array_equal(np.asarray(f), frame[1])
        assert cam.exposure_us == 5000
        call, = cam.port.stream_calls
        assert call["timeout"] == 3000 and call["length"] == 16384 + WIDTH * HEIGHT * 3 // 2

    def test_snap_timeout_is_given_in_seconds(self, cam):
        cam.snap(timeout=1.5)
        assert cam.port.stream_calls[0]["timeout"] == 1500

    def test_open_stops_the_camera_and_close_leaves_an_injected_port_alone(self, cam):
        assert cam.port.sent[0] == "stop"
        cam.close()
        assert cam.port is not None

    def test_context_manager(self, frame):
        with KiraluxDevice(port=FakeCameraPort()) as c:
            assert c.serial == 18658

    @pytest.mark.parametrize("serial, wanted", [(".*", None), (None, None), ("18658", "18658")])
    def test_without_a_port_a_KiraluxPort_is_made_opened_and_closed(self, monkeypatch, serial, wanted):
        made = []

        class Stand(device.KiraluxPort):
            """A KiraluxPort whose USB side is a debug port answering from the description."""

            def __init__(self, serialNumber=None):
                super().__init__(serialNumber)          # builds locks only; nothing touches USB
                made.append(self)
                self.requestedSerial = serialNumber
                self.opened = self.closed = False
                self.debug = FakeCameraPort()

            def open(self):
                self.opened = True

            def close(self):
                self.closed = True

            def writeData(self, data, endPoint=None):
                return self.debug.writeData(data)

            def readString(self, endPoint=None):
                return self.debug.readString()

        monkeypatch.setattr(device, "KiraluxPort", Stand)
        c = KiraluxDevice(serialNumber=serial)
        c.open()
        port, = made
        assert port.requestedSerial == wanted and port.opened and c.serial == 18658
        c.close()
        assert port.closed
