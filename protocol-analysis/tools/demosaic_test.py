import numpy as np
from PIL import Image

W, H = 2448, 2048
npix = W * H
data = open("raw_frame.bin", "rb").read()
HDR = 16384
raw = np.frombuffer(data[HDR:HDR + npix * 3 // 2], dtype=np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)

def unpack(scheme):
    p = np.empty(npix, np.uint16)
    if scheme == "A":
        p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
        p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    else:
        p[0::2] = (b[:, 0] << 4) | (b[:, 1] >> 4)
        p[1::2] = ((b[:, 1] & 0x0F) << 8) | b[:, 2]
    return p.reshape(H, W)

def save(img, name):
    lo, hi = np.percentile(img, [1, 99])
    disp = np.clip((img.astype(np.float32) - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    im = Image.fromarray(disp, "L"); im.thumbnail((520, 520)); im.save(name)

for s in ("A", "B"):
    img = unpack(s).astype(np.float32)
    # intensite S0 = moyenne du super-pixel 2x2 (demosaique polar)
    s0 = (img[0::2, 0::2] + img[0::2, 1::2] + img[1::2, 0::2] + img[1::2, 1::2]) / 4.0
    save(s0, f"intensity_{s}.png")
    # mesure de "striping residuel" : variance moyenne entre lignes paires/impaires sur zone lisse
    strip = np.mean(np.abs(img[0::2, :].mean(0) - img[1::2, :].mean(0)))
    print(f"schema {s}: S0 shape={s0.shape} mean={s0.mean():.1f} striping_rows={strip:.2f}")
