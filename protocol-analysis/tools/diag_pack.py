from camera_usb import ThorCam
c = ThorCam(verbose=False)
for q in ["imgpack", "imgpack.disc", "pixel_byte_ordering", "pixel_byte_ordering.disc",
          "image_dims", "pixel_bit_depth", "pixel_size", "sensor_readout_time",
          "polar_phase", "color"]:
    try:
        print(f"{q:24} -> {c.cmd(q)!r}")
    except Exception as e:
        print(f"{q:24} !! {e}")
c.close()
