"""Live preview of the four analyser channels (I0, I45, I90, I135) with myTk.

Everything stays uint16 until the last step: the channels are strided views of the
mosaic (no copy, no float), scaled to 8 bits (brightest 0.5% saturate) only to be drawn.

    python examples/preview_mytk_channels.py --exp 1000

Close the window to stop. Needs myTk:  pip install mytk
"""
import argparse
import threading
import time

import numpy as np
from PIL import Image as PILImage
from mytk import App, Image, Label

from kiralux import KiraluxCameraDevice

NAMES = ("I0", "I45", "I90", "I135")
LAYOUT = ((0, 0), (0, 1), (1, 0), (1, 1))        # (row, column) of each channel
STEP = 3                                          # show every 3rd pixel: still a view, still no copy


class ChannelsApp(App):
    def __init__(self, camera):
        App.__init__(self, name="Kiralux live preview: channels", auto_position="top-left")
        self.camera = camera
        self.running = True
        self.pending = False                      # a frame is on its way to the window

        blank = PILImage.new("L", (1224 // STEP, 1024 // STEP))
        self.images = []
        for name, (row, column) in zip(NAMES, LAYOUT):
            Label(name).grid_into(self.window, row=2 * row, column=column, pady=(10, 0))
            image = Image(pil_image=blank)
            image.grid_into(self.window, row=2 * row + 1, column=column, padx=5, pady=5)
            self.images.append(image)
        self.status = Label("")
        self.status.grid_into(self.window, row=4, column=0, columnspan=2, pady=(0, 10))

        self.grabber = threading.Thread(target=self.grab, daemon=True)
        self.grabber.start()

    def grab(self):
        while self.running:
            start = time.perf_counter()
            frame = self.camera.snap()
            snapped = time.perf_counter()
            views = [c[::STEP, ::STEP] for c in frame.raw_channels]
            top = max(int(np.percentile(v, 99.5)) for v in views) or 1   # one scale for all four, to keep their ratios
            pictures = [PILImage.fromarray((np.minimum(v, top) * 255 // top).astype(np.uint8)) for v in views]
            done = time.perf_counter()
            text = (f"{1 / (done - start):.1f} frames/s   capture {1000 * (snapped - start):.0f} ms"
                    f"   to 8 bits {1000 * (done - snapped):.1f} ms")
            if not self.pending:                      # the window is behind: drop this frame, keep capturing
                self.pending = True
                self.schedule_on_main_thread(self.show, args=[pictures, text])

    def show(self, pictures, text):
        for image, picture in zip(self.images, pictures):
            image.pil_image = picture
            image.update_display()
        self.status.text = text
        self.pending = False

    def stop(self):
        self.running = False
        self.grabber.join()          # let the read in flight finish; shutdownDevice() then stops the stream


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=int, default=1_000, help="exposure in microseconds")
    args = ap.parse_args()

    camera = KiraluxCameraDevice()
    camera.initializeDevice()
    camera.setExposure(args.exp)
    camera.startStreaming()                       # arm once: frames then arrive back to back
    app = ChannelsApp(camera)
    try:
        app.mainloop()
    finally:
        app.stop()
        camera.shutdownDevice()


if __name__ == "__main__":
    main()
