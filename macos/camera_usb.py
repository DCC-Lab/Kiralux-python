#!/usr/bin/env python3
"""Pilote Python pur pour la camera ThorLabs CS505MUP1 (Kiralux 5 MP polarisation),
reconstruit par reverse-engineering du protocole USB. AUCUNE librairie ThorLabs.

Fonctionne sur macOS/Linux via libusb (backend). Protocole : voir ../HANDOFF.md
et ../docs/PROTOCOL.md.

Etat :
  - Commandes / configuration / trigger / lecture : OK.
  - Petites ROI : image PROPRE.
  - Plein format : pertes de donnees residuelles en lecture (debit libusb-macOS) ->
    cf. ../HANDOFF.md section 6. A finaliser (streaming zero-copie / pont reseau).

Prerequis :
    brew install libusb        (Linux : apt install libusb-1.0-0)
    pip install libusb1 numpy pillow
    export DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib   # macOS, pour trouver libusb

Usage :
    python camera_usb.py --info
    python camera_usb.py --roi 712 512 1735 1535 --exp 20000 --out frame.png
"""
import argparse
import sys
import time

import usb1

VID, PID = 0x1313, 0x4001
EP_CMD_OUT, EP_CMD_IN, EP_IMG_IN = 0x02, 0x82, 0x83
CMD_LEN = 1024
HDR = 16384                      # en-tete de frame (tags TSI/FCNT/... puis padding)
N_TRANSFERS = 64                 # transferts async concurrents
BUF = 128 * 1024                 # taille par transfert


class Kiralux:
    def __init__(self):
        self.ctx = usb1.USBContext(); self.ctx.open()
        self.h = self.ctx.openByVendorIDAndProductID(VID, PID)
        if self.h is None:
            raise RuntimeError(f"Camera {VID:#06x}:{PID:#06x} introuvable "
                               "(branchee sur cette machine ? detachee de la VM ?)")
        try:
            self.h.setAutoDetachKernelDriver(True)
        except Exception:
            pass
        self.h.claimInterface(0)

    # -- protocole texte ASCII --------------------------------------------
    def cmd(self, text, timeout=3000):
        self.h.bulkWrite(EP_CMD_OUT, (text.encode() + b"\x00").ljust(CMD_LEN, b"\x00"), timeout)
        resp = bytes(self.h.bulkRead(EP_CMD_IN, CMD_LEN, timeout)).split(b"\x00")[0].decode("latin1").strip()
        if resp.startswith("error"):
            raise RuntimeError(f"cmd {text!r} -> {resp}")
        return resp

    def info(self):
        self.cmd("stop")
        return {
            "sernum": self.cmd("sernum"),
            "model": self.cmd("id"),
            "width": int(self.cmd("image_width")),
            "height": int(self.cmd("image_height")),
            "bit_depth": int(self.cmd("pixel_bit_depth")),
            "polar_phase": self.cmd("polar_phase"),
            "color": self.cmd("color"),
            "temperature": self.cmd("temperature"),
        }

    # -- acquisition (lecture async multi-buffer) -------------------------
    def grab_raw_bytes(self, exposure_us=20000, roi=None, wall=5.0):
        """Retourne (data: bytearray, W, H). data = HDR + pixels 12-bit packes."""
        self.cmd("stop")
        if roi is not None:
            self.cmd("roi %d %d %d %d" % tuple(roi))
        self.cmd(f"exp {int(exposure_us)}")
        self.cmd("hwtrig none")
        self.cmd("nframes 1")
        W = int(self.cmd("image_width")); H = int(self.cmd("image_height"))
        target = HDR + W * H * 3 // 2

        data = bytearray(); st = {"a": N_TRANSFERS, "stop": False}
        def cb(t):
            if t.getStatus() == usb1.TRANSFER_COMPLETED:
                data.extend(t.getBuffer()[:t.getActualLength()])
            if not st["stop"] and len(data) < target:
                try:
                    t.submit(); return
                except usb1.USBError:
                    pass
            st["a"] -= 1

        transfers = [self.h.getTransfer() for _ in range(N_TRANSFERS)]
        for t in transfers:
            t.setBulk(EP_IMG_IN, BUF, callback=cb, timeout=2000)
        self.cmd("arm")
        for t in transfers:
            t.submit()
        self.cmd("start")
        t0 = time.monotonic()
        while st["a"] > 0 and len(data) < target and time.monotonic() - t0 < wall:
            self.ctx.handleEventsTimeout(0.02)
        st["stop"] = True
        for t in transfers:
            try: t.cancel()
            except Exception: pass
        t1 = time.monotonic()
        while st["a"] > 0 and time.monotonic() - t1 < 0.5:
            self.ctx.handleEventsTimeout(0.02)
        self.cmd("stop")
        return data, W, H

    def grab(self, exposure_us=20000, roi=None):
        """Acquiert une frame -> ndarray uint16 (H, W), mosaique polar brute."""
        import numpy as np
        data, W, H = self.grab_raw_bytes(exposure_us, roi)
        row = W * 3 // 2
        nrows = min(H, (len(data) - HDR) // row)
        nrows -= nrows % 2
        raw = np.frombuffer(bytes(data[HDR:HDR + nrows * row]), np.uint8).astype(np.uint16).reshape(-1, 3)
        p = np.empty(nrows * W, np.uint16)
        p[0::2] = raw[:, 0] | ((raw[:, 1] & 0x0F) << 8)      # Mono12p, little-endian
        p[1::2] = (raw[:, 1] >> 4) | (raw[:, 2] << 4)
        pct = 100.0 * len(data) / (HDR + W * H * 3 // 2)
        if nrows < H:
            print(f"[warn] frame partielle: {nrows}/{H} lignes ({pct:.1f}% recu) "
                  f"- cf. HANDOFF.md section 6", file=sys.stderr)
        return p.reshape(nrows, W)

    @staticmethod
    def polar_s0(mosaic):
        """Intensite S0 = moyenne du super-pixel 2x2 (demosaique polar 0/45/90/135)."""
        import numpy as np
        m = mosaic.astype(np.float32)
        return (m[0::2, 0::2] + m[0::2, 1::2] + m[1::2, 0::2] + m[1::2, 1::2]) / 4.0

    def close(self):
        try: self.h.releaseInterface(0)
        except Exception: pass
        self.ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--exp", type=int, default=20000, help="exposition en us")
    ap.add_argument("--roi", type=int, nargs=4, metavar=("L", "T", "R", "B"),
                    help="region d'interet (left top right bottom)")
    ap.add_argument("--out", default="frame.png")
    ap.add_argument("--s0", action="store_true", help="enregistre l'intensite S0 (demosaique)")
    args = ap.parse_args()

    cam = Kiralux()
    if args.info:
        print(cam.info()); cam.close(); return
    import numpy as np
    from PIL import Image
    mosaic = cam.grab(args.exp, roi=args.roi)
    cam.close()
    img = cam.polar_s0(mosaic) if args.s0 else mosaic.astype(np.float32)
    print(f"image {img.shape} min={img.min():.0f} max={img.max():.0f} mean={img.mean():.1f}")
    lo, hi = np.percentile(img, [1, 99])
    d = np.clip((img - lo) / max(hi - lo, 1) * 255, 0, 255).astype(np.uint8)
    Image.fromarray(d, "L").save(args.out)
    print("->", args.out)


if __name__ == "__main__":
    main()
