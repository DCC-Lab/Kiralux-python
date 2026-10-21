#!/usr/bin/env python3
"""Acquire one frame and save intensity, DoLP, AoLP and an HSV false-color map.

    python polar_demo.py [--exp US]
"""
import argparse

import numpy as np
from PIL import Image

from kiralux import Kiralux


def stretch(a, lo=1, hi=99):
    a = np.asarray(a, np.float32)
    p0, p1 = np.percentile(a, [lo, hi])
    return np.clip((a - p0) / max(p1 - p0, 1e-6) * 255, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=int, default=40000, help="exposure in microseconds")
    args = ap.parse_args()

    with Kiralux() as cam:
        print(cam, "| T =", cam.temperature, "C")
        frame = cam.snap(exposure_us=args.exp)

    Image.fromarray(stretch(frame.s0)).save("polar_S0.png")
    Image.fromarray((np.clip(frame.dolp, 0, 1) * 255).astype(np.uint8)).save("polar_DoLP.png")
    Image.fromarray(stretch(frame.aolp)).save("polar_AoLP.png")
    Image.fromarray(frame.falsecolor, "RGB").save("polar_falsecolor.png")
    print(f"DoLP mean {frame.dolp.mean():.3f}  |  AoLP range "
          f"[{frame.aolp.min():.0f}, {frame.aolp.max():.0f}] deg")
    print("-> polar_S0.png  polar_DoLP.png  polar_AoLP.png  polar_falsecolor.png")


if __name__ == "__main__":
    main()
