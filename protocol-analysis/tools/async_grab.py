"""Acquisition with ASYNCHRONOUS USB transfers (python-libusb1).
Resolves the data loss of synchronous reads on the USB3 burst.
"""
import sys
import numpy as np
from PIL import Image
import usb1

VID, PID = 0x1313, 0x4001
EP_CMD_OUT, EP_CMD_IN, EP_IMG_IN = 0x02, 0x82, 0x83
HDR = 16384
N_TRANSFERS = 48
BUF = 256 * 1024  # 48 x 256 KB = 12 MB in flight > frame size (no overflow)

class AsyncCam:
    def __init__(self):
        self.ctx = usb1.USBContext(); self.ctx.open()
        self.h = self.ctx.openByVendorIDAndProductID(VID, PID)
        if self.h is None:
            raise RuntimeError("camera not found")
        try: self.h.setAutoDetachKernelDriver(True)
        except Exception: pass
        self.h.claimInterface(0)

    def cmd(self, s, timeout=2000):
        self.h.bulkWrite(EP_CMD_OUT, (s.encode()+b"\x00").ljust(1024, b"\x00"), timeout)
        r = self.h.bulkRead(EP_CMD_IN, 1024, timeout)
        resp = bytes(r).split(b"\x00")[0].decode("latin1").strip()
        if resp.startswith("error"):
            raise RuntimeError(f"{s!r} -> {resp}")
        return resp

    def grab(self, exposure_us=20000, full=True):
        self.cmd("stop")
        if full:
            self.cmd("roi 0 0 2447 2047")   # full frame
        self.cmd(f"exp {int(exposure_us)}")
        self.cmd("hwtrig none")
        self.cmd("nframes 1")
        W = int(self.cmd("image_width")); H = int(self.cmd("image_height"))
        pix = W * H * 3 // 2
        target = HDR + pix

        data = bytearray()
        state = {"active": N_TRANSFERS, "stop": False}
        def cb(t):
            st = t.getStatus()
            if st == usb1.TRANSFER_COMPLETED:
                data.extend(t.getBuffer()[:t.getActualLength()])
            # re-submit as long as we don't have the whole frame (even on timeout: the bottom
            # of sensor arrives after a readout delay)
            if not state["stop"] and len(data) < target:
                try: t.submit(); return
                except usb1.USBError: pass
            state["active"] -= 1

        transfers = []
        for _ in range(N_TRANSFERS):
            t = self.h.getTransfer()
            t.setBulk(EP_IMG_IN, BUF, callback=cb, timeout=1500)
            transfers.append(t)

        self.cmd("arm"); self.cmd("start")
        for t in transfers:
            t.submit()
        import time as _t
        t0 = _t.monotonic()
        while state["active"] > 0 and len(data) < target and (_t.monotonic() - t0) < 10:
            self.ctx.handleEventsTimeout(0.1)
        state["stop"] = True
        # let the in-flight transfers finish cleanly
        for _ in range(N_TRANSFERS):
            if state["active"] <= 0: break
            self.ctx.handleEventsTimeout(0.05)
        self.cmd("stop")

        print(f"received {len(data)}/{target} bytes")
        row_bytes = W * 3 // 2
        avail = len(data) - HDR
        nrows = min(H, max(0, avail // row_bytes))
        pix_bytes = bytes(data[HDR:HDR + nrows * row_bytes])
        raw = np.frombuffer(pix_bytes, np.uint8).astype(np.uint16)
        b = raw.reshape(-1, 3)
        p = np.empty(nrows * W, np.uint16)
        p[0::2] = b[:, 0] | ((b[:, 1] & 0x0F) << 8)
        p[1::2] = (b[:, 1] >> 4) | (b[:, 2] << 4)
        print(f"-> {nrows} lines decoded")
        return p.reshape(nrows, W)

    def close(self):
        try: self.h.releaseInterface(0)
        except Exception: pass
        self.ctx.close()

if __name__ == "__main__":
    cam = AsyncCam()
    img = cam.grab(20000)
    cam.close()
    print(f"image {img.shape} min={img.min()} max={img.max()} mean={img.mean():.1f}")
    vmed = np.median(np.abs(img[1:].astype(int)-img[:-1])); hmed = np.median(np.abs(img[:,1:].astype(int)-img[:,:-1]))
    print(f"vmed={vmed:.1f} hmed={hmed:.1f}  (if ~equal and low = clean!)")
    a = img.astype(np.float32); lo, hi = np.percentile(a, [1, 99])
    d = np.clip((a-lo)/max(hi-lo,1)*255, 0, 255).astype(np.uint8)
    Image.fromarray(d, "L").resize((1400, int(1400*img.shape[0]/img.shape[1])), Image.LANCZOS).save("async_frame.png")
    print("-> async_frame.png")
