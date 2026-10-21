import numpy as np
from PIL import Image
W, H = 2448, 2048
data = open("raw_frame.bin", "rb").read()
OFF = 60
raw = np.frombuffer(data[OFF:OFF + W*H*3//2], np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)
p = np.empty(W*H, np.uint16)
p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
img = p.reshape(H, W).astype(np.float32)
lo, hi = np.percentile(img, [1, 99])
d = np.clip((img - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
im = Image.fromarray(d, "L")
im = im.resize((1600, int(1600*H/W)), Image.LANCZOS)  # gentle reduction
im.save("full_raw_1600.png")
print("saved", im.size)
