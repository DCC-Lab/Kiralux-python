"""Live preview of the four analyser channels (I0, I45, I90, I135) with myTk, and of the
angle (AoLP) and degree (DoLP) of linear polarization computed from them.

The channels stay uint16 until the last step: they are strided views of the mosaic (no
copy, no float), scaled to 8 bits (brightest 0.5% saturate) only to be drawn. AoLP and
DoLP are computed on the same reduced images, in float32.

    python examples/preview_mytk_channels.py --exp 10000

Start/Stop pauses the camera, the slider sets the exposure time (logarithmic, in ms), and
"Save as..." waits for N fresh frames, averages the last N full-size raw mosaics (a deque
that never holds more than N) -- entirely in float32 -- then decodes the average into the
four analyser channels plus AoLP and DoLP, and writes all six as 16-bit TIFFs (rounded only
at this last step) in a new folder named after the chosen path (its extension, if any, is
dropped; the folder is created next to it). Close the window to stop.
Needs myTk:  pip install mytk
"""
import argparse
import os
import threading
import time
from collections import deque
from tkinter import filedialog

import numpy as np
from PIL import Image as PILImage
from mytk import App, Box, Button, Checkbox, Image, IntEntry, Label, Slider

from kiralux import KiraluxCameraDevice, KiraluxDebug, PolarFrame

NAMES = ("I0", "I45", "I90", "I135", "AoLP (hue: -90 to +90 deg)", "DoLP (white: 1)")
LAYOUT = ((0, 0), (0, 1), (1, 0), (1, 1), (0, 2), (1, 2))        # (row, column) of each picture
STEP = 3                                          # show every 3rd pixel: still a view, still no copy
DARK = 0.1                                        # AoLP is not drawn where S0 is under this fraction of the display scale
LOG_MS = (-1, 3)                                  # exposure slider: 0.1 ms to 1000 ms, on a log scale
FULL_12_BIT, FULL_16_BIT = 4095, 65535            # the TIFFs use the whole 16-bit scale: 4095 ADU is written as 65535
MAX_IMAGES = 100                                  # a raw mosaic is 10 MB: they all wait in memory until averaged
FILE_TYPES = (("Folder name", "*.tiff"),)
CHANNEL_NAMES = ("I0", "I45", "I90", "I135")


def aolp_color_image(aolp_deg, dolp, lit, dolp_brightness, dolp_top=None):
    """AoLP as a hue (HSV), black where there is almost no light.

    By default (`dolp_brightness=False`) the brightness (HSV "value") is a flat on/off
    mask from total intensity (S0) alone: any lit pixel shows a fully-saturated color,
    even where DoLP is near zero -- under circular illumination (QWP) that is mostly
    noise, since the hue (atan2(S2,S1)) is essentially random when S1,S2 are both small.
    With `dolp_brightness=True`, the value channel is DoLP itself instead (stretched to
    `dolp_top`, its 99.5th percentile by default): only pixels with a real, resolvable
    polarization signal show color, scaled by how strong that signal is.
    """
    hue = (((aolp_deg / 180.0) + 0.5) * 255).astype(np.uint8)
    if dolp_brightness:
        if dolp_top is None:
            dolp_top = max(float(np.percentile(dolp, 99.5)), 1e-6)
        value = (lit * np.clip(dolp / dolp_top, 0, 1) * 255).astype(np.uint8)
    else:
        value = (lit * 255).astype(np.uint8)
    return PILImage.fromarray(np.dstack([hue, np.full_like(hue, 255), value]), "HSV").convert("RGB")


def polarization_pictures(views, top, dolp_brightness=False):
    """Compute AoLP (as a color picture) and DoLP (as gray levels) for the live preview.

    Also returns the underlying float arrays (angle in degrees, DoLP) and the "lit"
    mask (same threshold as the default black cutoff), so the caller can compute
    honest statistics -- excluding pixels too dim for AoLP to mean anything.
    """
    i0, i45, i90, i135 = (v.astype(np.float32) for v in views)
    s1, s2 = i0 - i90, i45 - i135
    s0 = (i0 + i45 + i90 + i135) / 2
    dolp = np.minimum(np.hypot(s1, s2) / np.maximum(s0, 1), 1)
    aolp_deg = np.degrees(0.5 * np.arctan2(s2, s1))
    lit = s0 > DARK * 2 * top
    aolp = aolp_color_image(aolp_deg, dolp, lit, dolp_brightness)
    return aolp, PILImage.fromarray((dolp * 255).astype(np.uint8)), aolp_deg, dolp, lit


