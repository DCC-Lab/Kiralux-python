"""Fixtures and the ``hardware`` switch.

Everything runs with no camera, against a ``ProtocolDebugPort`` built from
``protocol.json``. Tests marked ``hardware`` (and the ``hardware`` flavour of the
``camera`` fixture) need a real Kiralux on USB: they run when one is found and
are skipped otherwise.

    pytest                  # auto: hardware tests run only if a camera is plugged in
    pytest --hardware       # fail loudly if no camera is found
    pytest --no-hardware    # never touch USB
"""
import pytest

from kiralux import KiraluxCameraDevice

from support import FakeCameraPort, frame_bytes


def pytest_addoption(parser):
    group = parser.getgroup("kiralux")
    group.addoption("--hardware", action="store_true", help="require a camera for the hardware tests")
    group.addoption("--no-hardware", action="store_true", help="skip the hardware tests")


def _camera_present() -> bool:
    try:
        return len(KiraluxCameraDevice.available()) > 0
    except Exception:           # no libusb, no permission, ...
        return False


def pytest_collection_modifyitems(config, items):
    if config.getoption("--no-hardware"):
        reason = "--no-hardware"
    elif config.getoption("--hardware") or _camera_present():
        return
    else:
        reason = "no Kiralux camera found on USB"
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def frame():
    """A random full-size frame: (wire bytes, the mosaic they encode)."""
    return frame_bytes()


@pytest.fixture
def port(frame):
    """A camera-less port: answers from the CommandDictionary and streams ``frame``."""
    return FakeCameraPort(image=frame[0])


@pytest.fixture
def mock_camera(port):
    """An initialized ``KiraluxCameraDevice`` on the debug port."""
    cam = KiraluxCameraDevice(port=port)
    cam.initializeDevice()
    yield cam
    cam.shutdownDevice()


@pytest.fixture(params=["mock", pytest.param("hardware", marks=pytest.mark.hardware)])
def camera(request, mock_camera):
    """The same contract, with and without a camera.

    ``mock`` is the debug-port camera; ``hardware`` is a real one, whose settings
    are put back as they were when the test is done.
    """
    if request.param == "mock":
        yield mock_camera
        return
    cam = KiraluxCameraDevice()
    cam.initializeDevice()
    saved = (cam.exposure_us, cam.gain_db, cam.black_level, cam.binning, cam.roi, cam.frame_count)
    try:
        yield cam
    finally:
        cam.exposure_us, cam.gain_db, cam.black_level = saved[:3]
        cam.binning, cam.roi, cam.frame_count = saved[3:]
        cam.shutdownDevice()
