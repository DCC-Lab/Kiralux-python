import numpy as np
from PIL import Image

W, H = 2448, 2048
npix = W * H
data = open("raw_frame.bin", "rb").read()
OFF = 60
raw = np.frombuffer(data[OFF:OFF + npix * 3 // 2], dtype=np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)
p = np.empty(npix, np.uint16)
p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
img = p.reshape(H, W).astype(np.float32)

# S0 intensity: mean of the 2x2 polar super-pixel -> 1224x1024, removes the mosaic
s0 = (img[0::2, 0::2] + img[0::2, 1::2] + img[1::2, 0::2] + img[1::2, 1::2]) / 4.0

def save(a, name, thumb=760):
    lo, hi = np.percentile(a, [1, 99])
    d = np.clip((a - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    im = Image.fromarray(d, "L"); im.thumbnail((thumb, thumb)); im.save(name)

save(s0, "S0_off60.png")
print("S0", s0.shape, "mean=%.1f" % s0.mean())
# striping residual on S0
print("striping S0 (even/odd rows):", float(np.mean(np.abs(s0[0::2].mean(0) - s0[1::2].mean(0)))))
