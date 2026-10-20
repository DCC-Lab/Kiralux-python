import numpy as np
W, H = 2448, 2048
data = open("raw_frame.bin", "rb").read()
OFF = 60
raw = np.frombuffer(data[OFF:OFF + W*H*3//2], np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)
p = np.empty(W*H, np.uint16)
p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
img = p.reshape(H, W).astype(np.int32)

# rugosite intra-ligne (mediane |dx|) par ligne
rough = np.median(np.abs(img[:, 1:] - img[:, :-1]), axis=1)
print("rugosite par ligne 495..525:")
for r in range(495, 526):
    bar = "#" * int(rough[r] / 40)
    print(f"  row {r:4d}: {rough[r]:6.0f} {bar}")

# combien de lignes 'folles' (rough > 600) et leur espacement
wild = np.where(rough > 600)[0]
print(f"\nlignes folles (rough>600): {len(wild)} / {H}")
if len(wild) > 1:
    diffs = np.diff(wild)
    vals, cnts = np.unique(diffs, return_counts=True)
    print("espacements les plus frequents:", sorted(zip(cnts, vals), reverse=True)[:6])
print("premieres lignes folles:", wild[:20].tolist())
