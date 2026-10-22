"""KiraluxCameraDevice with no camera: a ProtocolDebugPort built from protocol.json."""
import warnings

import numpy as np
import pytest
from notificationcenter.core import NotificationCenter
from hardwarelibrary.physicaldevice import PhysicalDevice, DeviceState
from hardwarelibrary.cameras.camera import CameraDeviceNotification

import kiralux.camera_device as camera_device
from kiralux import KiraluxCameraDevice, PolarFrame, Command
from support import FakeCameraPort, IDENTITY, WIDTH, HEIGHT


# --------------------------------------------------------------------------- #
#  lifecycle
# --------------------------------------------------------------------------- #
class TestLifecycle:
    def test_initialization_reaches_ready_and_reads_the_identity(self, mock_camera):
        assert mock_camera.state == DeviceState.Ready
        assert mock_camera.serial == 18658
        assert mock_camera.version == "CS505MUP1"
        assert repr(mock_camera) == "<KiraluxCameraDevice CS505MUP1 sn=18658>"

    def test_initialization_stops_any_running_acquisition_first(self, mock_camera, port):
        assert port.sent[0] == "stop"

    def test_context_manager_initializes_and_shuts_down(self, port):
        with KiraluxCameraDevice(port=port) as cam:
            assert cam.state == DeviceState.Ready
        assert cam.state != DeviceState.Ready
        assert cam.port is None
        assert port.isOpen is False

    def test_shutdown_closes_the_port(self, mock_camera, port):
        port.open()
        mock_camera.shutdownDevice()
        assert port.isOpen is False and mock_camera.port is None

    def test_a_device_that_does_not_answer_fails_to_initialize(self):
        class Silent(FakeCameraPort):
            def writeData(self, data, endPoint=None):
                raise IOError("no answer")
        cam = KiraluxCameraDevice(port=Silent())
        with pytest.raises(PhysicalDevice.UnableToInitialize):
            cam.initializeDevice()
        assert cam.state == DeviceState.Unrecognized

    @pytest.mark.parametrize("serial, wanted", [(None, None), (".*", None), ("18658", "18658")])
    def test_without_an_injected_port_a_KiraluxPort_is_opened(self, monkeypatch, frame, serial, wanted):
        made = []

        class Stand(FakeCameraPort):
            def __init__(self, serialNumber=None):
                super().__init__(image=frame[0])
                made.append(serialNumber)
        monkeypatch.setattr(camera_device, "KiraluxPort", Stand)
        cam = KiraluxCameraDevice(serialNumber=serial)
        cam.initializeDevice()
        assert made == [wanted]
        assert cam.imageEndPoint == camera_device.EP_IMAGE
        assert cam.port.isOpen
        cam.shutdownDevice()

    def test_identifiers(self):
        assert (KiraluxCameraDevice.classIdVendor, KiraluxCameraDevice.classIdProduct) == (0x1313, 0x4001)

    def test_available_lists_serials_of_connected_cameras(self, monkeypatch):
        class Dev:
            def __init__(self, serial):
                self._s = serial

            @property
            def serial_number(self):
                if self._s is None:
                    raise ValueError("no string descriptor")
                return self._s
        import usb.core
        seen = {}

        def find(**kw):
            seen.update(kw)
            return [Dev("18658\x00 "), Dev(None)]
        monkeypatch.setattr(usb.core, "find", find)
        assert KiraluxCameraDevice.available() == ["18658", None]
        assert seen == {"find_all": True, "idVendor": 0x1313, "idProduct": 0x4001}

    def test_available_is_empty_with_no_camera(self, monkeypatch):
        import usb.core
        monkeypatch.setattr(usb.core, "find", lambda **kw: [])
        assert KiraluxCameraDevice.available() == []


# --------------------------------------------------------------------------- #
#  firmware vocabulary
# --------------------------------------------------------------------------- #
class TestVocabulary:
    def test_matching_vocabulary_is_silent(self, port):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            KiraluxCameraDevice(port=port).initializeDevice()

    def test_drift_is_reported_both_ways_without_blocking(self):
        vocabulary = " ".join(c.value for c in Command if c is not Command.EXP) + " brandnew"
        port = FakeCameraPort(identity={**IDENTITY, "vocabulary": vocabulary})
        cam = KiraluxCameraDevice(port=port)
        with pytest.warns(UserWarning, match="drift") as record:
            cam.initializeDevice()
        text = str(record[0].message)
        assert "brandnew" in text and "exp" in text
        assert cam.state == DeviceState.Ready


