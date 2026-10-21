import time, numpy as np
from PIL import Image
import usb1

VID, PID = 0x1313, 0x4001
EPO, EPI, EPIMG = 0x02, 0x82, 0x83
HDR = 16384
N, BUF = 64, 256*1024

ctx = usb1.USBContext(); ctx.open()
h = ctx.openByVendorIDAndProductID(VID, PID)
try: h.setAutoDetachKernelDriver(True)
except Exception: pass
h.claimInterface(0)

def cmd(s, to=2000):
    h.bulkWrite(EPO, (s.encode()+b"\x00").ljust(1024, b"\x00"), to)
    r = h.bulkRead(EPI, 1024, to)
    return bytes(r).split(b"\x00")[0].decode("latin1").strip()

cmd("stop"); cmd("roi 0 0 2447 2047")
W = int(cmd("image_width")); H = int(cmd("image_height"))
cmd("exp 20000"); cmd("hwtrig none"); cmd("nframes 1")
row = W*3//2; pix = W*H*row//row; pix = W*H*3//2; target = HDR + pix

data = bytearray(); st = {"a": N, "stop": False}
def cb(t):
    if t.getStatus() == usb1.TRANSFER_COMPLETED:
        data.extend(t.getBuffer()[:t.getActualLength()])
    if not st["stop"] and len(data) < target:
        try: t.submit(); return
        except usb1.USBError: pass
    st["a"] -= 1

ts = []
for _ in range(N):
    t = h.getTransfer(); t.setBulk(EPIMG, BUF, callback=cb, timeout=1000); ts.append(t)
cmd("arm"); cmd("start")
for t in ts: t.submit()
t0 = time.monotonic()
while st["a"] > 0 and len(data) < target and time.monotonic()-t0 < 4:
    ctx.handleEventsTimeout(0.05)
st["stop"] = True
for t in ts:
    try: t.cancel()
    except Exception: pass
t1 = time.monotonic()
while st["a"] > 0 and time.monotonic()-t1 < 1:
    ctx.handleEventsTimeout(0.02)
try: cmd("stop")
except Exception: pass
h.releaseInterface(0); ctx.close()

print(f"recu {len(data)}/{target}  ({100*len(data)/target:.1f}%)")
nrows = min(H, (len(data)-HDR)//row)
raw = np.frombuffer(bytes(data[HDR:HDR+nrows*row]), np.uint8).astype(np.uint16).reshape(-1,3)
p = np.empty(nrows*W, np.uint16)
p[0::2] = raw[:,0] | ((raw[:,1]&0x0F)<<8); p[1::2] = (raw[:,1]>>4) | (raw[:,2]<<4)
img = p.reshape(nrows, W)
vmed = float(np.median(np.abs(img[1:].astype(int)-img[:-1])))
hmed = float(np.median(np.abs(img[:,1:].astype(int)-img[:,:-1])))
print(f"{nrows} lignes  vmed={vmed:.1f} hmed={hmed:.1f}  (propre si ~egaux et <20)")
a=img.astype(np.float32); lo,hi=np.percentile(a,[1,99])
d=np.clip((a-lo)/max(hi-lo,1)*255,0,255).astype(np.uint8)
Image.fromarray(d,"L").resize((1300,int(1300*nrows/W)),Image.LANCZOS).save("async2.png")
print("-> async2.png")
