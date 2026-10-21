import sys, time
import usb1, numpy as np
VID,PID=0x1313,0x4001; EPO,EPI,EPIMG=0x02,0x82,0x83; HDR=16384
N,BUF=256,16384
c=usb1.USBContext(); c.open()
h=c.openByVendorIDAndProductID(VID,PID); h.claimInterface(0)
def cmd(s,to=3000):
    h.bulkWrite(EPO,(s.encode()+b"\x00").ljust(1024,b"\x00"),to)
    return bytes(h.bulkRead(EPI,1024,to)).split(b"\x00")[0].decode("latin1").strip()
cmd("stop"); cmd("roi 0 0 2447 2047"); cmd("sfr off"); cmd("hbin 1"); cmd("vbin 1")
W=int(cmd("image_width"));H=int(cmd("image_height"))
cmd("exp %d"%(int(sys.argv[1]) if len(sys.argv)>1 else 20000));cmd("hwtrig none");cmd("nframes 1")
target=HDR+W*H*3//2
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
while st["a"]>0 and len(data)<target and time.monotonic()-t0<4:
    c.handleEventsTimeout(0.005)
st["stop"]=True
for t in ts:
    try:t.cancel()
    except Exception:pass
t1=time.monotonic()
while st["a"]>0 and time.monotonic()-t1<0.3:c.handleEventsTimeout(0.01)
cmd("stop"); h.releaseInterface(0); c.close()
open("raw_clean.bin","wb").write(bytes(data))
print("saved raw_clean.bin %d/%d (%.1f%%) W=%d H=%d"%(len(data),target,100*len(data)/target,W,H))
