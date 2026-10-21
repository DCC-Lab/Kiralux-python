import numpy as np

W, H = 2448, 2048
data = open("raw_frame.bin", "rb").read()
PIXBYTES = W * 3 // 2  # 3672

def unpackA(buf):
    b = np.frombuffer(buf, dtype=np.uint8).astype(np.uint16).reshape(-1, 3)
    p = np.empty(b.shape[0] * 2, np.uint16)
    p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
    p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    return p

def build(frame_off, stride, lead):
    rows = []
    for i in range(H):
        s = frame_off + i * stride + lead
        buf = data[s:s + PIXBYTES]
        if len(buf) < PIXBYTES:
            return None
        rows.append(unpackA(buf))
    return np.array(rows, dtype=np.uint16)  # (H, W)

def vmetric(img):
    # difference ligne a ligne (meme polariseur -> distance 2 lignes), zone centrale
    c = img[400:600, 400:2000].astype(np.int32)
    return float(np.median(np.abs(c[2:] - c[:-2])))

best = None
for frame_off in (0, 8, 60, 16384):
    for stride in (3672, 3680):
        for lead in (0, 8):
            img = build(frame_off, stride, lead)
            if img is None:
                continue
            m = vmetric(img)
            print(f"frame_off={frame_off:6d} stride={stride} lead={lead}  vmed={m:7.1f}")
            if best is None or m < best[0]:
                best = (m, frame_off, stride, lead)
print("\nBEST:", best)
