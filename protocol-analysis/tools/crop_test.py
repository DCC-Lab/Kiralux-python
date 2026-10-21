import numpy as np
from PIL import Image

W, H = 2448, 2048
npix = W * H
data = open("raw_frame.bin", "rb").read()

# 1) Contenu de la zone d'en-tete entre les tags (60) et 16384
seg = np.frombuffer(data[60:16384], dtype=np.uint8)
print(f"header[60:16384]: nonzero={np.count_nonzero(seg)}/{seg.size} "
      f"min={seg.min()} max={seg.max()}")
# ou commencent les premiers octets non nuls apres 60 ?
nz = np.nonzero(seg)[0]
print("  premiers non-zero offsets (abs):", (nz[:8] + 60).tolist() if nz.size else "aucun")

HDR = 16384
raw = np.frombuffer(data[HDR:HDR + npix * 3 // 2], dtype=np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)
p = np.empty(npix, np.uint16)
p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
img = p.reshape(H, W)

# 2) crop pleine resolution zone lisse (mur), agrandi x4 pour voir le motif reel
crop = img[900:980, 1000:1080].astype(np.float32)
lo, hi = np.percentile(img, [1, 99])
d = np.clip((crop - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
Image.fromarray(d, "L").resize((80*5, 80*5), Image.NEAREST).save("crop_fullres.png")
print("crop stats: mean=%.1f std=%.1f" % (crop.mean(), crop.std()))
# motif par colonne/ligne sur le crop
print("moyenne 8 premieres lignes:", [int(crop[i].mean()) for i in range(8)])
print("moyenne 8 premieres cols :", [int(crop[:, i].mean()) for i in range(8)])
