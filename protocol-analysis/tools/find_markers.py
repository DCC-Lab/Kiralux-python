data = open("raw_big.bin", "rb").read()
print("size:", len(data))
for marker in (b"FCNT", b"TSI", b"\x90\x90\x00\x00", b"PCKH", b"ENDT"):
    offs = []
    start = 0
    while True:
        i = data.find(marker, start)
        if i < 0: break
        offs.append(i); start = i + 1
    print(f"{marker!r}: {len(offs)} occurrences", offs[:12])
    if len(offs) > 2:
        diffs = [offs[k+1]-offs[k] for k in range(min(10,len(offs)-1))]
        print("   spacings:", diffs)
