#!/usr/bin/env python3
"""Affiche une image dans une fenetre sur le bureau Windows.

Usage:
    python show_image.py [chemin_image] [--seconds N] [--title "Titre"]

Sans chemin, genere une image de test (degrade + mire) pour verifier
que l'affichage fonctionne. --seconds N ferme la fenetre apres N secondes.
"""
import argparse
import os
import sys
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk


def make_test_image(w=640, h=480):
    """Degrade horizontal + mire + texte, pour valider le pipeline d'affichage."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for x in range(w):
        v = int(255 * x / (w - 1))
        for y in range(h):
            px[x, y] = (v, (y * 255) // (h - 1), 255 - v)
    d = ImageDraw.Draw(img)
    # mire: croix centrale
    d.line([(w // 2, 0), (w // 2, h)], fill=(255, 255, 255), width=1)
    d.line([(0, h // 2), (w, h // 2)], fill=(255, 255, 255), width=1)
    for r in range(40, min(w, h) // 2, 40):
        d.ellipse([w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r],
                  outline=(255, 255, 255))
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    d.text((10, 10), "ThorImage RE - image de test", fill=(255, 255, 0), font=font)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", help="chemin de l'image a afficher")
    ap.add_argument("--seconds", type=float, default=0,
                    help="fermeture auto apres N secondes (0 = reste ouverte)")
    ap.add_argument("--title", default="ThorImage - Afficheur")
    ap.add_argument("--grab", default=None,
                    help="capture l'ecran apres 2s et enregistre ce PNG (preuve d'affichage)")
    args = ap.parse_args()

    if args.image and os.path.isfile(args.image):
        img = Image.open(args.image)
        src = args.image
    else:
        if args.image:
            print(f"[info] introuvable: {args.image} -> image de test", file=sys.stderr)
        img = make_test_image()
        src = "(image de test)"

    root = tk.Tk()
    root.title(f"{args.title} - {os.path.basename(src)}")
    root.configure(bg="black")

    # Bornage a l'ecran
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    disp = img.copy()
    disp.thumbnail((int(sw * 0.9), int(sh * 0.9)), Image.LANCZOS)
    photo = ImageTk.PhotoImage(disp)

    lbl = tk.Label(root, image=photo, bg="black")
    lbl.pack()

    # Centrage
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
                print(f"[ok] capture ecran -> {args.grab}")
            except Exception as e:
                print(f"[err] capture: {e}", file=sys.stderr)
        root.after(2000, _grab)

    if args.seconds > 0:
        root.after(int(args.seconds * 1000), root.destroy)

    print(f"[ok] affichage de {src} ({img.width}x{img.height})")
    root.mainloop()


if __name__ == "__main__":
    main()
