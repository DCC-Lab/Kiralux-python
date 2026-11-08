"""Capture a single slide image (optionally averaged over many frames) and save it
as a 16-bit TIFF raw mosaic, in the same scale as preview_mytk_channels.py's
"Save as..." (12-bit ADU stretched to the full 16-bit range), so it feeds directly
into birefringence_map.py.

For --n > 1, frames are streamed (armed once, back to back: ~110 ms/frame instead
of the ~410+ ms/frame of re-arming for every single shot) and accumulated into one
running float32 sum -- constant memory, regardless of --n (never a list of N full
frames: at ~20 MB/frame, 1000 of them would be ~20 GB).

    python examples/capture_slide.py --exp 20000 --out ~/Desktop/Kiralux-test/Slide-001.tiff
    python examples/capture_slide.py --exp 350 --n 1000 --out slide_avg1000.tiff
"""
import argparse
import time

import numpy as np
from PIL import Image as PILImage

from kiralux import KiraluxCameraDevice

FULL_12_BIT, FULL_16_BIT = 4095, 65535


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp", type=int, default=20_000, help="exposure in microseconds")
    ap.add_argument("--n", type=int, default=1, help="number of raw frames to average (default: 1, a true single shot)")
    ap.add_argument("--out", required=True, help="output TIFF path")
    args = ap.parse_args()

    with KiraluxCameraDevice() as cam:
        cam.setExposure(args.exp)
        print(f"{cam}  |  exposure {args.exp} us  |  averaging {args.n} frame(s)", flush=True)

        start = time.perf_counter()
        total = None
        streaming = args.n > 1
        if streaming:
            cam.startStreaming()
        try:
            for i in range(args.n):
                mosaic = np.asarray(cam.snap().mosaic, dtype=np.float32)
                total = mosaic if total is None else total + mosaic
                if streaming and args.n >= 20 and (i + 1) % (args.n // 10) == 0:
                    print(f"  {i + 1}/{args.n} frames", flush=True)
        finally:
            if streaming:
                cam.stopStreaming()
    elapsed = time.perf_counter() - start

    average = total / args.n
    saturated = (average >= FULL_12_BIT - 1).mean() * 100
    print(f"captured {args.n} frame(s) in {elapsed:.1f}s ({1000 * elapsed / args.n:.0f} ms/frame)", flush=True)
    print(f"raw ADU: mean {average.mean():.1f}  max {average.max():.0f} / {FULL_12_BIT}  "
          f"({saturated:.2f}% of pixels at/near saturation)", flush=True)
    if saturated > 0.1:
        print("WARNING: significant saturation -- lower --exp", flush=True)

    PILImage.fromarray(np.rint(average * (FULL_16_BIT / FULL_12_BIT)).astype(np.uint16)).save(args.out)
    print(f"wrote {args.out}", flush=True)


if __name__ == "__main__":
    main()
