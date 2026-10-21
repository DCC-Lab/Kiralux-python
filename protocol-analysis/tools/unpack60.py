import numpy as np
from PIL import Image

W, H = 2448, 2048
npix = W * H
data = open("raw_frame.bin", "rb").read()
OFF = 60  # pixels just after the ENDT tag
need = npix * 3 // 2
raw = np.frombuffer(data[OFF:OFF + need], dtype=np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)

def save(img, name, thumb=700):
    lo, hi = np.percentile(img, [1, 99])
    d = np.clip((img.astype(np.float32) - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    im = Image.fromarray(d, "L"); im.thumbnail((thumb, thumb)); im.save(name)

for s in ("A", "B"):
    p = np.empty(npix, np.uint16)
    if s == "A":
        p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
        p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    else:
        p[0::2] = (b[:, 0] << 4) | (b[:, 1] >> 4)
        p[1::2] = ((b[:, 1] & 0x0F) << 8) | b[:, 2]
    img = p.reshape(H, W)
    save(img, f"off60_{s}.png")
    # horizontal high-frequency noise (lower = good unpack)
    hf = np.mean(np.abs(np.diff(img[1000, :].astype(int))))
    print(f"scheme {s}: mean={img.mean():.1f} min={img.min()} max={img.max()} hf_noise={hf:.1f}")
