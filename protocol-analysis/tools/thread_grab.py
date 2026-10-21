import time, threading, numpy as np
from PIL import Image
import usb1
VID,PID=0x1313,0x4001; EPO,EPI,EPIMG=0x02,0x82,0x83; HDR=16384
ctx=usb1.USBContext();ctx.open()
h=ctx.openByVendorIDAndProductID(VID,PID)
try:h.setAutoDetachKernelDriver(True)
except Exception:pass
h.claimInterface(0)
def cmd(s,to=3000):
    h.bulkWrite(EPO,(s.encode()+b"\x00").ljust(1024,b"\x00"),to)
    return bytes(h.bulkRead(EPI,1024,to)).split(b"\x00")[0].decode("latin1").strip()

cmd("stop"); cmd("roi 0 0 2447 2047")
cmd("sfr off")  # normal sensor speed; we rely on fast draining
W=int(cmd("image_width"));H=int(cmd("image_height"))
cmd("exp 20000");cmd("hwtrig none");cmd("nframes 1")
pix=W*H*3//2; target=HDR+pix
N,BUF=96,131072   # 96 x 128KB = 12MB in flight
data=bytearray(); st={"a":N,"stop":False}
lock=threading.Lock()
def cb(t):
    if t.getStatus()==usb1.TRANSFER_COMPLETED:
        with lock: data.extend(t.getBuffer()[:t.getActualLength()])
    if not st["stop"] and len(data)<target:
        try:t.submit();return
        except usb1.USBError:pass
    st["a"]-=1

# thread that pumps the events continuously (high throughput)
def pump():
    while not st["stop"] and st["a"]>0:
        try: ctx.handleEventsTimeout(0.01)
        except Exception: break
ts=[]
for _ in range(N):
    t=h.getTransfer();t.setBulk(EPIMG,BUF,callback=cb,timeout=3000);ts.append(t)
cmd("arm")
th=threading.Thread(target=pump,daemon=True);
t0=time.monotonic(); cmd("start")
for t in ts:t.submit()
th.start()
while len(data)<target and st["a"]>0 and time.monotonic()-t0<6:
    time.sleep(0.01)
dt=time.monotonic()-t0
st["stop"]=True
for t in ts:
    try:t.cancel()
    except Exception:pass
time.sleep(0.3); th.join(timeout=1)
try:cmd("stop")
except Exception:pass
h.releaseInterface(0);ctx.close()
print(f"received {len(data)}/{target} ({100*len(data)/target:.1f}%) in {dt*1000:.0f}ms = {len(data)/dt/1e6:.1f} MB/s")
row=W*3//2; nrows=min(H,(len(data)-HDR)//row)
raw=np.frombuffer(bytes(data[HDR:HDR+nrows*row]),np.uint8).astype(np.uint16).reshape(-1,3)
p=np.empty(nrows*W,np.uint16)
p[0::2]=raw[:,0]|((raw[:,1]&0x0F)<<8);p[1::2]=(raw[:,1]>>4)|(raw[:,2]<<4)
img=p.reshape(nrows,W)
print(f"{nrows} lines vmed={np.median(np.abs(img[1:].astype(int)-img[:-1])):.1f} hmed={np.median(np.abs(img[:,1:].astype(int)-img[:,:-1])):.1f}")
a=img.astype(np.float32);lo,hi=np.percentile(a,[1,99])
d=np.clip((a-lo)/max(hi-lo,1)*255,0,255).astype(np.uint8)
Image.fromarray(d,"L").resize((1300,int(1300*nrows/W)),Image.LANCZOS).save("thread.png")
print("-> thread.png")
