import time, usb.core, usb.util
import numpy as np
from PIL import Image
from camera_usb import ThorCam, EP_IMG_IN

c = ThorCam(verbose=True)
print("roi.disc ->", c.cmd("roi.disc"))
c.cmd("stop")
# small centered ROI 512x512
print("set roi ->", c.cmd("roi 960 768 512 512"))
W = int(c.cmd("image_width")); H = int(c.cmd("image_height"))
print("dims after roi:", W, H)
c.cmd("exp 20000"); c.cmd("hwtrig none"); c.cmd("nframes 1")
c.cmd("arm"); c.cmd("start")
buf = usb.util.create_buffer(4 * 1024 * 1024)
t0 = time.time()
try:
    n = c.dev.read(EP_IMG_IN, buf, timeout=4000)
except usb.core.USBError as e:
    n = 0; print("err", e)
dt = time.time() - t0
c.cmd("stop"); c.close()
data = bytes(buf[:n])
print(f"read {n} bytes in {dt*1000:.0f}ms  expected header+WH1.5={16384 + W*H*3//2} or {W*H*3//2}")

# decode (tries offset 16384 and 60)
for OFF in (16384, 60):
    need = W*H*3//2
    if len(data) < OFF+need:
        print(f"  off={OFF}: not enough data"); continue
    raw = np.frombuffer(data[OFF:OFF+need], np.uint8).astype(np.uint16)
    b = raw.reshape(-1,3)
    p = np.empty(W*H, np.uint16)
    p[0::2] = b[:,0] | ((b[:,1]&0x0F)<<8)
    p[1::2] = (b[:,1]>>4) | (b[:,2]<<4)
    img = p.reshape(H,W).astype(np.int32)
    vmed = np.median(np.abs(img[1:]-img[:-1])); hmed = np.median(np.abs(img[:,1:]-img[:,:-1]))
    print(f"  off={OFF}: vmed={vmed:.1f} hmed={hmed:.1f}")
    a = img.astype(np.float32); lo,hi=np.percentile(a,[1,99])
    d=np.clip((a-lo)/max(hi-lo,1)*255,0,255).astype(np.uint8)
    Image.fromarray(d,"L").save(f"roi_off{OFF}.png")
