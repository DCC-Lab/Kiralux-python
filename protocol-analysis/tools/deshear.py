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

# For each line, integer shift [-30..30] maximizing the correlation with line-2 (same polarizer)
shifts = [0, 0]
col = slice(300, 2100)
for i in range(2, H):
    ref = img[i-2, col]
    best_s, best_c = 0, -1e18
    cur = img[i]
    for s in range(-30, 31):
        seg = cur[300+s:2100+s] if (300+s>=0 and 2100+s<=W) else None
        if seg is None or len(seg) != (2100-300):
            continue
        c = -np.mean(np.abs(seg - ref))  # - difference = correlation
        if c > best_c:
            best_c, best_s = c, s
    shifts.append(best_s)
shifts = np.array(shifts)
print("shifts: min=%d max=%d  first 20:" % (shifts.min(), shifts.max()), shifts[:20].tolist())
print("cumulative shift at the last line:", int(np.cumsum(shifts)[-1]))
# histogram of the shifts
vals, cnts = np.unique(shifts, return_counts=True)
print("shift distribution:", dict(zip(vals.tolist(), cnts.tolist())))
