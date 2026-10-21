"""Drive the Kiralux as a single PyHardwareLibrary CameraDevice.

Shows KiraluxCameraDevice end to end: the connection lifecycle / state machine,
capability introspection, both ways to set the exposure (direct property and the
notified+validated capability), a one-shot snap, and the inherited capture loop.

    python examples/camera_device_demo.py --exp 20000 --n 3
"""
import argparse

import numpy as np

from kiralux import KiraluxCameraDevice, ExposureCapability, GainCapability


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=int, default=20_000, help="exposure in microseconds")
    ap.add_argument("--gain", type=int, default=0, help="gain (0..480, tenths of a dB)")
    ap.add_argument("--n", type=int, default=3, help="frames to capture with the loop")
    args = ap.parse_args()

    print("connected:", KiraluxCameraDevice.available())

    with KiraluxCameraDevice() as cam:                 # initialize -> Ready, shutdown on exit
        print(repr(cam), "| state:", cam.state.name)
        print("capabilities:", [c.__name__ for c in cam.capabilities()])
        print("has exposure/gain:",
              cam.hasCapability(ExposureCapability), cam.hasCapability(GainCapability))
        print("sensor:", cam.sensor_size, "| bit depth:", cam.bit_depth,
              "| T:", cam.temperature, "C")

        cam.setExposure(args.exp)                      # notified + validated capability
        cam.setGain(args.gain)
        print("exposure:", cam.getExposure(), cam.unit, "| gain:", cam.getGain(), "dB")

        frame = cam.snap()                             # one-shot
        print("snap:", repr(frame), "| DoLP mean %.3f" % float(frame.dolp.mean()))

        for i, f in enumerate(cam.captureFrames(args.n)):   # inherited capture loop
            m = np.asarray(f).astype(int)
            vmed = float(np.median(np.abs(m[1:] - m[:-1])))
            print(f"  frame {i}: {f!r} vmed {vmed}")

    print("state after context:", cam.state.name)


if __name__ == "__main__":
    main()
