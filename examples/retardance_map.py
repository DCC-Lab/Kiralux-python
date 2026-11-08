"""Invert the measured AoLP/DoLP shift into retardance (birefringence), per pixel,
using the exact Mueller matrix of an ideal linear retarder.

Model: the reference frame (polarized light, no sample) gives the input Stokes
state at each pixel: degree of polarization p(x,y) and azimuth theta0(x,y). The
sample is modeled as a lossless linear retarder with unknown fast-axis angle
alpha(x,y) and retardance delta(x,y). Rotating the sample's measured (S1,S2) into
the frame aligned with theta0 gives two numbers A, B per pixel; inverting the
retarder's Mueller matrix (exact, not a small-angle approximation) gives:

    4*alpha' = atan2(2*A*B, B^2 - A^2)        (fast/slow axis, mod 90 deg: a
                                                linear-Stokes-only measurement
                                                cannot tell fast from slow, nor
                                                recover the sign of delta)
    u = sqrt(A^2+B^2) / (p * |sin(2*alpha')|)  (u = 1 - cos(delta))
    delta = arccos(1 - u)                      (retardance magnitude, 0..180 deg)

IMPORTANT LIMITATIONS (this is not a black box -- read before trusting the numbers):

  - delta enters the measured (S1,S2) at SECOND order (u ~ delta^2/2): a tiny
    retardance produces an even tinier signal. The noise floor in delta is
    therefore much larger, in degrees, than the noise floor in AoLP was.
  - Isotropic depolarization (scattering -- brain tissue scatters) looks exactly
    like a retarder at alpha'=+/-45 deg (B=0, A>0). A 1% DoLP drop alone gives
    delta ~ 8 deg with NO real birefringence. Always check the alpha' histogram
    for a pile-up at +/-45 deg, and compare the delta map to the DoLP-drop map:
    if they match, you are looking at scattering, not retardance.
  - A pure rotation (AoLP shifts, DoLP does not drop: B >> A) inverts to
    delta ~ 180 deg (a "half-wave plate" solution) in this model -- it does NOT
    mean a huge true retardance.
  - Blind spot: where the fast/slow axis is parallel or perpendicular to the
    input polarization, A = B = 0 for ANY delta -- unmeasurable at that pixel,
    for any sample.
  - With white-light illumination delta is not a single physical retardance at
    one wavelength; treat the deg/rad number as an effective, spectrally-averaged
    response, not Delta_n * d at a defined lambda.

This script does not hide any of that: it prints the diagnostic fractions and
plots alpha' and the delta-vs-DoLP comparison alongside the delta map.

    python examples/retardance_map.py sample.tiff reference.tiff --out retardance
"""
import argparse

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image as PILImage

from kiralux import PolarFrame


def load(path):
    return PolarFrame(np.asarray(PILImage.open(path), dtype=np.float32))


