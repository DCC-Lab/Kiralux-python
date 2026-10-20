import numpy as np
from PIL import Image
W, H = 2448, 2048
data = open("raw_frame.bin", "rb").read()

def unpackA(off, n):
    raw = np.frombuffer(data[off:off + n*3//2], np.uint8).astype(np.uint16)
    b = raw.reshape(-1, 3)
    p = np.empty(n, np.uint16)
    p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
    p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    return p

def save(a, name, t=600):
    a = a.astype(np.float32)
    lo, hi = np.percentile(a, [1, 99])
    d = np.clip((a - lo) / max(hi-lo,1) * 255, 0, 255).astype(np.uint8)
    im = Image.fromarray(d, "L"); im.thumbnail((t, t)); im.save(name)

for OFF in (60, 16384):
    pix = unpackA(OFF, W*H)
    # H2 planaire : 4 plans 1224x1024
    pw, ph = W//2, H//2
    plane0 = pix[:pw*ph].reshape(ph, pw)
    save(plane0, f"H2_plane0_off{OFF}.png")
    # metrique lissage du plan 0
    v = float(np.median(np.abs(plane0[1:].astype(int)-plane0[:-1])))
    h = float(np.median(np.abs(plane0[:,1:].astype(int)-plane0[:,:-1])))
    print(f"OFF={OFF} H2 plane0: vmed={v:.1f} hmed={h:.1f}")
