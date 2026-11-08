"""Continuous fiber-orientation visualization via Line Integral Convolution (LIC),
colored by retardance -- the "DTI-color-FA-like" rendering discussed earlier.

Why LIC and not matplotlib.streamplot: our axis field is undirected (known only mod 90
deg -- the fast/slow sign is not recoverable from a linear-Stokes-only measurement), so
there is no globally consistent "positive direction" to feed a true vector-field
streamline integrator. LIC does not need one: at every pixel it convolves white noise
along the LOCAL line (forward and backward are symmetric), so the sign ambiguity never
enters.

The axis field still has to be made locally continuous first (the raw mod-90 value jumps
every time the true axis crosses a multiple of 90 deg, same branch-cut problem as the
discrete line plot earlier tonight -- fixed there by unwrapping on a coarse grid). Here
that unwrapped coarse grid is upsampled (scipy.ndimage.zoom) to full resolution to build
a smooth per-pixel direction field before LIC runs on it.

    python examples/lic_fiber_map.py retardance_qwp_sample3 --sample Slide-QWP-sample3-avg500.tiff

(expects <prefix>_axis.npy and <prefix>_delta.npy from retardance_qwp.py; --sample is the
TIFF used to rebuild the S0 mask)
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image as PILImage
from scipy.ndimage import map_coordinates, zoom

from kiralux import PolarFrame

MIN_S0 = 100.0
MIN_DOLP = 0.08   # below this, axis is essentially noise (no resolvable retardance) -- excluding
                  # it matters even more here than for the discrete line plot: the unwrap step
                  # otherwise "integrates" noise and drifts into long, fake coherent streaks


def unwrap_coarse_grid(axis_deg, valid, step=8, min_frac_valid=0.3):
    """Circular-mean axis per grid cell (mod 90), then neighbor-continuity unwrapped
    (choose, for each cell, whichever of {a-90, a, a+90} is closest to an already-
    unwrapped neighbor). Returns the unwrapped grid (NaN where invalid) and its (y, x)
    cell-center coordinates.
    """
    H, W = axis_deg.shape
    rad4 = np.radians(axis_deg) * 4
    gy_range = list(range(0, H - step, step))
    gx_range = list(range(0, W - step, step))
    nrows, ncols = len(gy_range), len(gx_range)

    grid_angle = np.full((nrows, ncols), np.nan)
    for i, gy in enumerate(gy_range):
        for j, gx in enumerate(gx_range):
            block_valid = valid[gy:gy + step, gx:gx + step]
            if block_valid.mean() < min_frac_valid:
                continue
            block_rad4 = rad4[gy:gy + step, gx:gx + step][block_valid]
            mean_vec = np.exp(1j * block_rad4).mean()
            grid_angle[i, j] = (np.degrees(np.angle(mean_vec)) / 4) % 90

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

    # fill NaN holes (nearest valid neighbor) so zoom() doesn't propagate NaNs everywhere
    if np.isnan(unwrapped).any():
        yy, xx = np.indices(unwrapped.shape)
        good = ~np.isnan(unwrapped)
        if good.any():
            from scipy.interpolate import NearestNDInterpolator
            filler = NearestNDInterpolator(np.c_[yy[good], xx[good]], unwrapped[good])
            unwrapped = np.where(good, unwrapped, filler(yy, xx))
    return unwrapped


def line_integral_convolution(ux, uy, noise, length=18, step=1.0):
    """Classic LIC: average noise sampled along the local (symmetric, undirected) field
    line through each pixel, forward and backward, `length` steps each way."""
    H, W = noise.shape
    y0, x0 = np.indices((H, W), dtype=np.float32)
    acc = noise.copy()
    count = np.ones_like(noise)

    for sign in (1.0, -1.0):
        px, py = x0.copy(), y0.copy()
        for _ in range(length):
            cx = np.clip(px, 0, W - 1)
            cy = np.clip(py, 0, H - 1)
            acc += map_coordinates(noise, [cy, cx], order=1, mode="nearest")
            count += 1
            local_ux = map_coordinates(ux, [cy, cx], order=1, mode="nearest")
            local_uy = map_coordinates(uy, [cy, cx], order=1, mode="nearest")
            px += sign * step * local_ux
            py += sign * step * local_uy
    return acc / count


def hsv_to_rgb(h, s, v):
    h6 = (h % 1.0) * 6.0
    c = v * s
    x = c * (1 - np.abs(h6 % 2 - 1))
    z = np.zeros_like(c)
    i = h6.astype(int) % 6
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [c, x, z, z, x, c])
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [x, c, c, x, z, z])
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4, i == 5], [z, z, x, c, c, x])
    m = v - c
    return np.clip(np.dstack([r + m, g + m, b + m]), 0, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prefix", help="prefix of <prefix>_axis.npy / <prefix>_delta.npy from retardance_qwp.py")
    ap.add_argument("--sample", required=True, help="the sample TIFF (for the S0 mask)")
    ap.add_argument("--grid-step", type=int, default=8, help="coarse grid for unwrapping (px)")
    ap.add_argument("--lic-length", type=int, default=18, help="LIC steps each direction (px)")
    ap.add_argument("--out", default="lic_fiber_map")
    args = ap.parse_args()

    axis_deg = np.load(f"{args.prefix}_axis.npy")
    delta_deg = np.load(f"{args.prefix}_delta.npy")
    frame = PolarFrame(np.asarray(PILImage.open(args.sample), dtype=np.float32))
    valid = (frame.s0 >= MIN_S0) & (frame.dolp >= MIN_DOLP)
    print(f"valid (S0 and DoLP >= {MIN_DOLP}): {valid.sum()}/{valid.size} ({100*valid.mean():.1f}%)")

    print("unwrapping axis on a coarse grid...")
    coarse = unwrap_coarse_grid(axis_deg, valid, step=args.grid_step)
    zoom_factor = (axis_deg.shape[0] / coarse.shape[0], axis_deg.shape[1] / coarse.shape[1])
    angle_full = zoom(coarse, zoom_factor, order=1)[: axis_deg.shape[0], : axis_deg.shape[1]]
    theta = np.radians(angle_full)
    ux, uy = np.cos(theta).astype(np.float32), np.sin(theta).astype(np.float32)

    print("running LIC...")
    rng = np.random.default_rng(0)
    noise = rng.random(axis_deg.shape, dtype=np.float32)
    lic = line_integral_convolution(ux, uy, noise, length=args.lic_length)
    lic_norm = (lic - lic.min()) / max(lic.max() - lic.min(), 1e-6)

    delta_top = np.percentile(delta_deg[valid], 99)
    delta_norm = np.clip(delta_deg / max(delta_top, 1e-6), 0, 1)
    hue = (angle_full / 90.0) % 1.0
    value = np.where(valid, lic_norm * (0.3 + 0.7 * delta_norm), 0.0)
    rgb = hsv_to_rgb(hue, np.ones_like(hue), value)

    fig, ax = plt.subplots(figsize=(11, 9), facecolor="black")
    ax.imshow(rgb)
    ax.set_title("LIC fiber orientation map (hue=axis, brightness=LIC x retardance)", color="white")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(f"{args.out}.png", dpi=150, facecolor="black")
    print(f"wrote {args.out}.png")


if __name__ == "__main__":
    main()
