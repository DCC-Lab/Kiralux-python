"""Live preview of the four analyser channels (I0, I45, I90, I135) with myTk, and of the
angle (AoLP) and degree (DoLP) of linear polarization computed from them.

The channels stay uint16 until the last step: they are strided views of the mosaic (no
copy, no float), scaled to 8 bits (brightest 0.5% saturate) only to be drawn. AoLP and
DoLP are computed on the same reduced images, in float32.

    python examples/preview_mytk_channels.py --exp 10000

Start/Stop pauses the camera, the slider sets the exposure time (logarithmic, in ms), and
"Save as..." keeps the next N consecutive full-size raw mosaics in a deque, averages them and
writes the average (float32, in ADU: a 32-bit .tiff or a .npy). Close the window to stop.
Needs myTk:  pip install mytk
"""
import argparse
import threading
import time
from collections import deque
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
MAX_IMAGES = 100                                  # a raw mosaic is 10 MB: they all wait in memory until averaged
FILE_TYPES = (("TIFF, 32-bit float", "*.tiff"), ("NumPy array, float32", "*.npy"))


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


def save_average(mosaics, path):
    """Average the mosaics (float32, in ADU) and write the result: a numpy array for .npy, a float TIFF otherwise."""
    average = np.zeros(mosaics[0].shape, np.float32)
    for mosaic in mosaics:
        average += mosaic
    average /= len(mosaics)
    if path.endswith(".npy"):
        np.save(path, average)
    else:
        PILImage.fromarray(average).save(path)


class ChannelsApp(App):
    """The camera is only ever touched by the grab thread; the window just sets what it wants."""

    def __init__(self, camera, exposure_us):
        App.__init__(self, name="Kiralux live preview: channels", auto_position="top-left")
        self.camera = camera
        self.running = True
        self.pending = False                      # a frame is on its way to the window
        self.wanted = True                        # Start/Stop
        self.exposure_us = exposure_us            # what the slider asks for; the grab thread applies it
        self.save = None                          # {"path", "mosaics"} while saving: a deque of the next N frames
        self.message = ""

        # what the controls show and hold, bound to them (changing one changes the other)
        self.log_exposure = np.log10(exposure_us / 1000)
        self.exposure_text = f"{exposure_us / 1000:.3g} ms"
        self.button_text = "Stop"
        self.images_to_save = 1
        self.status_text = ""

        controls = Box(label="Camera")                  # a column on the left, the pictures on its right
        controls.grid_into(self.window, row=0, column=0, rowspan=4, padx=10, pady=10, sticky="n")
        self.start_button = Button(self.button_text, user_event_callback=self.toggle)
        self.start_button.grid_into(controls, row=0, column=0, padx=10, pady=(10, 5))
        Label("Exposure").grid_into(controls, row=1, column=0, padx=10, pady=(15, 0))
        exposure_label = Label(self.exposure_text)
        exposure_label.grid_into(controls, row=2, column=0, padx=10)
        self.slider = Slider(value=self.log_exposure, minimum=LOG_MS[0], maximum=LOG_MS[1], width=160)
        self.slider.grid_into(controls, row=3, column=0, padx=10, pady=5)
        Label("Save").grid_into(controls, row=4, column=0, padx=10, pady=(15, 0))
        count = IntEntry(value=self.images_to_save, minimum=1, maximum=MAX_IMAGES, width=6)
        count.grid_into(controls, row=5, column=0, padx=10)
        Label("images (averaged)").grid_into(controls, row=6, column=0, padx=10)
        Button("Save as...", user_event_callback=self.ask_where).grid_into(controls, row=7, column=0, padx=10, pady=(5, 10))

        blank = PILImage.new("L", (1224 // STEP, 1024 // STEP))
        self.images = []
        for name, (row, column) in zip(NAMES, LAYOUT):
            Label(name).grid_into(self.window, row=2 * row, column=column + 1, pady=(10, 0))
            image = Image(pil_image=blank)
            image.grid_into(self.window, row=2 * row + 1, column=column + 1, padx=5, pady=5)
            self.images.append(image)

        status = Label("")
        status.grid_into(self.window, row=4, column=0, columnspan=4, pady=(0, 10))

        self.bind_property_to_widget_value("log_exposure", self.slider)
        self.bind_property_to_widget_value("exposure_text", exposure_label)
        self.bind_property_to_widget_value("button_text", self.start_button)
        self.bind_property_to_widget_value("images_to_save", count)
        self.bind_property_to_widget_value("status_text", status)
        self.add_observer(self, "log_exposure")

        self.grabber = threading.Thread(target=self.grab, daemon=True)
        self.grabber.start()

    # -- window side: ask, never touch the camera ----------------------------- #
    def toggle(self, event, button):
        self.wanted = not self.wanted
        self.button_text = "Stop" if self.wanted else "Start"

    def observed_property_changed(self, observed_object, observed_property_name, new_value, context):
        """The exposure slider moved (log10 of the exposure in ms), by the mouse or by the program."""
        if observed_property_name == "log_exposure":
            milliseconds = 10 ** new_value
            self.exposure_text = f"{milliseconds:.3g} ms"
            self.exposure_us = max(1, round(1000 * milliseconds))
        super().observed_property_changed(observed_object, observed_property_name, new_value, context)

    def ask_where(self, event, button):
        path = filedialog.asksaveasfilename(parent=self.window.widget, title="Save the average of the next images",
                                            defaultextension=".tiff", filetypes=FILE_TYPES)
        if path and self.save is None:
            self.wanted = True                    # the images come from the stream
            self.button_text = "Stop"
            self.save = {"path": path, "mosaics": deque(maxlen=self.images_to_save)}

    def show(self, pictures, text):
        for image, picture in zip(self.images, pictures):
            image.pil_image = picture
            image.update_display()
        self.status_text = text
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
        """Keep the next frames of the stream in the deque; average and write them when it is full."""
        request = self.save
        mosaics = request["mosaics"]
        mosaics.append(mosaic)
        self.message = f"saving {len(mosaics)}/{mosaics.maxlen}"
        if len(mosaics) == mosaics.maxlen:
            save_average(mosaics, request["path"])
            self.message = f"saved the average of {len(mosaics)} image(s) to {request['path']}"
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
