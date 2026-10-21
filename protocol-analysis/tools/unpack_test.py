import numpy as np
from PIL import Image

W, H = 2448, 2048
npix = W * H
data = open("raw_frame.bin", "rb").read()
HDR = 16384
raw = np.frombuffer(data[HDR:HDR + npix * 3 // 2], dtype=np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)

# Schema A : p0 = b0 | (b1&0xF)<<8 ; p1 = b1>>4 | b2<<4
pA = np.empty(npix, np.uint16)
pA[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
pA[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)

# Schema B : p0 = b0<<4 | b1>>4 ; p1 = (b1&0xF)<<8 | b2
pB = np.empty(npix, np.uint16)
pB[0::2] = (b[:, 0] << 4) | (b[:, 1] >> 4)
pB[1::2] = ((b[:, 1] & 0x0F) << 8) | b[:, 2]

for name, p in [("A", pA), ("B", pB)]:
    img = p.reshape(H, W)
    lo, hi = np.percentile(img, [1, 99])
    disp = np.clip((img.astype(np.float32) - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    im = Image.fromarray(disp, "L")
    im.thumbnail((500, 500))
    im.save(f"unpack_{name}.png")
    print(f"schema {name}: min={img.min()} max={img.max()} mean={img.mean():.1f}")
