"""Acquiert UNE frame de la camera TSI via ctypes et l'enregistre en PNG.
Preuve que la voie Python officielle (tl_camera_*) permet l'acquisition complete.
"""
import ctypes as C
import os
import time
import numpy as np
from PIL import Image

BIN = r"C:\Program Files\Thorlabs\ThorImageCAM\Bin"
OUT = r"C:\Mac\Home\ThorImageRE\tools\camera_frame.png"
EXPOSURE_US = 20000  # 20 ms

def main():
    os.add_dll_directory(BIN); os.chdir(BIN)
    sdk = C.cdll.LoadLibrary(os.path.join(BIN, "thorlabs_tsi_camera_sdk.dll"))

    # signatures
    sdk.tl_camera_open_sdk.restype = C.c_int
    sdk.tl_camera_discover_available_cameras.argtypes = [C.c_char_p, C.c_int]
    sdk.tl_camera_open_camera.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    sdk.tl_camera_set_exposure_time.argtypes = [C.c_void_p, C.c_longlong]
    sdk.tl_camera_set_operation_mode.argtypes = [C.c_void_p, C.c_int]
    sdk.tl_camera_set_frames_per_trigger_zero_for_unlimited.argtypes = [C.c_void_p, C.c_uint]
    sdk.tl_camera_set_image_poll_timeout.argtypes = [C.c_void_p, C.c_int]
    sdk.tl_camera_arm.argtypes = [C.c_void_p, C.c_int]
    sdk.tl_camera_issue_software_trigger.argtypes = [C.c_void_p]
    sdk.tl_camera_disarm.argtypes = [C.c_void_p]
    sdk.tl_camera_get_image_width.argtypes = [C.c_void_p, C.POINTER(C.c_int)]
    sdk.tl_camera_get_image_height.argtypes = [C.c_void_p, C.POINTER(C.c_int)]
    sdk.tl_camera_get_pending_frame_or_null.argtypes = [
        C.c_void_p, C.POINTER(C.POINTER(C.c_ushort)), C.POINTER(C.c_int),
        C.POINTER(C.POINTER(C.c_ubyte)), C.POINTER(C.c_int)]
    sdk.tl_camera_close_camera.argtypes = [C.c_void_p]

    assert sdk.tl_camera_open_sdk() == 0, "open_sdk failed"
    buf = C.create_string_buffer(4096)
    sdk.tl_camera_discover_available_cameras(buf, 4096)
    sn = buf.value.split()[0]
    print("camera", sn.decode())

    h = C.c_void_p()
    assert sdk.tl_camera_open_camera(sn, C.byref(h)) == 0, "open_camera failed"

    sdk.tl_camera_set_exposure_time(h, EXPOSURE_US)
    sdk.tl_camera_set_operation_mode(h, 0)                       # 0 = software triggered
    sdk.tl_camera_set_frames_per_trigger_zero_for_unlimited(h, 1)
    sdk.tl_camera_set_image_poll_timeout(h, 3000)               # 3 s

    w = C.c_int(); ht = C.c_int()
    sdk.tl_camera_get_image_width(h, C.byref(w))
    sdk.tl_camera_get_image_height(h, C.byref(ht))
    W, H = w.value, ht.value
    print(f"image {W}x{H}, exposure {EXPOSURE_US} us")

    sdk.tl_camera_arm(h, 2)
    sdk.tl_camera_issue_software_trigger(h)

    img_ptr = C.POINTER(C.c_ushort)()
    frame_count = C.c_int()
    meta_ptr = C.POINTER(C.c_ubyte)()
    meta_size = C.c_int()

    frame = None
    t0 = time.time()
    while time.time() - t0 < 5:
        rc = sdk.tl_camera_get_pending_frame_or_null(
            h, C.byref(img_ptr), C.byref(frame_count),
            C.byref(meta_ptr), C.byref(meta_size))
        if rc == 0 and img_ptr:
            n = W * H
            arr = np.ctypeslib.as_array(img_ptr, shape=(n,)).copy()
            frame = arr.reshape((H, W))
            print("frame recue, frame_count =", frame_count.value)
            break
        time.sleep(0.01)

    sdk.tl_camera_disarm(h)
    sdk.tl_camera_close_camera(h)
    sdk.tl_camera_close_sdk()

    if frame is None:
        print("AUCUNE frame recue")
        return

    print(f"stats: min={frame.min()} max={frame.max()} mean={frame.mean():.1f} dtype={frame.dtype}")
    # 12 bits -> 8 bits pour visualisation
    lo, hi = np.percentile(frame, [1, 99])
    disp = np.clip((frame.astype(np.float32) - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    Image.fromarray(disp, mode="L").save(OUT)
    print("saved", OUT)

if __name__ == "__main__":
    main()
