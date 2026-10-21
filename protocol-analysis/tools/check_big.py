import numpy as np
from PIL import Image
W, H = 2448, 2048
data = open("raw_big.bin", "rb").read()

def unpackA(off):
    raw = np.frombuffer(data[off:off + W*H*3//2], np.uint8).astype(np.uint16)
    b = raw.reshape(-1, 3)
    p = np.empty(W*H, np.uint16)
    p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
    p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    return p.reshape(H, W).astype(np.int32)

for off in (60, 16384):
    img = unpackA(off)
    rough = np.median(np.abs(img[:, 1:] - img[:, :-1]), axis=1)
    wild = int((rough > 600).sum())
    print(f"off={off}: lignes folles={wild}/{H}  rough median={np.median(rough):.0f}")

# genere l'image au meilleur offset
best_off = 16384 if (np.median(np.abs(unpackA(16384)[:,1:]-unpackA(16384)[:,:-1]),axis=1)>600).sum() < \
                     (np.median(np.abs(unpackA(60)[:,1:]-unpackA(60)[:,:-1]),axis=1)>600).sum() else 60
img = unpackA(best_off).astype(np.float32)
lo, hi = np.percentile(img, [1, 99])
d = np.clip((img - lo) / (hi-lo) * 255, 0, 255).astype(np.uint8)
im = Image.fromarray(d, "L").resize((1500, int(1500*H/W)), Image.LANCZOS)
im.save("big_view.png")
print("best_off=", best_off, "-> big_view.png")
