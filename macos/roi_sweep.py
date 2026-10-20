import time, numpy as np
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

def grab(W,H):
    pix=W*H*3//2; target=HDR+pix
    N,BUF=64,131072
    data=bytearray(); st={"a":N,"stop":False}
    def cb(t):
        if t.getStatus()==usb1.TRANSFER_COMPLETED: data.extend(t.getBuffer()[:t.getActualLength()])
        if not st["stop"] and len(data)<target:
            try:t.submit();return
            except usb1.USBError:pass
        st["a"]-=1
    ts=[]
    for _ in range(N):
        t=h.getTransfer();t.setBulk(EPIMG,BUF,callback=cb,timeout=2000);ts.append(t)
    cmd("arm")
    for t in ts:t.submit()
    cmd("start"); t0=time.monotonic()
    while st["a"]>0 and len(data)<target and time.monotonic()-t0<4:
        ctx.handleEventsTimeout(0.02)
    st["stop"]=True
    for t in ts:
        try:t.cancel()
        except Exception:pass
    t1=time.monotonic()
    while st["a"]>0 and time.monotonic()-t1<0.5: ctx.handleEventsTimeout(0.02)
    cmd("stop")
    row=W*3//2; nrows=min(H,(len(data)-HDR)//row)
    if nrows<4: return len(data),target,nrows,0,0
    raw=np.frombuffer(bytes(data[HDR:HDR+nrows*row]),np.uint8).astype(np.uint16).reshape(-1,3)
    p=np.empty(nrows*W,np.uint16)
    p[0::2]=raw[:,0]|((raw[:,1]&0x0F)<<8);p[1::2]=(raw[:,1]>>4)|(raw[:,2]<<4)
    img=p.reshape(nrows,W)
    vmed=float(np.median(np.abs(img[1:].astype(int)-img[:-1])))
    hmed=float(np.median(np.abs(img[:,1:].astype(int)-img[:,:-1])))
    return len(data),target,nrows,vmed,hmed

cmd("stop"); cmd("sfr off")
for side in (256,512,768,1024,1536,2048):
    W=side if side<2448 else 2448
    cx,cy=1224,1024
    l=((cx-W//2)//4)*4; t=((cy-side//2)//4)*4
    cmd("stop"); cmd(f"roi {l} {t} {l+W-1} {t+side-1}")
    Wr=int(cmd("image_width"));Hr=int(cmd("image_height"))
    got,tgt,nr,v,hh=grab(Wr,Hr)
    print(f"ROI {Wr}x{Hr}: recu {100*got/tgt:5.1f}%  vmed={v:6.1f} hmed={hh:5.1f}  {'PROPRE' if v<60 else 'strie'}")
h.releaseInterface(0);ctx.close()
