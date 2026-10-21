from camera_usb import ThorCam
c = ThorCam(verbose=False)
for q in ["pixel_clock_count_base", "pixel_clock_count_base.disc",
          "frametime", "frametime.disc", "sensor_readout_time",
          "camera_radix", "sfr", "sfr.disc", "debug_radix",
          "imgpack", "pixel_size", "roi"]:
    try: print(f"{q:28} -> {c.cmd(q)!r}")
    except Exception as e: print(f"{q:28} !! {e}")
c.close()
