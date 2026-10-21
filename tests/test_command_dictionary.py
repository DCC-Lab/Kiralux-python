"""Exercise the Kiralux CommandDictionary with no camera attached.

``ProtocolDebugPort`` stands in for the instrument using the *same* description
the real driver sends with: a request's values are remembered by name, and a
reply answers from that memory. So setting the exposure and reading it back
returns what was set, and the read-only identity values are whatever we seed.

Run it anywhere:  python macos/test_command_dictionary.py
"""
from hardwarelibrary.communication.protocol import CommandDictionary
from hardwarelibrary.communication.debugport import ProtocolDebugPort

from kiralux.device import KiraluxDevice, PROTOCOL_PATH


def mock_camera():
    """A KiraluxDevice backed by a ProtocolDebugPort, with identity pre-seeded."""
    protocol = CommandDictionary.fromFile(PROTOCOL_PATH)
    port = ProtocolDebugPort(protocol)
    port.values.update({"serial": 18658, "model": "CS505MUP1",
                        "width": 2448, "height": 2048, "depth": 12,
                        "temperature": 31.5})
    cam = KiraluxDevice(port=port)
    cam.protocol = protocol
    cam.open()
    return cam


def main():
    # 1. The description is internally consistent (every command round-trips a specimen).
    CommandDictionary.fromFile(PROTOCOL_PATH).validate()
    print("validate(): OK — all", len(CommandDictionary.fromFile(PROTOCOL_PATH).names), "commands consistent")

    cam = mock_camera()

    # 2. Read-only identity comes back as seeded.
    assert cam.serial == 18658, cam.serial
    assert cam.model == "CS505MUP1", cam.model
    assert cam.sensor_size == (2448, 2048), cam.sensor_size
    assert cam.bit_depth == 12, cam.bit_depth
    assert abs(cam.temperature - 31.5) < 1e-6, cam.temperature
    print("identity   :", cam.serial, cam.model, cam.sensor_size, cam.bit_depth, cam.temperature, "C")

    # 3. Settings round-trip through the mock's memory.
    cam.exposure_us = 20_000
    assert cam.exposure_us == 20_000, cam.exposure_us
    cam.gain_db = 7
    assert cam.gain_db == 7, cam.gain_db
    cam.roi = (0, 0, 2447, 2047)
    assert cam.roi == (0, 0, 2447, 2047), cam.roi
    cam.binning = (2, 2)
    assert cam.binning == (2, 2), cam.binning
    print("settings   : exp", cam.exposure_us, "gain", cam.gain_db,
          "roi", cam.roi, "binning", cam.binning)

    # 4. The command half of an acquisition recognizes end to end.
    cam.prepare_capture(nframes=1, trigger="none")
    print("prepare_capture: stop/hwtrig/nframes/arm all recognized")

    cam.close()
    print("\nALL TESTS PASSED (no camera required)")


if __name__ == "__main__":
    main()
