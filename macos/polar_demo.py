#!/usr/bin/env python3
"""Demo polarisation : acquiert une frame et sauve S0, DoLP, AoLP, fausse couleur.
    python polar_demo.py [--exp us]
"""
import argparse
import numpy as np
from PIL import Image
from camera_usb import Kiralux

def norm8(a, lo=1, hi=99):
    a = a.astype(np.float32)
    p0, p1 = np.percentile(a, [lo, hi])
    return np.clip((a - p0) / max(p1 - p0, 1e-6) * 255, 0, 255).astype(np.uint8)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=int, default=20000)
    args = ap.parse_args()
    with Kiralux() as cam:
        print("infos:", cam.info())
        mosaic = cam.grab(exposure_us=args.exp)
    print("mosaique", mosaic.shape)

    S0 = Kiralux.polar_s0(mosaic)
    dolp = Kiralux.polar_dolp(mosaic)
    aolp = Kiralux.polar_aolp(mosaic)           # -90..90 deg
    fc = Kiralux.polar_falsecolor(mosaic)

    Image.fromarray(norm8(S0)).save("polar_S0.png")
    # DoLP en 0..1 -> 0..255 (pas de percentile, echelle physique)
    Image.fromarray((np.clip(dolp, 0, 1) * 255).astype(np.uint8)).save("polar_DoLP.png")
    # AoLP -90..90 -> teinte cyclique
    Image.fromarray(norm8(aolp)).save("polar_AoLP.png")
    Image.fromarray(fc, "RGB").save("polar_falsecolor.png")
    print("DoLP: min=%.3f max=%.3f mean=%.3f" % (dolp.min(), dolp.max(), dolp.mean()))
    print("AoLP: min=%.1f max=%.1f deg" % (aolp.min(), aolp.max()))
    print("-> polar_S0.png  polar_DoLP.png  polar_AoLP.png  polar_falsecolor.png")

if __name__ == "__main__":
    main()
