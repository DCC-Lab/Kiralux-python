import numpy as np
data = open("raw_big.bin", "rb").read()
OFF = 16384
raw = np.frombuffer(data[OFF:], np.uint8).astype(np.uint16)
n3 = (len(raw) // 3)
b = raw[:n3*3].reshape(-1, 3)
pix = np.empty(n3 * 2, np.uint16)
pix[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
pix[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
pix = pix.astype(np.int32)
print("total pixels:", len(pix))

best = None
for Wt in range(2420, 2480, 2):
    nrows = len(pix) // Wt
    if nrows < 400:
        continue
    img = pix[:nrows * Wt].reshape(nrows, Wt)
    # correlation verticale distance 2 (meme polariseur) sur zone centrale
    c = img[200:nrows-200, 100:Wt-100]
    v = float(np.median(np.abs(c[2:] - c[:-2])))
    flag = ""
    if best is None or v < best[0]:
        best = (v, Wt, nrows); flag = " <--"
    print(f"Wt={Wt} nrows={nrows}  vmed2={v:7.1f}{flag}")
print("BEST:", best)