# --------------------------------------------------------------------------- #
#  identity and settings (direct protocol properties)
# --------------------------------------------------------------------------- #
class TestProperties:
    def test_identity(self, mock_camera):
        assert mock_camera.sensor_size == (WIDTH, HEIGHT)
        assert mock_camera.bit_depth == 12
        assert mock_camera.temperature == 29.0
        assert mock_camera.polar_phase == 90

    @pytest.mark.parametrize("name, value", [
        ("exposure_us", 20_000), ("gain_db", 7), ("black_level", 8), ("frame_count", 3),
        ("binning", (2, 4)), ("roi", (0, 0, 2447, 2047)), ("roi", (5, 6, 700, 800)),
    ])
    def test_settings_round_trip(self, mock_camera, name, value):
        setattr(mock_camera, name, value)
        assert getattr(mock_camera, name) == value

    def test_floats_are_truncated_to_integers_for_the_wire(self, mock_camera):
        mock_camera.exposure_us = 1234.9
        assert mock_camera.exposure_us == 1234

    def test_commands_on_the_wire(self, mock_camera, port):
        del port.sent[:]
        mock_camera.exposure_us = 500
        mock_camera.binning = (2, 3)
        mock_camera.roi = (1, 2, 300, 400)
        mock_camera.gain_db = 9
        mock_camera.black_level = 4
        mock_camera.frame_count = 2
        assert port.sent == ["exp 500", "hbin 2", "vbin 3", "roi 1 2 300 400",
                             "gain 9", "blklvl 4", "nframes 2"]


# --------------------------------------------------------------------------- #
#  acquisition
# --------------------------------------------------------------------------- #
class TestAcquisition:
    def test_snap_returns_the_decoded_frame(self, mock_camera, frame):
        f = mock_camera.snap()
        assert isinstance(f, PolarFrame) and f.shape == (HEIGHT, WIDTH)
        np.testing.assert_array_equal(np.asarray(f), frame[1])

    def test_snap_runs_the_acquisition_dialog_in_order(self, mock_camera, port):
        del port.sent[:]
        mock_camera.snap()
        assert port.sent == ["stop", "hwtrig none", "nframes 1", "image_width", "image_height",
                             "arm", "start"]

    def test_the_following_snaps_only_arm_and_start(self, mock_camera, port):
        mock_camera.snap()
        del port.sent[:]
        mock_camera.snap()
        assert port.sent == ["arm", "start"]

    @pytest.mark.parametrize("change", [
        lambda cam: setattr(cam, "roi", (0, 0, 99, 99)),
        lambda cam: setattr(cam, "binning", (1, 1)),
        lambda cam: setattr(cam, "frame_count", 2)])
    def test_changing_the_geometry_or_frame_count_sets_the_mode_up_again(self, mock_camera, port, change):
        mock_camera.snap()
        change(mock_camera)
        del port.sent[:]
        mock_camera.snap()
        assert port.sent[:3] == ["stop", "hwtrig none", "nframes 1"]

    def test_shutdown_stops_a_camera_left_armed(self, mock_camera, port):
        mock_camera.snap()
        del port.sent[:]
        mock_camera.shutdownDevice()
        assert port.sent == ["stop"]

    def test_a_failed_read_stops_drains_and_sets_up_again(self, mock_camera, port, monkeypatch):
        mock_camera.snap()
        monkeypatch.setattr(port, "readStream", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
        with pytest.raises(TimeoutError):
            mock_camera.snap()
        assert mock_camera.frame_size is None and port.sent[-1] == "stop"

    def test_snap_reads_header_plus_packed_pixels_from_the_image_endpoint(self, mock_camera, port):
        mock_camera.snap()
        call, = port.stream_calls
        assert call["length"] == 16384 + WIDTH * HEIGHT * 3 // 2
        assert call["timeout"] == 3000

    def test_snap_with_exposure_sets_it_first(self, mock_camera, port):
        del port.sent[:]
        mock_camera.snap(exposure_us=7777)
        assert port.sent[0] == "exp 7777" and mock_camera.exposure_us == 7777

    def test_snap_follows_the_sensor_size_the_camera_reports(self, mock_camera, port):
        from support import frame_bytes
        data, mosaic = frame_bytes(64, 32, seed=9)
        port.image = data
        port.values.update(width=64, height=32)
        np.testing.assert_array_equal(np.asarray(mock_camera.snap()), mosaic)

    def test_a_short_stream_is_padded_with_zeros(self, mock_camera, port):
        port.image = port.image[: 16384 + 1000]
        f = mock_camera.snap()
        assert f.shape == (HEIGHT, WIDTH) and (np.asarray(f)[-1] == 0).all()

    def test_captureFrames_takes_n_snapshots(self, mock_camera, port):
        frames = mock_camera.captureFrames(3)
        assert len(frames) == 3 and len(port.stream_calls) == 3

    def test_the_capture_thread_loop_posts_each_frame(self, mock_camera):
        got = []
        NotificationCenter().add_observer(
            got, lambda n: got.append(n.user_info), CameraDeviceNotification.imageCaptured, mock_camera)
        mock_camera.quitLoop = True            # one pass, then leave
        mock_camera.captureLoopThread()
        assert len(got) == 1

    def test_shutdown_while_not_capturing_is_harmless(self, mock_camera):
        assert not mock_camera.isCapturing
        mock_camera.shutdownDevice()


class TestDrainImageEndpoint:
    def test_stops_when_the_pipe_is_empty(self):
        from kiralux.camera_device import drain_image_endpoint
        port = FakeCameraPort()                          # not streaming: every read times out
        drain_image_endpoint(port, 0x83)
        assert port.stream_calls == []

    def test_is_bounded_when_the_pipe_never_empties(self):
        from kiralux.camera_device import drain_image_endpoint
        port = FakeCameraPort(image=bytes(16384))
        port.streaming = True
        drain_image_endpoint(port, 0x83, limit=5)
        assert len(port.stream_calls) == 5
