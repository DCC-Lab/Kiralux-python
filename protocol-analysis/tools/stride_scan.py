import numpy as np
W, H = 2448, 2048
data = open("raw_frame.bin", "rb").read()
PIX = W * 3 // 2  # 3672

def unpackA_rows(frame_off, stride):
    out = np.empty((H, W), np.uint16)
    for i in range(H):
        s = frame_off + i * stride
        buf = data[s:s + PIX]
        if len(buf) < PIX:
            return None
        b = np.frombuffer(buf, np.uint8).astype(np.uint16).reshape(-1, 3)
        out[i, 0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
        out[i, 1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
    return out

def vmed(img):
    c = img[300:700, 400:2000].astype(np.int32)
    return float(np.median(np.abs(c[1:] - c[:-1])))

best = None
for stride in range(3668, 3689):
    # frame_off doit garder la phase packing : multiple de 3 proche de 0/8
    for fo in (0, 60):
        img = unpackA_rows(fo, stride)
        if img is None: continue
        m = vmed(img)
        flag = ""
        if best is None or m < best[0]:
            best = (m, stride, fo); flag = "  <--"
        print(f"stride={stride} fo={fo:3d}  vmed={m:7.1f}{flag}")
print("\nBEST:", best)
