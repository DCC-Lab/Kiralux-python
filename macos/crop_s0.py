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
s0 = (img[0::2, 0::2] + img[0::2, 1::2] + img[1::2, 0::2] + img[1::2, 1::2]) / 4.0

# vertical smoothness test : correlation ligne a ligne du raw
def vstep(a):
    return float(np.median(np.abs(a[1:] - a[:-1])))
print("S0 vertical median|dy| =", vstep(s0))
print("S0 horizontal median|dx| =", float(np.median(np.abs(s0[:,1:]-s0[:,:-1]))))

# crop plein res centre (zone relativement lisse), 1:1
cy, cx = 500, 600
crop = s0[cy:cy+180, cx:cx+240]
lo, hi = np.percentile(s0, [2, 98])
d = np.clip((crop - lo) / max(hi-lo,1) * 255, 0, 255).astype(np.uint8)
Image.fromarray(d, "L").resize((240*2, 180*2), Image.NEAREST).save("crop_s0_fullres.png")
print("crop mean=%.1f std=%.1f" % (crop.mean(), crop.std()))
