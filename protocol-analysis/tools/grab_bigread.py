import time, usb.core, usb.util
from camera_usb import ThorCam, EP_IMG_IN

c = ThorCam(verbose=False)
c.cmd("stop"); c.cmd("exp 20000"); c.cmd("hwtrig none"); c.cmd("nframes 1")
W = int(c.cmd("image_width")); H = int(c.cmd("image_height"))
expected = 16384 + W * H * 3 // 2   # header + 12-bit packed (hypothesis)

# single large buffer: libusb fills internally, no Python loop gap
c.cmd("arm"); c.cmd("start")
buf = usb.util.create_buffer(16 * 1024 * 1024)
t0 = time.time()
try:
    n = c.dev.read(EP_IMG_IN, buf, timeout=5000)
except usb.core.USBError as e:
    n = 0; print("read err", e)
dt = time.time() - t0
c.cmd("stop"); c.close()

data = bytes(buf[:n])
open("raw_big.bin", "wb").write(data)
print(f"read {n} bytes in {dt*1000:.0f} ms  (expected ~{expected})  throughput={n/dt/1e6:.1f} MB/s")
print("header:", data[:16].hex())
