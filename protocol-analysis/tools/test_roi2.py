import time, usb.core, usb.util
import numpy as np
from PIL import Image
from camera_usb import ThorCam, EP_IMG_IN

c = ThorCam(verbose=False)
c.cmd("stop")
# valid ROI 1024x1024: left top right bottom
print("roi ->", c.cmd("roi 712 512 1735 1535"))
W = int(c.cmd("image_width")); H = int(c.cmd("image_height"))
print("dims:", W, H, " pixels_bytes=", W*H*3//2)
c.cmd("exp 20000"); c.cmd("hwtrig none"); c.cmd("nframes 1")
c.cmd("arm"); c.cmd("start")
buf = usb.util.create_buffer(4 * 1024 * 1024)
t0 = time.time()
n = c.dev.read(EP_IMG_IN, buf, timeout=4000)
dt = time.time() - t0
c.cmd("stop"); c.close()
data = bytes(buf[:n])
print(f"read {n} in {dt*1000:.0f}ms  (header60+pix={60+W*H*3//2})  throughput={n/dt/1e6:.1f}MB/s")

for OFF in (60, 16384):
    need = W*H*3//2
    if len(data) < OFF+need:
        print(f" off={OFF}: insufficient ({len(data)})"); continue
    raw = np.frombuffer(data[OFF:OFF+need], np.uint8).astype(np.uint16)
    b = raw.reshape(-1,3)
    p = np.empty(W*H, np.uint16)
    p[0::2]=b[:,0]|((b[:,1]&0x0F)<<8); p[1::2]=(b[:,1]>>4)|(b[:,2]<<4)
    img=p.reshape(H,W).astype(np.int32)
    print(f" off={OFF}: vmed={np.median(np.abs(img[1:]-img[:-1])):.1f} hmed={np.median(np.abs(img[:,1:]-img[:,:-1])):.1f}")
    a=img.astype(np.float32);lo,hi=np.percentile(a,[1,99])
    d=np.clip((a-lo)/max(hi-lo,1)*255,0,255).astype(np.uint8)
    Image.fromarray(d,"L").save(f"roi1024_off{OFF}.png")
