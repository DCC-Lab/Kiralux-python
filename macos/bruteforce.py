import numpy as np

W, H = 2448, 2048
npix = W * H
data = open("raw_frame.bin", "rb").read()
need = npix * 3 // 2

def unpack(off, scheme):
    raw = np.frombuffer(data[off:off + need], dtype=np.uint8).astype(np.uint16)
    b = raw.reshape(-1, 3)
    p = np.empty(npix, np.uint16)
    if scheme == "A":   # Mono12p (USB3 Vision)
        p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
        p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    elif scheme == "B":
        p[0::2] = (b[:, 0] << 4) | (b[:, 1] >> 4)
        p[1::2] = ((b[:, 1] & 0x0F) << 8) | b[:, 2]
    elif scheme == "C":  # Mono12Packed (GenICam PFNC)
        p[0::2] = (b[:, 0] << 4) | (b[:, 1] & 0x0F)
        p[1::2] = (b[:, 2] << 4) | (b[:, 1] >> 4)
    elif scheme == "D":
        p[0::2] = (b[:, 1] & 0x0F) | (b[:, 0] << 4)
        p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    return p.reshape(H, W)

# metrique : sur une bande lisse (lignes 950-970), bruit entre pixels SAME-POLAR (distance 2)
def smoothness(img):
    band = img[950:970, 200:2200].astype(np.int32)
    # difference horizontale a distance 2 (meme polariseur)
    d2 = np.abs(band[:, 2::2] - band[:, 0:-2:2])
    return float(np.median(d2))

best = None
for off in (57, 58, 59, 60, 61, 62, 63, 16384):
    for s in ("A", "B", "C", "D"):
        try:
            img = unpack(off, s)
            m = smoothness(img)
            print(f"off={off:5d} scheme={s}  median|d2|={m:7.1f}")
            if best is None or m < best[0]:
                best = (m, off, s)
        except Exception as e:
            print(off, s, "err", e)
print("\nBEST:", best)
