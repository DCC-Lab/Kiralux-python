"""Invert AoLP/DoLP into retardance (birefringence) and axis, for a capture taken under
QWP circular illumination (polarizer + achromatic quarter-wave plate at 45 deg before the
sample).

Model: ideal linear retarder, fast axis alpha, retardance delta. On a purely circular
input (p=1), its Mueller matrix gives:

    DoLP_out = |sin(delta)|          (first order in delta -- this is the whole point
                                       of adding the QWP: no more delta^2 suppression)
    AoLP_out = alpha + 45 deg (mod 90 deg)

Inversion used here:

    delta = arcsin(DoLP)   (deg, principal branch 0..90 -- valid for a weakly
                             birefringent sample; ambiguous with 180-delta beyond that)
    alpha = AoLP - 45 deg (mod 90 deg)   (fast vs slow axis not resolved: linear-Stokes-
                                           only measurement, same limitation as before)

p (illumination circularity, degree of polarization of the QWP-converted beam) defaults
to 1 here, which is an idealization: a real polarizer/QWP is never perfect, so p=1
UNDERESTIMATES delta. Pass --p to use a measured value instead.

How to measure p (alignment-insensitive, does the lamp/polarizer/QWP stay untouched):
swap the sample for a retarder of KNOWN retardance delta_cal (orientation does not
matter: DoLP_out = p*sin(delta) depends only on the magnitude of delta, not its axis),
capture it through the same illumination optics, then p = DoLP_measured / sin(delta_cal).

--ref lets you also invert the no-sample reference the same way and shows
delta_sample - delta_ref, a crude but honest way to see what's attributable to the
sample rather than to the optics/illumination themselves.

    python examples/retardance_qwp.py Slide-QWP-sample3-avg500.tiff
    python examples/retardance_qwp.py Slide-QWP-sample3-avg500.tiff --ref Reference-QWP2-avg500.tiff --p 0.97
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from PIL import Image as PILImage

from kiralux import PolarFrame

MIN_S0 = 100.0


def load(path):
    return PolarFrame(np.asarray(PILImage.open(path), dtype=np.float32))


def invert_qwp(frame, min_s0=MIN_S0, p=1.0):
    """delta (deg, arcsin(DoLP/p)), axis (deg, mod 90), valid mask."""
    valid = frame.s0 >= min_s0
    delta_deg = np.degrees(np.arcsin(np.clip(frame.dolp / p, 0, 1)))
    axis_deg = np.mod(frame.aolp - 45.0, 90.0)
    return delta_deg, axis_deg, valid


def unwrapped_direction_lines(axis_deg, color_by, valid, step=12, min_frac_valid=0.3):
    """Grid of short line segments for the axis field, continuity-unwrapped (mod 90 deg
    has no natural "closest to zero" representative; jumping between 1 deg and 89 deg for
    a 2 deg real change looks like noise unless each cell picks the branch closest to its
    already-unwrapped neighbor)."""
    H, W = axis_deg.shape
    rad4 = np.radians(axis_deg) * 4
    gy_range = list(range(0, H - step, step))
    gx_range = list(range(0, W - step, step))
    nrows, ncols = len(gy_range), len(gx_range)

    grid_angle = np.full((nrows, ncols), np.nan)
    grid_color = np.full((nrows, ncols), np.nan)
    for i, gy in enumerate(gy_range):
        for j, gx in enumerate(gx_range):
            block_valid = valid[gy:gy + step, gx:gx + step]
            if block_valid.mean() < min_frac_valid:
                continue
            block_rad4 = rad4[gy:gy + step, gx:gx + step][block_valid]
            mean_vec = np.exp(1j * block_rad4).mean()
            grid_angle[i, j] = (np.degrees(np.angle(mean_vec)) / 4) % 90
            grid_color[i, j] = color_by[gy:gy + step, gx:gx + step][block_valid].mean()

    unwrapped = np.full_like(grid_angle, np.nan)
    for i in range(nrows):
        for j in range(ncols):
            a = grid_angle[i, j]
            if np.isnan(a):
                continue
            candidates = [a - 90, a, a + 90]
            ref = None
            if j > 0 and not np.isnan(unwrapped[i, j - 1]):
                ref = unwrapped[i, j - 1]
            elif i > 0 and not np.isnan(unwrapped[i - 1, j]):
                ref = unwrapped[i - 1, j]
            unwrapped[i, j] = a if ref is None else min(candidates, key=lambda c: abs(c - ref))

    segs, colors = [], []
    half = step * 0.65
    for i, gy in enumerate(gy_range):
        for j, gx in enumerate(gx_range):
            a = unwrapped[i, j]
            if np.isnan(a):
                continue
            theta = np.radians(a)
            ux, uy = np.cos(theta), np.sin(theta)
            xc, yc = gx + step / 2, gy + step / 2
            segs.append([(xc - half * ux, yc - half * uy), (xc + half * ux, yc + half * uy)])
            colors.append(grid_color[i, j])
    return segs, np.array(colors)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sample")
    ap.add_argument("--ref", help="no-sample QWP reference, same FOV")
    ap.add_argument("--p", type=float, default=1.0,
                     help="measured illumination circularity (degree of polarization), "
                          "from a known-retarder calibration shot; default 1.0 (idealized)")
    ap.add_argument("--out", default="retardance_qwp")
    args = ap.parse_args()

    sample = load(args.sample)
    delta_deg, axis_deg, valid = invert_qwp(sample, p=args.p)
    d = delta_deg[valid]
    print(f"sample: valid {valid.sum()}/{valid.size}  delta (deg, p={args.p}): "
          f"mean {d.mean():.4f}  median {np.median(d):.4f}  std {d.std():.4f}")

    color_by = delta_deg
    if args.ref:
        ref = load(args.ref)
        ref_delta_deg, _, ref_valid = invert_qwp(ref, p=args.p)
        both_valid = valid & ref_valid
        diff = (delta_deg - ref_delta_deg)[both_valid]
        print(f"reference: delta (deg, p={args.p}): mean {ref_delta_deg[ref_valid].mean():.4f}  "
              f"median {np.median(ref_delta_deg[ref_valid]):.4f}")
        print(f"sample - reference: mean {diff.mean():+.4f}  median {np.median(diff):+.4f}  std {diff.std():.4f} deg")

    fig, axs = plt.subplots(1, 2, figsize=(16, 8), facecolor="black")
    for ax in axs:
        ax.set_facecolor("black")

    masked_delta = np.ma.masked_array(delta_deg, mask=~valid)
    vmax = np.percentile(d, 99)
    im0 = axs[0].imshow(masked_delta, cmap="inferno", vmin=0, vmax=vmax)
    axs[0].set_title(f"Retardance |delta| = arcsin(DoLP/p), p={args.p} (deg)\nmedian {np.median(d):.3f} deg", color="white")
    cbar0 = fig.colorbar(im0, ax=axs[0], fraction=0.046, pad=0.04)
    cbar0.ax.yaxis.set_tick_params(color="white")
    plt.setp(plt.getp(cbar0.ax.axes, 'yticklabels'), color="white")

    segs, colors = unwrapped_direction_lines(axis_deg, color_by, valid)
    bg = np.ma.masked_array(delta_deg, mask=~valid)
    axs[1].imshow(bg, cmap="gray", vmin=0, vmax=vmax, alpha=0.5)
    lc = LineCollection(segs, array=colors, cmap="inferno", norm=plt.Normalize(0, vmax), linewidths=1.3)
    axs[1].add_collection(lc)
    axs[1].set_title("Axis (alpha = AoLP - 45 deg, mod 90), colored by delta", color="white")

    for ax in axs:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(f"{args.out}.png", dpi=150, facecolor="black")
    np.save(f"{args.out}_delta.npy", delta_deg.astype(np.float32))
    np.save(f"{args.out}_axis.npy", axis_deg.astype(np.float32))
    print(f"wrote {args.out}.png, {args.out}_delta.npy, {args.out}_axis.npy")


if __name__ == "__main__":
    main()
