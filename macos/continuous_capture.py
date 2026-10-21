#!/usr/bin/env python3
"""Exemple d'acquisition continue avec la classe Kiralux.
Acquiert N frames en boucle (software trigger), mesure le FPS, sauve la derniere
intensite S0.
    python continuous_capture.py [--n 30] [--exp 10000]
"""
import argparse
import time
import numpy as np
from PIL import Image
from camera_usb import Kiralux


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="nombre de frames")
    ap.add_argument("--exp", type=int, default=10000, help="exposition en us")
    ap.add_argument("--out", default="live_S0.png")
    args = ap.parse_args()

    with Kiralux() as cam:
        info = cam.info()
        print(f"camera {info['sernum']}  {info['width']}x{info['height']}  {info['bit_depth']} bits")
        # pre-config une fois (la camera conserve exp/roi entre les grabs)
        cam.cmd("stop"); cam.cmd("roi 0 0 2447 2047"); cam.cmd("sfr off")
        cam.cmd(f"exp {args.exp}"); cam.cmd("hwtrig none"); cam.cmd("nframes 1")

        last = None
        t0 = time.monotonic()
        for i in range(args.n):
            mosaic = cam.grab(exposure_us=args.exp)   # reconfigure+arm+start+read
            last = mosaic
            if (i + 1) % 10 == 0:
                dt = time.monotonic() - t0
                print(f"  {i+1} frames  {(i+1)/dt:.1f} fps  (mean={mosaic.mean():.0f})")
        dt = time.monotonic() - t0

    print(f"total {args.n} frames en {dt:.2f}s = {args.n/dt:.1f} fps")
    s0 = Kiralux.polar_s0(last).astype(np.float32)
    p0, p1 = np.percentile(s0, [1, 99])
    d = np.clip((s0 - p0) / max(p1 - p0, 1) * 255, 0, 255).astype(np.uint8)
    Image.fromarray(d).save(args.out)
    print("->", args.out)


if __name__ == "__main__":
    main()
