import numpy as np
from PIL import Image

W, H = 2448, 2048
npix = W * H
data = open("raw_frame.bin", "rb").read()

# 1) Content of the header area between the tags (60) and 16384
seg = np.frombuffer(data[60:16384], dtype=np.uint8)
print(f"header[60:16384]: nonzero={np.count_nonzero(seg)}/{seg.size} "
      f"min={seg.min()} max={seg.max()}")
# where do the first non-zero bytes after 60 begin?
nz = np.nonzero(seg)[0]
print("  first non-zero offsets (abs):", (nz[:8] + 60).tolist() if nz.size else "none")

HDR = 16384
raw = np.frombuffer(data[HDR:HDR + npix * 3 // 2], dtype=np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)
p = np.empty(npix, np.uint16)
p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
img = p.reshape(H, W)

# 2) full resolution crop of smooth area (wall), enlarged x4 to see the real pattern
crop = img[900:980, 1000:1080].astype(np.float32)
lo, hi = np.percentile(img, [1, 99])
d = np.clip((crop - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
Image.fromarray(d, "L").resize((80*5, 80*5), Image.NEAREST).save("crop_fullres.png")
print("crop stats: mean=%.1f std=%.1f" % (crop.mean(), crop.std()))
# pattern per column/line on the crop
print("mean of first 8 lines:", [int(crop[i].mean()) for i in range(8)])
print("mean of first 8 cols :", [int(crop[:, i].mean()) for i in range(8)])
