"""Live preview of the Kiralux: the four polarizer channels and their polarimetric decomposition.

    python examples/preview.py --exp 40000

Close the window to stop. Needs matplotlib:  pip install "kiralux[examples]"
"""
import argparse
import threading

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from kiralux import KiraluxCameraDevice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=int, default=40_000, help="exposure in microseconds")
    ap.add_argument("--gain", type=int, default=0, help="gain (0..480, tenths of a dB)")
    args = ap.parse_args()

    cam = KiraluxCameraDevice()
    cam.initializeDevice()
    cam.setExposure(args.exp)
    cam.setGain(args.gain)

    latest = {"frame": None, "count": 0}
    stop = threading.Event()

    def grab():
        while not stop.is_set():
            latest["frame"] = cam.snap()
            latest["count"] += 1

    threading.Thread(target=grab, daemon=True).start()
    while latest["frame"] is None:
        stop.wait(0.05)

    # (title, getter, cmap, (vmin, vmax))
    views = [
        ("S0", lambda f: f.s0, "gray", (None, None)),
        ("DoLP", lambda f: f.dolp, "viridis", (0, 1)),
        ("AoLP (deg)", lambda f: f.aolp, "hsv", (-90, 90)),
        ("I0", lambda f: f.channels[0], "gray", (0, 4095)),
        ("I45", lambda f: f.channels[1], "gray", (0, 4095)),
        ("I90", lambda f: f.channels[2], "gray", (0, 4095)),
        ("I135", lambda f: f.channels[3], "gray", (0, 4095)),
        ("False color", lambda f: f.falsecolor, None, (None, None)),
    ]

    fig, axs = plt.subplots(2, 4, figsize=(18, 8))
    fig.canvas.manager.set_window_title("Kiralux live preview")
    images = []
    f0 = latest["frame"]
    for ax, (title, get, cmap, (vmin, vmax)) in zip(axs.flat, views):
        images.append(ax.imshow(get(f0), cmap=cmap, vmin=vmin, vmax=vmax))
        ax.set_title(title)
        ax.axis("off")
    fig.tight_layout()


    def update(_):
        f = latest["frame"]
        for im, (_, get, _, (vmin, vmax)) in zip(images, views):
            data = get(f)
            im.set_data(data)
            if vmin is None and data.ndim == 2:
                im.set_clim(data.min(), data.max())
        fig.suptitle(f"{cam.version}  exp {cam.getExposure()} us  frames {latest['count']}")
        return images

    anim = FuncAnimation(fig, update, interval=50, blit=False, cache_frame_data=False)
    try:
        plt.show()
    finally:
        stop.set()
        cam.shutdownDevice()


if __name__ == "__main__":
    main()
