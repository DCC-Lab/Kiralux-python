import sys, time, argparse
import usb1, numpy as np
from PIL import Image
VID,PID=0x1313,0x4001; EPO,EPI,EPIMG=0x02,0x82,0x83; HDR=16384

ap=argparse.ArgumentParser()
ap.add_argument("--hbin",type=int,default=1); ap.add_argument("--vbin",type=int,default=1)
ap.add_argument("--sfr",default="off"); ap.add_argument("--nbuf",type=int,default=64)
ap.add_argument("--bufkb",type=int,default=128); ap.add_argument("--exp",type=int,default=20000)
ap.add_argument("--out",default="dbg.png")
a=ap.parse_args()
N,BUF=a.nbuf,a.bufkb*1024

c=usb1.USBContext(); c.open()
h=c.openByVendorIDAndProductID(VID,PID); h.claimInterface(0)
def cmd(s,to=3000):
    h.bulkWrite(EPO,(s.encode()+b"\x00").ljust(1024,b"\x00"),to)
    return bytes(h.bulkRead(EPI,1024,to)).split(b"\x00")[0].decode("latin1").strip()

cmd("stop"); cmd("roi 0 0 2447 2047")
cmd(f"sfr {a.sfr}")
cmd(f"hbin {a.hbin}"); cmd(f"vbin {a.vbin}")
W=int(cmd("image_width"));H=int(cmd("image_height"))
cmd(f"exp {a.exp}");cmd("hwtrig none");cmd("nframes 1")
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
while st["a"]>0 and len(data)<target and time.monotonic()-t0<8:
    c.handleEventsTimeout(0.01)
dt=time.monotonic()-t0
st["stop"]=True
for t in ts:
    try:t.cancel()
    except Exception:pass
t1=time.monotonic()
while st["a"]>0 and time.monotonic()-t1<0.5:c.handleEventsTimeout(0.02)
cmd("stop"); h.releaseInterface(0); c.close()

print(f"hbin={a.hbin} vbin={a.vbin} sfr={a.sfr} nbuf={N} buf={a.bufkb}k : {W}x{H} recu {100*len(data)/target:.1f}% en {dt*1000:.0f}ms = {len(data)/max(dt,1e-3)/1e6:.1f}MB/s")
row=W*3//2; nrows=min(H,(len(data)-HDR)//row); nrows-=nrows%2
if nrows<4: print("trop peu de donnees"); sys.exit()
raw=np.frombuffer(bytes(data[HDR:HDR+nrows*row]),np.uint8).astype(np.uint16).reshape(-1,3)
p=np.empty(nrows*W,np.uint16)
p[0::2]=raw[:,0]|((raw[:,1]&0x0F)<<8);p[1::2]=(raw[:,1]>>4)|(raw[:,2]<<4)
img=p.reshape(nrows,W)
vmed=float(np.median(np.abs(img[1:].astype(int)-img[:-1])));hmed=float(np.median(np.abs(img[:,1:].astype(int)-img[:,:-1])))
# ecart-type ligne-a-ligne pour detecter le striping meme regulier
rowmeans=img.mean(1); strip=float(np.std(rowmeans[1:]-rowmeans[:-1]))
print(f"   nrows={nrows} vmed={vmed:.1f} hmed={hmed:.1f} stripe(std drow)={strip:.1f}")
a2=img.astype(np.float32);lo,hi=np.percentile(a2,[1,99])
d=np.clip((a2-lo)/max(hi-lo,1)*255,0,255).astype(np.uint8)
Image.fromarray(d).resize((700,int(700*nrows/W))).save(a.out)
print("   ->",a.out)
