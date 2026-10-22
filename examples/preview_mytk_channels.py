"""Live preview of the four analyser channels (I0, I45, I90, I135) with myTk, and of the
angle (AoLP) and degree (DoLP) of linear polarization computed from them.

The channels stay uint16 until the last step: they are strided views of the mosaic (no
copy, no float), scaled to 8 bits (brightest 0.5% saturate) only to be drawn. AoLP and
DoLP are computed on the same reduced images, in float32.

    python examples/preview_mytk_channels.py --exp 10000

Start/Stop pauses the camera, the slider sets the exposure time (logarithmic, in ms), and
"Save as..." writes the next N consecutive full-size raw mosaics (uint16, 12-bit values):
a .tiff or .png is 16 bits, a .npy is a numpy array. With N > 1 the files are numbered
(name_0001.tiff, name_0002.tiff...). Close the window to stop. Needs myTk:  pip install mytk
"""
import argparse
import os
import threading
import time
from tkinter import filedialog

import numpy as np
from PIL import Image as PILImage
from mytk import App, Box, Button, Image, IntEntry, Label, Slider

from kiralux import KiraluxCameraDevice

NAMES = ("I0", "I45", "I90", "I135", "AoLP (hue: -90 to +90 deg)", "DoLP (white: 1)")
LAYOUT = ((0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (1, 2))        # (row, column) of each picture
STEP = 3                                          # show every 3rd pixel: still a view, still no copy
DARK = 0.1                                        # AoLP is not drawn where S0 is under this fraction of the display scale
LOG_MS = (-1, 3)                                  # exposure slider: 0.1 ms to 1000 ms, on a log scale
FILE_TYPES = (("TIFF, 16 bits", "*.tiff"), ("PNG, 16 bits", "*.png"), ("NumPy array", "*.npy"))


def polarization_pictures(views, top):
    """AoLP as a hue (black where there is almost no light) and DoLP as gray levels."""
    i0, i45, i90, i135 = (v.astype(np.float32) for v in views)
    s1, s2 = i0 - i90, i45 - i135
    s0 = (i0 + i45 + i90 + i135) / 2
    dolp = np.minimum(np.hypot(s1, s2) / np.maximum(s0, 1), 1)
    hue = ((np.arctan2(s2, s1) / (2 * np.pi) + 0.5) * 255).astype(np.uint8)    # 0.5 * arctan2, from -90 to +90 deg
    value = ((s0 > DARK * 2 * top) * 255).astype(np.uint8)
    aolp = PILImage.fromarray(np.dstack([hue, np.full_like(hue, 255), value]), "HSV").convert("RGB")
    return aolp, PILImage.fromarray((dolp * 255).astype(np.uint8))


def save_mosaic(mosaic, path):
    """Write one raw mosaic: a numpy array for .npy, a 16-bit image otherwise."""
    if path.endswith(".npy"):
        np.save(path, mosaic)
    else:
        PILImage.fromarray(mosaic).save(path)


def numbered(path, n, count):
    """The path itself for a single image, name_0001.ext, name_0002.ext... for several."""
    if count == 1:
        return path
    stem, extension = os.path.splitext(path)
    return f"{stem}_{n + 1:04d}{extension}"


class ChannelsApp(App):
    """The camera is only ever touched by the grab thread; the window just sets what it wants."""

    def __init__(self, camera, exposure_us):
        App.__init__(self, name="Kiralux live preview: channels", auto_position="top-left")
        self.camera = camera
        self.running = True
        self.pending = False                      # a frame is on its way to the window
        self.wanted = True                        # Start/Stop
        self.exposure_us = exposure_us            # what the slider asks for; the grab thread applies it
        self.save = None                          # {"path", "count", "mosaics"} while saving
        self.message = ""

        controls = Box(label="Camera")                  # a column on the left, the pictures on its right
        controls.grid_into(self.window, row=0, column=0, rowspan=4, padx=10, pady=10, sticky="n")
        self.start_button = Button("Stop", user_event_callback=self.toggle)
        self.start_button.grid_into(controls, row=0, column=0, padx=10, pady=(10, 5))
        Label("Exposure").grid_into(controls, row=1, column=0, padx=10, pady=(15, 0))
        self.exposure_label = Label(f"{exposure_us / 1000:g} ms")
        self.exposure_label.grid_into(controls, row=2, column=0, padx=10)
        self.slider = Slider(value=np.log10(exposure_us / 1000), minimum=LOG_MS[0], maximum=LOG_MS[1], width=160)
        self.slider.value_variable.trace_add("write", self.exposure_moved)    # the delegate only hears programmatic changes, not the mouse
        self.slider.grid_into(controls, row=3, column=0, padx=10, pady=5)
        Label("Save").grid_into(controls, row=4, column=0, padx=10, pady=(15, 0))
        self.count = IntEntry(value=1, minimum=1, maximum=1000, width=6)
        self.count.grid_into(controls, row=5, column=0, padx=10)
        Label("images").grid_into(controls, row=6, column=0, padx=10)
        self.save_button = Button("Save as...", user_event_callback=self.ask_where)
        self.save_button.grid_into(controls, row=7, column=0, padx=10, pady=(5, 10))

        blank = PILImage.new("L", (1224 // STEP, 1024 // STEP))
        self.images = []
        for name, (row, column) in zip(NAMES, LAYOUT):
            Label(name).grid_into(self.window, row=2 * row, column=column + 1, pady=(10, 0))
            image = Image(pil_image=blank)
            image.grid_into(self.window, row=2 * row + 1, column=column + 1, padx=5, pady=5)
            self.images.append(image)

        self.status = Label("")
        self.status.grid_into(self.window, row=4, column=0, columnspan=4, pady=(0, 10))

        self.grabber = threading.Thread(target=self.grab, daemon=True)
        self.grabber.start()

    # -- window side: ask, never touch the camera ----------------------------- #
    def toggle(self, event, button):
        self.wanted = not self.wanted
        button.label = "Stop" if self.wanted else "Start"

    def exposure_moved(self, *trace):
        """The exposure slider moved; its value is log10 of the exposure in ms."""
        milliseconds = 10 ** self.slider.value
        self.exposure_label.text = f"{milliseconds:.3g} ms"
        self.exposure_us = max(1, round(1000 * milliseconds))

    def ask_where(self, event, button):
        path = filedialog.asksaveasfilename(parent=self.window.widget, title="Save raw mosaics",
                                            defaultextension=".tiff", filetypes=FILE_TYPES)
        if path and self.save is None:
            self.wanted = True                    # the images come from the stream
            self.start_button.label = "Stop"
            self.save = {"path": path, "count": self.count.value, "mosaics": []}

    def show(self, pictures, text):
        for image, picture in zip(self.images, pictures):
            image.pil_image = picture
            image.update_display()
        self.status.text = text
        self.pending = False

    # -- grab thread: the only one talking to the camera ---------------------- #
    def grab(self):
        applied = None
        while self.running:
            try:
                if self.exposure_us != applied:
                    applied = self.exposure_us
                    self.camera.setExposure(applied)     # re-arms a running stream
                if self.wanted != self.camera.streaming:
                    self.camera.startStreaming() if self.wanted else self.camera.stopStreaming()
                if not self.camera.streaming:
                    time.sleep(0.05)
                    continue
                self.grab_one()
            except Exception as error:                   # a timeout stops the stream; the loop starts it again
                self.message = f"{type(error).__name__}: {error}"
                time.sleep(0.5)

    def grab_one(self):
        start = time.perf_counter()
        frame = self.camera.snap()
        snapped = time.perf_counter()
        if self.save is not None:
            self.collect(frame.mosaic)
        views = [c[::STEP, ::STEP] for c in frame.raw_channels]
        top = max(int(np.percentile(v, 99.5)) for v in views) or 1   # one scale for all four, to keep their ratios (uint32: 4095 * 255 overflows uint16)
        pictures = [PILImage.fromarray((np.minimum(v, top).astype(np.uint32) * 255 // top).astype(np.uint8)) for v in views]
        pictures += polarization_pictures(views, top)
        done = time.perf_counter()
        text = (f"{1 / (done - start):.1f} frames/s   capture {1000 * (snapped - start):.0f} ms"
                f"   to pictures {1000 * (done - snapped):.1f} ms   {self.message}")
        if not self.pending:                      # the window is behind: drop this frame, keep capturing
            self.pending = True
            self.schedule_on_main_thread(self.show, args=[pictures, text])

    def collect(self, mosaic):
        """Keep the next frames of the stream; write them all when there are enough."""
        request = self.save
        request["mosaics"].append(mosaic)
        self.message = f"saving {len(request['mosaics'])}/{request['count']}"
        if len(request["mosaics"]) == request["count"]:
            for n, saved in enumerate(request["mosaics"]):
                save_mosaic(saved, numbered(request["path"], n, request["count"]))
            self.message = f"saved {request['count']} image(s) to {request['path']}"
            self.save = None

    def stop(self):
        self.running = False
        self.grabber.join()          # let the read in flight finish; shutdownDevice() then stops the stream


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=int, default=10_000, help="exposure in microseconds")
    args = ap.parse_args()

    camera = KiraluxCameraDevice()
    camera.initializeDevice()
    app = ChannelsApp(camera, args.exp)
    try:
        app.mainloop()
    finally:
        app.stop()
        camera.shutdownDevice()


if __name__ == "__main__":
    main()
