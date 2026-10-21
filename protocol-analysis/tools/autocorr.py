import numpy as np
data = np.frombuffer(open("raw_frame.bin", "rb").read(), np.uint8).astype(np.float32)
# remove the mean, take a slice of the middle (image area)
seg = data[100000:100000 + 400000]
seg = seg - seg.mean()

# autocorrelation for lags around a line (3600..3760)
print("lag   corr")
best = None
for lag in range(3600, 3761):
    a = seg[:-lag]; b = seg[lag:]
    c = float(np.dot(a, b) / len(a))
    if best is None or c > best[1]:
        best = (lag, c)
# display the 12 best lags
scores = []
for lag in range(3600, 3761):
    a = seg[:-lag]; b = seg[lag:]
    scores.append((float(np.dot(a, b)/len(a)), lag))
scores.sort(reverse=True)
for c, lag in scores[:12]:
    print(f"{lag}  {c:.1f}")
print("\nBEST lag =", best[0])

# also: look for the true divisor. total/2048 = 3680 ; total/lag ?
total = len(data)
print("total =", total, " total/3672=%.3f" % (total/3672), " total/3680=%.3f" % (total/3680))
for lag in [s[1] for s in scores[:6]]:
    print(f"  total/{lag} = {total/lag:.3f}")
