"""Simplest live preview of the Kiralux with myTk (no matplotlib): the intensity image (S0).

    python examples/preview_mytk.py --exp 30000

Close the window to stop. Needs myTk:  pip install mytk
"""
import argparse
import threading

import numpy as np
from PIL import Image as PILImage
from mytk import App, Image

from kiralux import KiraluxCameraDevice


class PreviewApp(App):
    def __init__(self, camera):
        App.__init__(self, name="Kiralux live preview")
        self.camera = camera
        self.running = True

        self.image = Image(pil_image=PILImage.new("L", (612, 512)))
        self.image.grid_into(self.window, row=0, column=0, padx=10, pady=10)

        self.grabber = threading.Thread(target=self.grab, daemon=True)
        self.grabber.start()

    def grab(self):
        while self.running:
            s0 = np.asarray(self.camera.snap().s0)
            low, high = np.percentile(s0, (0.5, 99.5))
            gray = np.clip((s0 - low) / max(high - low, 1) * 255, 0, 255).astype(np.uint8)
            self.schedule_on_main_thread(self.show, args=[PILImage.fromarray(gray).resize((612, 512))])

    def show(self, pil_image):
        self.image.pil_image = pil_image
        self.image.update_display()

    def stop(self):
        self.running = False
        self.grabber.join()          # let the capture in flight finish, so the camera is left idle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=int, default=30_000, help="exposure in microseconds")
    args = ap.parse_args()

    camera = KiraluxCameraDevice()
    camera.initializeDevice()
    camera.setExposure(args.exp)
    app = PreviewApp(camera)
    try:
        app.mainloop()
    finally:
        app.stop()
        camera.shutdownDevice()


if __name__ == "__main__":
    main()
