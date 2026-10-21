"""Test direct du TSI SDK via ctypes (sans la pile .NET ThorImage).
Charge thorlabs_tsi_camera_sdk.dll, ouvre le SDK, decouvre les cameras,
et lit modele + taille capteur. Valide la voie Python officielle.
"""
import ctypes as C
import os
import sys

BIN = r"C:\Program Files\Thorlabs\ThorImageCAM\Bin"

def main():
    os.add_dll_directory(BIN)
    os.chdir(BIN)
    dll_path = os.path.join(BIN, "thorlabs_tsi_camera_sdk.dll")
    print("loading", dll_path)
    sdk = C.cdll.LoadLibrary(dll_path)

    sdk.tl_camera_open_sdk.restype = C.c_int
    sdk.tl_camera_open_sdk.argtypes = []
    sdk.tl_camera_close_sdk.restype = C.c_int
    sdk.tl_camera_discover_available_cameras.restype = C.c_int
    sdk.tl_camera_discover_available_cameras.argtypes = [C.c_char_p, C.c_int]
    sdk.tl_camera_get_last_error.restype = C.c_char_p
    sdk.tl_camera_open_camera.restype = C.c_int
    sdk.tl_camera_open_camera.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    sdk.tl_camera_close_camera.restype = C.c_int
    sdk.tl_camera_close_camera.argtypes = [C.c_void_p]
    sdk.tl_camera_get_model.restype = C.c_int
    sdk.tl_camera_get_model.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
    sdk.tl_camera_get_sensor_width.restype = C.c_int
    sdk.tl_camera_get_sensor_width.argtypes = [C.c_void_p, C.POINTER(C.c_int)]
    sdk.tl_camera_get_sensor_height.restype = C.c_int
    sdk.tl_camera_get_sensor_height.argtypes = [C.c_void_p, C.POINTER(C.c_int)]
    sdk.tl_camera_get_bit_depth.restype = C.c_int
    sdk.tl_camera_get_bit_depth.argtypes = [C.c_void_p, C.POINTER(C.c_int)]

    rc = sdk.tl_camera_open_sdk()
    print("tl_camera_open_sdk ->", rc)
    if rc != 0:
        print("open_sdk failed")
        return

    buf = C.create_string_buffer(4096)
    rc = sdk.tl_camera_discover_available_cameras(buf, 4096)
    serials = buf.value.decode(errors="replace").strip()
    print("discover ->", rc, "| serials =", repr(serials))

    if serials:
        for sn in serials.split():
            handle = C.c_void_p()
            rc = sdk.tl_camera_open_camera(sn.encode(), C.byref(handle))
            print(f"  open_camera({sn}) ->", rc)
            if rc == 0 and handle:
                model = C.create_string_buffer(256)
                sdk.tl_camera_get_model(handle, model, 256)
                w = C.c_int(); h = C.c_int(); bd = C.c_int()
                sdk.tl_camera_get_sensor_width(handle, C.byref(w))
                sdk.tl_camera_get_sensor_height(handle, C.byref(h))
                sdk.tl_camera_get_bit_depth(handle, C.byref(bd))
                print(f"    model={model.value.decode(errors='replace')} "
                      f"sensor={w.value}x{h.value} bitdepth={bd.value}")
                sdk.tl_camera_close_camera(handle)
    else:
        err = sdk.tl_camera_get_last_error()
        print("  aucune camera detectee. last_error =",
              err.decode(errors="replace") if err else None)

    sdk.tl_camera_close_sdk()
    print("done.")

if __name__ == "__main__":
    main()
