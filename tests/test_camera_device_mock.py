"""Drive the full KiraluxCameraDevice with no camera attached.

Because the device now speaks its protocol through the same ``CommandDictionary``
as ``KiraluxDevice``, a ``ProtocolDebugPort`` can stand in for the camera: every
capability's get/set round-trips through the mock, and the read-only values are
whatever we seed. This exercises the whole CameraDevice command/capability layer
on any machine (the image read on EP 0x83 is the only part that needs hardware).

Run it anywhere:  python tests/test_camera_device_mock.py
"""
from hardwarelibrary.communication.protocol import CommandDictionary
from hardwarelibrary.communication.debugport import ProtocolDebugPort

from kiralux import KiraluxCameraDevice, Command
from kiralux.device import PROTOCOL_PATH


def mock_camera():
    """A KiraluxCameraDevice backed by a ProtocolDebugPort, identity pre-seeded."""
    protocol = CommandDictionary.fromFile(PROTOCOL_PATH)
    port = ProtocolDebugPort(protocol)
    port.values.update({"serial": 18658, "model": "CS505MUP1",
                        "width": 2448, "height": 2048, "depth": 12,
                        "temperature": 29.0, "phase": 90,
                        "vocabulary": " ".join(c.value for c in Command)})
    cam = KiraluxCameraDevice(port=port)
    cam.protocol = protocol
    cam.initializeDevice()
    return cam


def main():
    cam = mock_camera()
    print("state:", cam.state.name, "|", repr(cam))
    assert cam.state.name == "Ready", cam.state.name

    # read-only identity comes back as seeded
    assert cam.serial == 18658, cam.serial
    assert cam.version == "CS505MUP1", cam.version
    assert cam.sensor_size == (2448, 2048), cam.sensor_size
    assert cam.bit_depth == 12, cam.bit_depth
    assert cam.getTemperature() == 29.0, cam.getTemperature()
    assert cam.getPolarizationPhase() == 90, cam.getPolarizationPhase()

    # every settable capability round-trips through the mock's memory
    cam.setExposure(12_345);                 assert cam.getExposure() == 12_345
    cam.setGain(7);                          assert cam.getGain() == 7
    cam.setBlackLevel(8);                    assert cam.getBlackLevel() == 8
    cam.setBinning((2, 2));                  assert cam.getBinning() == (2, 2)
    cam.setRegionOfInterest((0, 0, 2447, 2047)); assert cam.getRegionOfInterest() == (0, 0, 2447, 2047)
    cam.setFrameCount(3);                    assert cam.getFrameCount() == 3
    print("capabilities round-tripped:", [c.__name__ for c in cam.capabilities()])

    # validation still refuses out-of-range values (nothing posted, nothing set)
    for call, arg in [(cam.setGain, 500), (cam.setBlackLevel, 9000), (cam.setBinning, (0, 1))]:
        try:
            call(arg)
            raise AssertionError(f"{call.__name__}({arg}) should have raised")
        except ValueError:
            pass
    print("out-of-range values rejected by validation")

    cam.shutdownDevice()
    print("\nALL CAMERA-DEVICE MOCK TESTS PASSED (no camera required)")


if __name__ == "__main__":
    main()
