import time, usb.core, usb.util
import numpy as np
from camera_usb import ThorCam, EP_IMG_IN

def grab(c, W, H):
    c.cmd("stop"); c.cmd("exp 20000"); c.cmd("hwtrig none"); c.cmd("nframes 1")
    c.cmd("arm"); c.cmd("start")
    buf = usb.util.create_buffer(4*1024*1024)
    n = c.dev.read(EP_IMG_IN, buf, timeout=4000)
    c.cmd("stop")
    return bytes(buf[:n])

c = ThorCam(verbose=False)
c.cmd("stop"); c.cmd("roi 712 512 1735 1535")
W = int(c.cmd("image_width")); H = int(c.cmd("image_height"))
a = grab(c, W, H)
b = grab(c, W, H)
c.close()
print("size a,b:", len(a), len(b))
la = min(len(a), len(b))
diff = np.frombuffer(a[:la], np.uint8).astype(int) - np.frombuffer(b[:la], np.uint8).astype(int)
print("identical bytes:", int(np.sum(diff==0)), "/", la, f"({100*np.mean(diff==0):.1f}%)")
# where do the differences begin?
nz = np.nonzero(diff)[0]
print("first difference at offset:", int(nz[0]) if len(nz) else "none")
