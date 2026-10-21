#!/usr/bin/env python3
"""Acquire a burst of frames in a loop and report the achieved frame rate.

    python continuous_capture.py [--n 30] [--exp US]
"""
import argparse
import time

import numpy as np
from PIL import Image

from kiralux import Kiralux


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="number of frames")
    ap.add_argument("--exp", type=int, default=10000, help="exposure in microseconds")
    ap.add_argument("--out", default="live_S0.png")
    args = ap.parse_args()

    with Kiralux() as cam:
        print(cam, "|", "x".join(map(str, cam.sensor_size)), "|", cam.bit_depth, "bit")
        cam.reset_roi()
        cam.exposure_us = args.exp

        last, t0 = None, time.monotonic()
        for i in range(args.n):
            last = cam.snap()
            if (i + 1) % 10 == 0:
                print(f"  {i + 1:3d} frames   {(i + 1) / (time.monotonic() - t0):.1f} fps")
        fps = args.n / (time.monotonic() - t0)

    print(f"{args.n} frames in {args.n / fps:.2f} s = {fps:.1f} fps")
    lo, hi = np.percentile(last.s0, [1, 99])
    Image.fromarray(np.clip((last.s0 - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)).save(args.out)
    print("->", args.out)


if __name__ == "__main__":
    main()
