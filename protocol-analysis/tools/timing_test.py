import time, usb1, numpy as np
VID,PID=0x1313,0x4001; EPO,EPI,EPIMG=0x02,0x82,0x83; HDR=16384
c=usb1.USBContext(); c.open()
h=c.openByVendorIDAndProductID(VID,PID); h.claimInterface(0)
def cmd(s,to=3000):
    h.bulkWrite(EPO,(s.encode()+b"\x00").ljust(1024,b"\x00"),to)
    return bytes(h.bulkRead(EPI,1024,to)).split(b"\x00")[0].decode("latin1").strip()
cmd("stop"); cmd("roi 0 0 2447 2047"); cmd("sfr off")
W=int(cmd("image_width"));H=int(cmd("image_height"))
cmd("exp 20000");cmd("hwtrig none");cmd("nframes 1")
target=HDR+W*H*3//2
buf=usb1.USBTransferHelper  # placeholder (unused)
cmd("arm")
t0=time.monotonic(); cmd("start")
# simple SYNCHRONOUS read in chunks of 1 MB, log of throughput over time
got=0; marks=[]
CHUNK=1024*1024
while got<target and time.monotonic()-t0<8:
    try:
        d=h.bulkRead(EPIMG, CHUNK, 500)
    except usb1.USBError as e:
        if "TIMEOUT" in str(e).upper():
            marks.append((time.monotonic()-t0, got, "timeout"))
            break
        raise
    got+=len(d)
    marks.append((time.monotonic()-t0, got, len(d)))
cmd("stop"); h.releaseInterface(0); c.close()
print(f"total {got}/{target} ({100*got/target:.1f}%)")
print("t(s)   cumul(MB)  chunk")
for t,g,n in marks[:40]:
    print(f"{t:5.2f}  {g/1e6:7.2f}   {n}")
