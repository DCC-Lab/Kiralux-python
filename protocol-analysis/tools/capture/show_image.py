#!/usr/bin/env python3
"""Displays an image in a window on the Windows desktop.

Usage:
    python show_image.py [image_path] [--seconds N] [--title "Title"]

Without a path, generates a test image (gradient + target pattern) to verify
that the display works. --seconds N closes the window after N seconds.
"""
import argparse
import os
import sys
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk


def make_test_image(w=640, h=480):
    """Horizontal gradient + target pattern + text, to validate the display pipeline."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for x in range(w):
        v = int(255 * x / (w - 1))
        for y in range(h):
            px[x, y] = (v, (y * 255) // (h - 1), 255 - v)
    d = ImageDraw.Draw(img)
    # target pattern: central cross
    d.line([(w // 2, 0), (w // 2, h)], fill=(255, 255, 255), width=1)
    d.line([(0, h // 2), (w, h // 2)], fill=(255, 255, 255), width=1)
    for r in range(40, min(w, h) // 2, 40):
        d.ellipse([w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r],
                  outline=(255, 255, 255))
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    d.text((10, 10), "ThorImage RE - test image", fill=(255, 255, 0), font=font)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", help="path of the image to display")
    ap.add_argument("--seconds", type=float, default=0,
                    help="auto close after N seconds (0 = stays open)")
    ap.add_argument("--title", default="ThorImage - Viewer")
    ap.add_argument("--grab", default=None,
                    help="captures the screen after 2s and saves this PNG (display proof)")
    args = ap.parse_args()

    if args.image and os.path.isfile(args.image):
        img = Image.open(args.image)
        src = args.image
    else:
        if args.image:
            print(f"[info] not found: {args.image} -> test image", file=sys.stderr)
        img = make_test_image()
        src = "(test image)"

    root = tk.Tk()
    root.title(f"{args.title} - {os.path.basename(src)}")
    root.configure(bg="black")

    # Clamp to the screen
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    disp = img.copy()
    disp.thumbnail((int(sw * 0.9), int(sh * 0.9)), Image.LANCZOS)
    photo = ImageTk.PhotoImage(disp)

    lbl = tk.Label(root, image=photo, bg="black")
    lbl.pack()

    # Centering
    root.update_idletasks()
    w, h = disp.width, disp.height
    x, y = (sw - w) // 2, (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    root.bind("<Escape>", lambda e: root.destroy())
    root.bind("q", lambda e: root.destroy())
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()

    if args.grab:
        def _grab():
            try:
                from PIL import ImageGrab
                ImageGrab.grab().save(args.grab)
                print(f"[ok] screen capture -> {args.grab}")
            except Exception as e:
                print(f"[err] capture: {e}", file=sys.stderr)
        root.after(2000, _grab)

    if args.seconds > 0:
        root.after(int(args.seconds * 1000), root.destroy)

    print(f"[ok] displaying {src} ({img.width}x{img.height})")
    root.mainloop()


if __name__ == "__main__":
    main()
