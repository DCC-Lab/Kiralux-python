# kiralux

**100% Python** control of the **ThorLabs Kiralux CS505MUP1** camera (5 MP,
monochrome **polarization** CMOS, Sony IMX250MZR) on **macOS/Linux**, with **no
ThorLabs native libraries**. USB transport goes through the `USBPort` class of
[DCC-Lab/PyHardwareLibrary](https://github.com/DCC-Lab/PyHardwareLibrary).

Built by reverse-engineering the camera's USB protocol (interoperability) — the
full approach and the decoding tools are in
[`protocol-analysis/`](protocol-analysis/METHODOLOGY.md).

## Installation

```bash
pip install kiralux                 # pulls in hardwarelibrary + numpy
# or, from source:
pip install git+https://github.com/DCC-Lab/Kiralux-python
```

libusb is required at runtime (`pip` installs it via pyusb on most platforms). If
needed: `brew install libusb` (macOS) / `dnf|apt install libusb-1.0` (Linux). On
macOS with a non-standard brew prefix:

```bash
export DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib
```

The camera must be connected directly to the machine (detached from any VM).

## Quick start

```python
from kiralux import Kiralux

with Kiralux() as cam:                  # or Kiralux(serial="18658")
    cam.exposure_us = 20_000            # properties stay in sync with the camera
    cam.gain_db     = 0
    cam.roi         = (0, 0, 2447, 2047)
    cam.binning     = (1, 1)
    print(cam.model, cam.serial, cam.temperature)

    frame = cam.snap()                  # -> PolarFrame (2048 x 2448 uint16)
    frame.s0            # total intensity (Stokes S0), half-resolution
    frame.dolp          # degree of linear polarization   0..1
    frame.aolp          # angle of linear polarization     -90..90 deg
    frame.stokes        # (S0, S1, S2)
    frame.channels      # (I0, I45, I90, I135)
    frame.falsecolor    # HSV composite (hue=AoLP, sat=DoLP, value=S0) -> RGB

Kiralux.available()                     # serial numbers of connected cameras
```

The polarimetric views are computed **lazily** and cached.

```bash
python examples/polar_demo.py --exp 40000     # S0, DoLP, AoLP, false color
python examples/continuous_capture.py --n 30  # capture loop + FPS
# (the examples write PNGs:  pip install "kiralux[examples]")
```

## Three ways to drive the camera

All depend only on `hardwarelibrary` + `numpy`.

| Class | Import | What for |
|---|---|---|
| **`Kiralux`** | `from kiralux import Kiralux` | The direct, simple driver. `snap()` -> `PolarFrame`. **Start here.** |
| **`KiraluxDevice`** | `from kiralux import KiraluxDevice` | Same camera, vocabulary described by a PyHardwareLibrary `CommandDictionary`. Comes with a **hardware-free mock** (see [`tests/`](tests/)). |
| **`KiraluxCamera`** | `from kiralux import KiraluxCamera` | PyHardwareLibrary `CameraDevice` adapter: state machine, notifications, capture loop, capability introspection. |

The choice between `Kiralux` (simple) and `KiraluxDevice` (CommandDictionary) is
discussed in PR #2: for local single-camera use, `Kiralux` is enough; the
`CommandDictionary` pays off for hardware-free testing / CI.

## The protocol in brief

USB vendor interface (class `0xFF`), 5 bulk endpoints. **ASCII text** protocol,
self-documenting (`discover`, `<cmd>.disc`):

- `0x02` OUT: ASCII commands (1024-byte buffer, `\0`-terminated)
- `0x82` IN : ASCII responses
- `0x83` IN : image data (16384-byte header + **12-bit packed Mono12p** pixels)

Sequence: `stop -> exp <us> -> hwtrig none -> nframes 1 -> arm -> start -> [read 0x83] -> stop`.

**Two keys** to a clean image at ~95 MB/s (see
[`protocol-analysis/METHODOLOGY.md`](protocol-analysis/METHODOLOGY.md)): read
endpoint `0x83` in **16384-byte transfers** (otherwise ~1 MB/s), and **decode each
16384-byte block independently** (12-bit triplets do not cross block boundaries —
this was the cause of the striping).

## Layout

```
kiralux/                 the distributable package (the driver)
  camera.py              Kiralux class + PolarFrame
  device.py              KiraluxDevice + KiraluxPort (CommandDictionary variant)
  phl.py                 KiraluxCamera (PyHardwareLibrary CameraDevice adapter)
  protocol.json          command vocabulary (CommandDictionary)
examples/                polar_demo.py, continuous_capture.py
tests/                   test_command_dictionary.py (runs with no camera, via a mock)
protocol-analysis/       the reverse-engineering approach + the decoding tools
  METHODOLOGY.md         how the protocol was decoded (concise)
  REPORT.html, docs/, captures/, tools/
pyproject.toml           modern packaging (depends on hardwarelibrary>=2.2.0)
```

## License / note

Interoperability project to control hardware we own, under the
[MIT](LICENSE) license. ThorLabs proprietary binaries and source are not
redistributed here. ThorLabs, Kiralux and CS505MUP1 are trademarks of Thorlabs, Inc.
