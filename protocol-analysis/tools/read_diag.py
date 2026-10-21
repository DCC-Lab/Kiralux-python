import time, usb.core
from camera_usb import ThorCam, EP_IMG_IN

def drain_frame(c, label):
    c.cmd("stop"); c.cmd("exp 20000"); c.cmd("hwtrig none"); c.cmd("nframes 1")
    W = int(c.cmd("image_width")); H = int(c.cmd("image_height"))
    c.cmd("arm"); c.cmd("start")
    total = 0; reads = 0; first = b""
    t0 = time.time()
    while time.time() - t0 < 6:
        try:
            part = c.dev.read(EP_IMG_IN, 16384, timeout=600)
        except usb.core.USBError:
            break   # nothing left to read
        if not first:
            first = bytes(part[:16])
        total += len(part); reads += 1
    c.cmd("stop")
    print(f"[{label}] W={W} H={H}  received={total} B  reads={reads}  "
          f"W*H*1.5={int(W*H*1.5)}  W*H*2={W*H*2}  first={first.hex()}")

c = ThorCam(verbose=False)
print("pack =", c.cmd("imgpack"))
drain_frame(c, "imgpack ON")
print("set off ->", c.cmd("imgpack off"), "| now", c.cmd("imgpack"))
drain_frame(c, "imgpack OFF")
c.close()