def invert(ref: PolarFrame, sample: PolarFrame, min_s0: float, blind_spot_eps: float = 0.08):
    s0r, s1r, s2r = ref.stokes
    s0s, s1s, s2s = sample.stokes
    good_s0 = (s0r >= min_s0) & (s0s >= min_s0)

    p = np.hypot(s1r, s2r) / np.maximum(s0r, 1e-9)
    theta0 = 0.5 * np.arctan2(s2r, s1r)
    c, s = np.cos(2 * theta0), np.sin(2 * theta0)

    a = (s1s * c + s2s * s) / np.maximum(s0s, 1e-9)
    b = (-s1s * s + s2s * c) / np.maximum(s0s, 1e-9)
    A = p - a
    B = b

    four_alpha = np.arctan2(2 * A * B, B**2 - A**2)
    alpha_prime_deg = np.degrees(four_alpha) / 4.0
    sin2ap = np.sin(np.radians(2 * alpha_prime_deg))

    blind = np.abs(sin2ap) < blind_spot_eps
    R = np.hypot(A, B)
    with np.errstate(divide="ignore", invalid="ignore"):
        u = R / (p * np.abs(sin2ap))
    delta_deg = np.degrees(np.arccos(np.clip(1 - u, -1, 1)))

    axis_abs_deg = np.degrees(theta0) + alpha_prime_deg
    axis_abs_deg = np.mod(axis_abs_deg, 90.0)

    valid = good_s0 & ~blind & np.isfinite(delta_deg)
    inconsistent = good_s0 & (A < 0)  # A < 0 cannot happen for an ideal retarder

    return dict(delta_deg=delta_deg, axis_deg=axis_abs_deg, alpha_prime_deg=alpha_prime_deg,
                A=A, B=B, p=p, valid=valid, blind=blind & good_s0, inconsistent=inconsistent,
                dolp_drop=ref.dolp - sample.dolp)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sample")
    ap.add_argument("reference")
    ap.add_argument("--out", default="retardance")
    ap.add_argument("--min-s0", type=float, default=200.0)
    args = ap.parse_args()

    ref, sample = load(args.reference), load(args.sample)
    r = invert(ref, sample, args.min_s0)

    valid = r["valid"]
    n_total = valid.size
    print(f"valid (above min-s0, not blind-spot): {valid.sum()}/{n_total} ({100*valid.mean():.1f}%)")
    print(f"blind-spot pixels (axis within ~5 deg of input azimuth): "
          f"{r['blind'].sum()} ({100*r['blind'].mean():.1f}%)")
    print(f"model-inconsistent pixels (A<0, impossible for an ideal retarder): "
          f"{r['inconsistent'].sum()} ({100*r['inconsistent'].mean():.1f}%)")
    d = r["delta_deg"][valid]
    print(f"delta (deg): median {np.median(d):.3f}  mean {d.mean():.3f}  "
          f"fraction > 90 deg (half-wave-like, likely rotation not retardance): "
          f"{100*(d > 90).mean():.1f}%")
    ap_deg = r["alpha_prime_deg"][valid]
    near45 = (np.abs(np.abs(ap_deg) - 45) < 10).mean()
    print(f"alpha' pile-up near +/-45 deg (sign of scattering mimicking retardance): "
          f"{100*near45:.1f}% of valid pixels within 10 deg of +/-45")

    fig, axs = plt.subplots(2, 2, figsize=(14, 12))
    masked_delta = np.ma.masked_array(r["delta_deg"], mask=~valid)
    im0 = axs[0, 0].imshow(masked_delta, cmap="viridis", vmin=0, vmax=np.percentile(d, 99))
    axs[0, 0].set_title("Retardance magnitude |delta| (deg) -- see caveats in the docstring")
    fig.colorbar(im0, ax=axs[0, 0], fraction=0.046, pad=0.04)

    masked_axis = np.ma.masked_array(r["axis_deg"], mask=~valid)
    im1 = axs[0, 1].imshow(masked_axis, cmap="twilight", vmin=0, vmax=90)
    axs[0, 1].set_title("Fast/slow axis (deg, mod 90 -- fast vs slow not resolved)")
    fig.colorbar(im1, ax=axs[0, 1], fraction=0.046, pad=0.04)

    axs[1, 0].hist(ap_deg, bins=90, range=(-45, 45))
    axs[1, 0].axvline(-45, color="r", ls="--"); axs[1, 0].axvline(45, color="r", ls="--")
    axs[1, 0].set_title("alpha' histogram (pile-up at +/-45 = scattering, not retardance)")
    axs[1, 0].set_xlabel("alpha' (deg)")

    dolp_drop = r["dolp_drop"][valid]
    axs[1, 1].scatter(dolp_drop[::97], d[::97], s=2, alpha=0.3)
    axs[1, 1].set_xlabel("DoLP drop (reference - sample)")
    axs[1, 1].set_ylabel("delta (deg)")
    axs[1, 1].set_title("delta vs DoLP drop (correlated => scattering, not birefringence)")

    for ax in axs[0]:
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(f"{args.out}.png", dpi=150)
    np.save(f"{args.out}_delta.npy", r["delta_deg"].astype(np.float32))
    np.save(f"{args.out}_axis.npy", r["axis_deg"].astype(np.float32))
    print(f"wrote {args.out}.png, {args.out}_delta.npy, {args.out}_axis.npy")


if __name__ == "__main__":
    main()