def circular_mean_std_deg(angles_deg, period=180.0):
    """Mean/std of an angle that wraps every `period` degrees (AoLP wraps at 180)."""
    theta = np.radians(angles_deg) * (360.0 / period)
    mean_vec = np.exp(1j * theta).mean()
    mean_deg = np.degrees(np.angle(mean_vec)) * (period / 360.0)
    r = np.clip(np.abs(mean_vec), 1e-9, 1.0)
    std_deg = np.degrees(np.sqrt(-2 * np.log(r))) * (period / 360.0)
    return mean_deg, std_deg


def stats_text(name, values, lit=None, circular=False):
    v = values[lit] if lit is not None else values.ravel()
    if v.size == 0:
        return f"{name}: no lit pixels"
    if circular:
        mean, std = circular_mean_std_deg(v)
        return f"mean {mean:+.3f}°  std {std:.3f}°"
    return f"mean {v.mean():.3f}  std {v.std():.3f}"


def save_measurement(mosaics, chosen_path):
    """Average the mosaics in float32, decode channels/AoLP/DoLP (still float32), and only
    then round each to a 16-bit TIFF, in a new folder named after `chosen_path` (any
    extension dropped). Returns the folder path.

    Encoding of the 16-bit files (documented again in readme.txt inside the folder):
      I0/I45/I90/I135.tiff : raw ADU (0..4095) stretched to the full 16-bit range (x 65535/4095)
      AoLP.tiff             : degrees in [-90, 90) mapped to [0, 65535]
      DoLP.tiff              : [0, 1] mapped to [0, 65535]
      AoLP_color.tiff        : the same hue picture as the live preview (8-bit RGB), brightness
                               scaled by DoLP -- not raw data, for a quick look / figures
    """
    average = np.zeros(mosaics[0].shape, np.float32)
    for mosaic in mosaics:
        average += mosaic
    average /= len(mosaics)                            # still float32 throughout

    frame = PolarFrame(average)
    i0, i45, i90, i135 = frame.raw_channels             # float32 views of `average`, ADU (0..4095)
    s0 = frame.stokes[0]
    aolp_deg, dolp = frame.aolp, frame.dolp              # float32, degrees and [0,1]
    lit = s0 > DARK * max(float(np.percentile(c, 99.5)) for c in (i0, i45, i90, i135))

    folder = os.path.splitext(chosen_path)[0]
    os.makedirs(folder, exist_ok=True)

    for name, channel in zip(CHANNEL_NAMES, (i0, i45, i90, i135)):
        scaled = np.rint(channel * (FULL_16_BIT / FULL_12_BIT)).astype(np.uint16)
        PILImage.fromarray(scaled).save(os.path.join(folder, f"{name}.tiff"))

    aolp_16 = np.rint((aolp_deg + 90.0) * (FULL_16_BIT / 180.0)).clip(0, FULL_16_BIT).astype(np.uint16)
    PILImage.fromarray(aolp_16).save(os.path.join(folder, "AoLP.tiff"))

    dolp_16 = np.rint(np.clip(dolp, 0, 1) * FULL_16_BIT).astype(np.uint16)
    PILImage.fromarray(dolp_16).save(os.path.join(folder, "DoLP.tiff"))

    aolp_color_image(aolp_deg, dolp, lit, dolp_brightness=True).save(os.path.join(folder, "AoLP_color.tiff"))

    with open(os.path.join(folder, "readme.txt"), "w") as f:
        f.write(f"Average of {len(mosaics)} raw mosaics, computed in float32, rounded to 16-bit on save.\n\n"
                f"I0/I45/I90/I135.tiff : raw ADU (0..4095) stretched to the full 16-bit range (x {FULL_16_BIT/FULL_12_BIT:.6f})\n"
                f"AoLP.tiff             : degrees in [-90, 90) mapped to [0, 65535]  "
                f"-> degrees = pixel/65535*180 - 90\n"
                f"DoLP.tiff             : [0, 1] mapped to [0, 65535]  -> dolp = pixel/65535\n"
                f"AoLP_color.tiff        : 8-bit RGB, hue = AoLP, brightness = DoLP (same palette as the live "
                f"preview) -- a picture, not raw data\n")

    return folder


