import sys, usb1
def log(*a): print(*a, flush=True)
log("python", sys.version.split()[0], "usb1", getattr(usb1, "__version__", "?"))
c = usb1.USBContext(); c.open()
log("context ok")
d = c.openByVendorIDAndProductID(0x1313, 0x4001)
log("device open:", d is not None)
if d:
    try:
        if d.kernelDriverActive(0):
            log("kernel driver active -> detaching")
            d.detachKernelDriver(0)
    except Exception as e:
        log("detach:", e)
    d.claimInterface(0)
    log("interface claimed")
    d.bulkWrite(0x02, b"sernum".ljust(1024, b"\x00"), 2000)
    log("wrote sernum")
    r = bytes(d.bulkRead(0x82, 1024, 2000)).split(b"\x00")[0].decode("latin1").strip()
    log("sernum =", r)
    d.bulkWrite(0x02, b"image_width".ljust(1024, b"\x00"), 2000)
    w = bytes(d.bulkRead(0x82, 1024, 2000)).split(b"\x00")[0].decode("latin1").strip()
    d.bulkWrite(0x02, b"image_height".ljust(1024, b"\x00"), 2000)
    hh = bytes(d.bulkRead(0x82, 1024, 2000)).split(b"\x00")[0].decode("latin1").strip()
    log("dims =", w, "x", hh)
    d.releaseInterface(0)
c.close()
log("done")
