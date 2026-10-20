import time, usb.core
from camera_usb import ThorCam, EP_IMG_IN

c = ThorCam(verbose=False)
c.cmd("stop"); c.cmd("exp 20000"); c.cmd("hwtrig none"); c.cmd("nframes 1")
W = int(c.cmd("image_width")); H = int(c.cmd("image_height"))
c.cmd("arm"); c.cmd("start")
data = bytearray()
t0 = time.time()
while time.time() - t0 < 6:
    try:
        part = c.dev.read(EP_IMG_IN, 65536, timeout=600)
    except usb.core.USBError:
        break
    data.extend(part)
c.cmd("stop"); c.close()

open("raw_frame.bin", "wb").write(data)
print(f"total={len(data)}  W={W} H={H}  W*H={W*H}  packed12={int(W*H*1.5)}")
# apercu en-tete
hdr = bytes(data[:128])
print("header hex :", hdr.hex())
print("header ascii:", "".join(chr(b) if 32 <= b < 127 else "." for b in hdr))
# cherche d'eventuels marqueurs ASCII dans les 2048 premiers octets
blk = bytes(data[:2048])
import re
for m in re.finditer(rb"[A-Za-z]{3,}", blk):
    print(f"  @0x{m.start():04x} {m.group().decode()!r}")
