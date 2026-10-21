import time, numpy as np
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

cmd("stop"); cmd("sfr off")
cmd("roi 712 512 1735 1535")          # 1024x1024 centered
W=int(cmd("image_width"));H=int(cmd("image_height"))
cmd("exp 20000");cmd("hwtrig none");cmd("nframes 1")
pix=W*H*3//2; target=HDR+pix
N,BUF=64,131072
data=bytearray(); st={"a":N,"stop":False}
def cb(t):
    if t.getStatus()==usb1.TRANSFER_COMPLETED: data.extend(t.getBuffer()[:t.getActualLength()])
    if not st["stop"] and len(data)<target:
        try:t.submit();return
        except usb1.USBError:pass
    st["a"]-=1
ts=[h.getTransfer() for _ in range(N)]
for t in ts: t.setBulk(EPIMG,BUF,callback=cb,timeout=2000)
cmd("arm")
for t in ts:t.submit()
cmd("start");t0=time.monotonic()
while st["a"]>0 and len(data)<target and time.monotonic()-t0<4:
    ctx.handleEventsTimeout(0.02)
st["stop"]=True
for t in ts:
    try:t.cancel()
    except Exception:pass
t1=time.monotonic()
while st["a"]>0 and time.monotonic()-t1<0.5: ctx.handleEventsTimeout(0.02)
cmd("stop"); h.releaseInterface(0);ctx.close()

row=W*3//2; nrows=min(H,(len(data)-HDR)//row)
raw=np.frombuffer(bytes(data[HDR:HDR+nrows*row]),np.uint8).astype(np.uint16).reshape(-1,3)
p=np.empty(nrows*W,np.uint16)
p[0::2]=raw[:,0]|((raw[:,1]&0x0F)<<8);p[1::2]=(raw[:,1]>>4)|(raw[:,2]<<4)
img=p.reshape(nrows,W).astype(np.float32)
print(f"{nrows}x{W}  received {100*len(data)/target:.1f}%")
# S0 intensity (2x2 polar demosaic) for natural image
s0=(img[0::2,0::2]+img[0::2,1::2]+img[1::2,0::2]+img[1::2,1::2])/4
lo,hi=np.percentile(s0,[1,99])
d=np.clip((s0-lo)/max(hi-lo,1)*255,0,255).astype(np.uint8)
Image.fromarray(d,"L").save("clean_S0.png")
# raw too
lo,hi=np.percentile(img,[1,99])
d2=np.clip((img-lo)/max(hi-lo,1)*255,0,255).astype(np.uint8)
Image.fromarray(d2,"L").save("clean_raw.png")
print("-> clean_S0.png (intensity), clean_raw.png (raw mosaic)")