class ChannelsApp(App):
    """The camera is only ever touched by the grab thread; the window just sets what it wants."""

    def __init__(self, camera, exposure_us):
        App.__init__(self, name="Kiralux live preview: channels", auto_position="top-left")
        self.camera = camera
        self.running = True
        self.pending = False                      # a frame is on its way to the window
        self.wanted = True                        # Start/Stop
        self.exposure_us = exposure_us            # what the slider asks for; the grab thread applies it
        self.recent = deque(maxlen=1)             # always the last N raw mosaics, N being the number of images to save
        self.save = None                          # {"path", "remaining"} while waiting for N fresh frames
        self.message = ""

        # what the controls show and hold, bound to them (changing one changes the other)
        self.log_exposure = np.log10(exposure_us / 1000)
        self.exposure_text = f"{exposure_us / 1000:.3g} ms"
        self.button_text = "Stop"
        self.images_to_save = 1
        self.status_text = ""
        self.dolp_brightness = False              # AoLP hue brightness: flat S0 mask, or scaled by DoLP

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
        dolp_checkbox = Checkbox(label="AoLP brightness = DoLP")
        dolp_checkbox.grid_into(controls, row=8, column=0, padx=10, pady=(5, 10))

        blank = PILImage.new("L", (1224 // STEP, 1024 // STEP))
        self.images = []
        self.stat_labels = []
        for name, (row, column) in zip(NAMES, LAYOUT):
            base = 3 * row                            # title / image / stats, per panel row
            Label(name).grid_into(self.window, row=base, column=column + 1, pady=(10, 0))
            image = Image(pil_image=blank)
            image.grid_into(self.window, row=base + 1, column=column + 1, padx=5, pady=5)
            self.images.append(image)
            stat_label = Label("")                    # mean/std of that picture, updated every frame
            stat_label.grid_into(self.window, row=base + 2, column=column + 1, pady=(0, 5))
            self.stat_labels.append(stat_label)

        status = Label("")
        status.grid_into(self.window, row=6, column=0, columnspan=4, pady=(0, 10))

        self.bind_property_to_widget_value("log_exposure", self.slider)
        self.bind_property_to_widget_value("exposure_text", exposure_label)
        self.bind_property_to_widget_value("button_text", self.start_button)
        self.bind_property_to_widget_value("images_to_save", count)
        self.bind_property_to_widget_value("status_text", status)
        self.bind_property_to_widget_value("dolp_brightness", dolp_checkbox)
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
        path = filedialog.asksaveasfilename(parent=self.window.widget,
                                            title="Name the folder for the next images",
                                            defaultextension=".tiff", filetypes=FILE_TYPES)
        if path and self.save is None:
            self.wanted = True                    # the images come from the stream
            self.button_text = "Stop"
            self.save = {"path": path, "remaining": self.images_to_save}

    def show(self, pictures, stats, text):
        for image, picture in zip(self.images, pictures):
            image.pil_image = picture
            image.update_display()
        for label, stat in zip(self.stat_labels, stats):
            label.text = stat
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
        self.collect(frame.mosaic)
        views = [c[::STEP, ::STEP] for c in frame.raw_channels]
        top = max(int(np.percentile(v, 99.5)) for v in views) or 1   # one scale for all four, to keep their ratios (uint32: 4095 * 255 overflows uint16)
        pictures = [PILImage.fromarray((np.minimum(v, top).astype(np.uint32) * 255 // top).astype(np.uint8)) for v in views]
        aolp_pic, dolp_pic, aolp_deg, dolp, lit = polarization_pictures(views, top, dolp_brightness=self.dolp_brightness)
        pictures += [aolp_pic, dolp_pic]
        stats = [stats_text(name, v) for name, v in zip(NAMES[:4], views)]
        stats.append(stats_text("AoLP", aolp_deg, lit=lit, circular=True))
        stats.append(stats_text("DoLP", dolp, lit=lit))
        done = time.perf_counter()
        text = (f"{1 / (done - start):.1f} frames/s   capture {1000 * (snapped - start):.0f} ms"
                f"   to pictures {1000 * (done - snapped):.1f} ms   {self.message}")
        if not self.pending:                      # the window is behind: drop this frame, keep capturing
            self.pending = True
            self.schedule_on_main_thread(self.show, args=[pictures, stats, text])

    def collect(self, mosaic):
        """Keep the last N frames of the stream, and when a save is waiting for N fresh ones, average and write them."""
        if self.recent.maxlen != self.images_to_save:
            self.recent = deque(self.recent, maxlen=self.images_to_save)
        self.recent.append(mosaic)
        request = self.save
        if request is None:
            return
        request["remaining"] -= 1
        self.message = f"saving {len(self.recent)}/{self.recent.maxlen}"
        if request["remaining"] <= 0:
            try:
                folder = save_measurement(self.recent, request["path"])
                self.message = f"saved {len(self.recent)}-image average (7 TIFFs) to {folder}"
            except Exception as error:
                self.message = f"could not save: {error}"
            self.save = None

    def stop(self):
        self.running = False
        self.grabber.join()          # let the read in flight finish; shutdownDevice() then stops the stream


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=int, default=10_000, help="exposure in microseconds")
    ap.add_argument("--debug", action="store_true",
                     help="no camera needed: use a synthetic KiraluxDebug scene instead")
    args = ap.parse_args()

    camera = KiraluxDebug() if args.debug else KiraluxCameraDevice()
    camera.initializeDevice()
    app = ChannelsApp(camera, args.exp)
    try:
        app.mainloop()
    finally:
        app.stop()
        camera.shutdownDevice()


if __name__ == "__main__":
    main()
