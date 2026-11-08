"""Per-pixel AoLP rotation map from Kiralux capture(s) of a slide.

The sample (a thin brain slice) is only weakly and non-uniformly birefringent, so
the rotation it imparts on the polarization varies pixel by pixel and must be
mapped, not averaged away.

Averaging more frames of the SAME capture does not reduce this map's noise floor
much: most of it is fixed-pattern (the four analyser channels of each superpixel
don't have identical transmission/extinction, a manufacturing non-uniformity that
repeats identically every frame, so temporal averaging can't touch it). The fix is
a per-pixel reference captured once, with polarized illumination and NO sample in
the beam (--ref-frame): its AoLP map carries that same fixed pattern, and
subtracting it pixel-by-pixel cancels it everywhere, not just in one patch. Prefer
this over --ref-roi (a single angle from one region, extrapolated to the whole
frame, which cannot correct a pattern that varies pixel to pixel). The reference
illumination need not be perfectly polarized: AoLP = 0.5*atan2(S2, S1) does not
depend on DoLP, only on there being enough S1/S2 signal above noise -- this script
prints the reference's DoLP so you can confirm that is the case.

    python examples/birefringence_map.py slide.tiff --ref-frame reference_no_sample.tiff --out rotation
        -> per-pixel calibration (recommended)

    python examples/birefringence_map.py slide.tiff
        -> no reference frame: drag a rectangle over bare glass (no tissue), close the window

    python examples/birefringence_map.py slide.tiff --ref-roi 50,50,250,200 --out rotation
        -> same, without the interactive picker (reusable/scriptable)

Writes <out>.png (the map) and <out>.npy (the raw float32 degrees, same shape as
AoLP: half the mosaic's width and height). Pixels too dim to trust (S0 below
--min-s0, in either frame when --ref-frame is used) are masked out (gray),
excluded from stats.
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import TwoSlopeNorm
from matplotlib.patches import Rectangle
from matplotlib.widgets import RectangleSelector
from PIL import Image as PILImage

from kiralux import PolarFrame


def load_mosaic(path: str) -> np.ndarray:
    return np.asarray(PILImage.open(path), dtype=np.float32)


def wrap_deg180(delta: np.ndarray) -> np.ndarray:
    """AoLP is defined mod 180 deg; wrap a difference into [-90, 90)."""
    return (delta + 90.0) % 180.0 - 90.0


def pick_roi(s0: np.ndarray) -> tuple[int, int, int, int]:
    """Let the user drag a rectangle over the reference region; block until the window closes."""
    box = {}

    def onselect(eclick, erelease):
        x0, y0, x1, y1 = eclick.xdata, eclick.ydata, erelease.xdata, erelease.ydata
        box["coords"] = (int(round(min(x0, x1))), int(round(min(y0, y1))),
                          int(round(max(x0, x1))), int(round(max(y0, y1))))

    fig, ax = plt.subplots(figsize=(9, 7))
    ax.imshow(s0, cmap="gray", vmin=0, vmax=np.percentile(s0, 99.5))
    ax.set_title("Drag a rectangle over bare slide (no tissue), then close this window")
    ax.axis("off")
    selector = RectangleSelector(ax, onselect, useblit=True, button=[1], interactive=True,
                                  props=dict(facecolor="none", edgecolor="yellow", linewidth=1.5))
    plt.show()
    if "coords" not in box:
        raise SystemExit("no reference region selected")
    return box["coords"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slide", help="TIFF of the sample (+ bare slide, for --ref-roi)")
    ap.add_argument("--ref-frame", help="TIFF of the same FOV, same illumination, NO sample: per-pixel calibration")
    ap.add_argument("--ref-roi", help="x0,y0,x1,y1 in AoLP-map pixels (skips the interactive picker); ignored with --ref-frame")
    ap.add_argument("--out", default="rotation_map", help="output file prefix (writes <out>.png and <out>.npy)")
    ap.add_argument("--min-s0", type=float, default=200.0, help="mask pixels dimmer than this (16-bit ADU)")
    ap.add_argument("--clip", type=float, default=None, help="colorbar half-range in degrees (default: 99th percentile of |delta|)")
    args = ap.parse_args()

    frame = PolarFrame(load_mosaic(args.slide))
    s0, s1, s2 = frame.stokes
    roi_box = None

    if args.ref_frame:
        ref_frame = PolarFrame(load_mosaic(args.ref_frame))
        if ref_frame.shape != frame.shape:
            raise ValueError(f"shape mismatch: {args.ref_frame} is {ref_frame.shape}, {args.slide} is {frame.shape}")
        ref_valid = ref_frame.s0 >= args.min_s0
        print(f"reference frame {args.ref_frame}: DoLP mean {ref_frame.dolp[ref_valid].mean():.3f}  "
              f"5th pct {np.percentile(ref_frame.dolp[ref_valid], 5):.3f}  "
              f"(1.0 = fully polarized; low values make the per-pixel AoLP there noisier, not biased)")
        delta = wrap_deg180(frame.aolp - ref_frame.aolp)
        valid = (s0 >= args.min_s0) & ref_valid
    else:
        x0, y0, x1, y1 = (int(v) for v in args.ref_roi.split(",")) if args.ref_roi else pick_roi(s0)
        roi_box = (x0, y0, x1, y1)
        roi_valid = s0[y0:y1, x0:x1] >= args.min_s0
        if not roi_valid.any():
            raise SystemExit("reference ROI has no pixel above --min-s0; pick a brighter region")
        ref_s1 = s1[y0:y1, x0:x1][roi_valid].mean()
        ref_s2 = s2[y0:y1, x0:x1][roi_valid].mean()
        ref_angle = np.degrees(0.5 * np.arctan2(ref_s2, ref_s1))
        print(f"reference ROI ({x0},{y0})-({x1},{y1}): {roi_valid.sum()} px, AoLP = {ref_angle:+.4f} deg")
        delta = wrap_deg180(frame.aolp - ref_angle)
        valid = s0 >= args.min_s0

    masked = np.ma.masked_array(delta, mask=~valid)
    stats_region = delta[valid]
    print(f"valid pixels: {valid.sum()} / {valid.size} ({100 * valid.mean():.1f}%)")
    print(f"delta AoLP (deg) over whole frame: mean {stats_region.mean():+.4f}  median {np.median(stats_region):+.4f}  "
          f"std {stats_region.std():.4f}")

    clip = args.clip if args.clip is not None else np.percentile(np.abs(stats_region), 99)
    clip = max(clip, 1e-3)

    fig, ax = plt.subplots(figsize=(9, 7))
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad("lightgray")
    im = ax.imshow(masked, cmap=cmap, norm=TwoSlopeNorm(vmin=-clip, vcenter=0.0, vmax=clip))
    title = "AoLP rotation relative to bare-slide reference, per pixel"
    if roi_box is not None:
        x0, y0, x1, y1 = roi_box
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="black", linewidth=1.5))
        title = "AoLP rotation relative to bare-slide reference (outlined), per pixel"
    ax.set_title(title)
    ax.axis("off")
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Δ AoLP (deg)")
    fig.tight_layout()
    fig.savefig(f"{args.out}.png", dpi=150)
    np.save(f"{args.out}.npy", delta.astype(np.float32))
    print(f"wrote {args.out}.png and {args.out}.npy")
    plt.show()


if __name__ == "__main__":
    main()
