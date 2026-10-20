import numpy as np
from PIL import Image
W, H = 2448, 2048
data = open("raw_big.bin", "rb").read()
OFF = 16384
raw = np.frombuffer(data[OFF:OFF + W*H*3//2], np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)
p = np.empty(W*H, np.uint16)
p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
img = p.reshape(H, W).astype(np.float32)

def save(a, name, t=640):
    lo, hi = np.percentile(a, [1, 99])
    d = np.clip((a - lo) / max(hi-lo,1) * 255, 0, 255).astype(np.uint8)
    im = Image.fromarray(d, "L"); im.thumbnail((t, t)); im.save(name)

# 4 canaux de polarisation (sous-echantillonnage 2x2)
c00 = img[0::2, 0::2]; c01 = img[0::2, 1::2]
c10 = img[1::2, 0::2]; c11 = img[1::2, 1::2]
save(c00, "ch00.png");
s0 = (c00 + c01 + c10 + c11) / 4
save(s0, "S0_final.png")
# roughness de chaque canal
for name, c in [("c00",c00),("c01",c01),("c10",c10),("c11",c11),("S0",s0)]:
    v = float(np.median(np.abs(c[1:]-c[:-1])))
    h = float(np.median(np.abs(c[:,1:]-c[:,:-1])))
    print(f"{name}: vmed={v:6.1f} hmed={h:6.1f} mean={c.mean():6.0f}")
