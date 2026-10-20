import numpy as np
W, H = 2448, 2048
data = open("raw_frame.bin", "rb").read()
OFF = 60
raw = np.frombuffer(data[OFF:OFF + W*H*3//2], dtype=np.uint8).astype(np.uint16)
b = raw.reshape(-1, 3)
p = np.empty(W*H, np.uint16)
p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
img = p.reshape(H, W)

# grille 14x14 pixels dans une zone 'lisse' (mur)
print("zone [500:514, 600:614]:")
for r in range(500, 514):
    print(" ".join("%4d" % img[r, c] for c in range(600, 614)))

# moyenne par parite de ligne et de colonne (sur grande zone lisse)
z = img[450:650, 500:2000].astype(float)
print("\nmoyennes par (ligne%2, col%2):")
for rp in (0,1):
    for cp in (0,1):
        print(f"  row%2={rp} col%2={cp}: {z[rp::2, cp::2].mean():.1f}")
# periode verticale : moyenne de chaque ligne sur 12 lignes
print("\nmoyenne de 12 lignes consecutives (col 500..2000):")
print([int(img[r,500:2000].mean()) for r in range(500,512)])
