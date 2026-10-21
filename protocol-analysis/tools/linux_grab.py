import sys, time, base64, io
import usb1, numpy as np
from PIL import Image
def log(*a): print(*a, flush=True)

VID,PID=0x1313,0x4001; EPO,EPI,EPIMG=0x02,0x82,0x83; HDR=16384
N,BUF=64,131072

c=usb1.USBContext(); c.open()
h=c.openByVendorIDAndProductID(VID,PID)
try:
    if h.kernelDriverActive(0): h.detachKernelDriver(0)
except Exception: pass
h.claimInterface(0)
def cmd(s,to=3000):
    h.bulkWrite(EPO,(s.encode()+b"\x00").ljust(1024,b"\x00"),to)
    return bytes(h.bulkRead(EPI,1024,to)).split(b"\x00")[0].decode("latin1").strip()

cmd("stop"); cmd("roi 0 0 2447 2047"); cmd("sfr off")
W=int(cmd("image_width"));H=int(cmd("image_height"))
cmd("exp 20000");cmd("hwtrig none");cmd("nframes 1")
pix=W*H*3//2; target=HDR+pix
data=bytearray(); st={"a":N,"stop":False}
def cb(t):
    if t.getStatus()==usb1.TRANSFER_COMPLETED: data.extend(t.getBuffer()[:t.getActualLength()])
    if not st["stop"] and len(data)<target:
        try:t.submit();return
        except usb1.USBError:pass
    st["a"]-=1
ts=[h.getTransfer() for _ in range(N)]
for t in ts:t.setBulk(EPIMG,BUF,callback=cb,timeout=2000)
cmd("arm")
for t in ts:t.submit()
t0=time.monotonic();cmd("start")
while st["a"]>0 and len(data)<target and time.monotonic()-t0<6:
    c.handleEventsTimeout(0.02)
dt=time.monotonic()-t0
st["stop"]=True
for t in ts:
    try:t.cancel()
    except Exception:pass
t1=time.monotonic()
while st["a"]>0 and time.monotonic()-t1<0.5:c.handleEventsTimeout(0.02)
cmd("stop"); h.releaseInterface(0); c.close()

log(f"W={W} H={H} recu={len(data)}/{target} ({100*len(data)/target:.1f}%) en {dt*1000:.0f}ms = {len(data)/max(dt,1e-3)/1e6:.1f} MB/s")
row=W*3//2; nrows=min(H,(len(data)-HDR)//row); nrows-=nrows%2
raw=np.frombuffer(bytes(data[HDR:HDR+nrows*row]),np.uint8).astype(np.uint16).reshape(-1,3)
p=np.empty(nrows*W,np.uint16)
p[0::2]=raw[:,0]|((raw[:,1]&0x0F)<<8);p[1::2]=(raw[:,1]>>4)|(raw[:,2]<<4)
img=p.reshape(nrows,W)
vmed=float(np.median(np.abs(img[1:].astype(int)-img[:-1])));hmed=float(np.median(np.abs(img[:,1:].astype(int)-img[:,:-1])))
log(f"nrows={nrows} vmed={vmed:.1f} hmed={hmed:.1f} -> {'PROPRE' if vmed<60 else 'STRIE'}")
# vignette S0 -> base64 (stdout)
s0=(img[:nrows//2*2:2,0::2].astype(np.float32)+img[1:nrows//2*2:2,0::2]+img[:nrows//2*2:2,1::2]+img[1:nrows//2*2:2,1::2])/4
lo,hi=np.percentile(s0,[1,99]);d=np.clip((s0-lo)/max(hi-lo,1)*255,0,255).astype(np.uint8)
im=Image.fromarray(d,"L");im.thumbnail((360,360))
buf=io.BytesIO();im.save(buf,format="JPEG",quality=70)
log("THUMB_B64:"+base64.b64encode(buf.getvalue()).decode())
