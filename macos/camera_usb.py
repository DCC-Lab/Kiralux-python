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
BLK = 16384                      # taille de bloc USB : les triplets 12-bit NE traversent PAS
                                 # les frontieres de 16384 o (5461 triplets + 1 o de padding/bloc)
N_TRANSFERS = 256                # transferts async concurrents
BUF = BLK                        # IMPORTANT: lire par bloc de 16384 (= burst) -> 95 MB/s
                                 # (des transferts plus gros s'effondrent a ~1 MB/s)


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
        try:
            if self.h.kernelDriverActive(0):
                self.h.detachKernelDriver(0)
        except Exception:
            pass
        self.h.claimInterface(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

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
        while st["a"] > 0 and time.monotonic() - t1 < 0.15:
            self.ctx.handleEventsTimeout(0.005)
        self.cmd("stop")
        return data, W, H

    @staticmethod
    def _unpack(body, W, H):
        """Decode 12-bit Mono12p en respectant la structure par bloc de 16384 o.

        Chaque bloc = 16383 octets "principaux" (5461 triplets) + 1 octet de queue.
        Les triplets ne traversent PAS les frontieres de bloc (16384 mod 3 = 1, sinon
        l'alignement derive de 1 o/bloc -> striping periodique). Les octets de queue,
        concatenes, forment la FIN de l'image (les derniers pixels)."""
        import numpy as np
        npix = W * H
        nblk = len(body) // BLK

        def tri(b3):
            b3 = b3.astype(np.uint16)
            p = np.empty(b3.shape[0] * 2, np.uint16)
            p[0::2] = b3[:, 0] | ((b3[:, 1] & 0x0F) << 8)
            p[1::2] = (b3[:, 1] >> 4) | (b3[:, 2] << 4)
            return p

        full = np.frombuffer(body[:nblk * BLK], np.uint8).reshape(nblk, BLK)
        px_main = tri(full[:, :16383].reshape(-1, 3))
        # octets de queue (1/bloc) + reste eventuel apres les blocs pleins
        extra = np.concatenate([full[:, 16383],
                                np.frombuffer(body[nblk * BLK:], np.uint8)])
        ne = len(extra) // 3
        px_tail = tri(extra[:ne * 3].reshape(-1, 3)) if ne else np.empty(0, np.uint16)

        allpx = np.concatenate([px_main, px_tail])
        if len(allpx) < npix:                       # securite (ROI non standard)
            allpx = np.concatenate([allpx, np.zeros(npix - len(allpx), np.uint16)])
        return allpx[:npix].reshape(H, W)

    def grab(self, exposure_us=20000, roi=None):
        """Acquiert une frame -> ndarray uint16 (H, W), mosaique polar brute."""
        data, W, H = self.grab_raw_bytes(exposure_us, roi)
        img = self._unpack(bytes(data[HDR:]), W, H)
        pct = 100.0 * len(data) / (HDR + W * H * 3 // 2)
        if pct < 99.5:
            print(f"[warn] frame partielle ({pct:.1f}% recu)", file=sys.stderr)
        return img

    # -- traitement polarisation (capteur Sony IMX250MZR, tuile 2x2) ------
    # Arrangement par defaut de la tuile 2x2 (haut-gauche, haut-droit, bas-gauche, bas-droit):
    #   [ 90°  45° ]
    #   [ 135°  0° ]
    @staticmethod
    def polar_channels(mosaic):
        """Separe la mosaique en 4 images (I0, I45, I90, I135), demi-resolution."""
        import numpy as np
        H2 = mosaic.shape[0] & ~1; W2 = mosaic.shape[1] & ~1
        m = mosaic[:H2, :W2].astype(np.float32)
        I90 = m[0::2, 0::2]; I45 = m[0::2, 1::2]
        I135 = m[1::2, 0::2]; I0 = m[1::2, 1::2]
        return I0, I45, I90, I135

    @classmethod
    def polar_stokes(cls, mosaic):
        """Parametres de Stokes lineaires (S0, S1, S2), demi-resolution."""
        I0, I45, I90, I135 = cls.polar_channels(mosaic)
        S0 = (I0 + I45 + I90 + I135) / 2.0      # intensite totale
        S1 = I0 - I90
        S2 = I45 - I135
        return S0, S1, S2

    @classmethod
    def polar_s0(cls, mosaic):
        """Intensite totale S0 (demi-resolution)."""
        return cls.polar_stokes(mosaic)[0]

    @classmethod
    def polar_dolp(cls, mosaic):
        """Degre de polarisation lineaire (DoLP), 0..1."""
        import numpy as np
        S0, S1, S2 = cls.polar_stokes(mosaic)
        return np.sqrt(S1 * S1 + S2 * S2) / np.maximum(S0, 1e-6)

    @classmethod
    def polar_aolp(cls, mosaic, degrees=True):
        """Angle de polarisation lineaire (AoLP). degrees=True -> -90..90 deg."""
        import numpy as np
        _, S1, S2 = cls.polar_stokes(mosaic)
        a = 0.5 * np.arctan2(S2, S1)
        return np.degrees(a) if degrees else a

    @classmethod
    def polar_falsecolor(cls, mosaic):
        """Rendu HSV: teinte=AoLP, saturation=DoLP, valeur=S0. -> RGB uint8."""
        import numpy as np
        S0, S1, S2 = cls.polar_stokes(mosaic)
        dolp = np.clip(np.sqrt(S1 * S1 + S2 * S2) / np.maximum(S0, 1e-6), 0, 1)
        aolp = (0.5 * np.arctan2(S2, S1) + np.pi / 2) / np.pi     # 0..1
        v = S0 - np.percentile(S0, 1)
        v = np.clip(v / max(np.percentile(S0, 99) - np.percentile(S0, 1), 1), 0, 1)
        import colorsys
        hsv = np.stack([aolp, dolp, v], axis=-1)
        # conversion vectorisee HSV->RGB
        h6 = hsv[..., 0] * 6.0
        c = hsv[..., 2] * hsv[..., 1]
        x = c * (1 - np.abs(h6 % 2 - 1))
        m = hsv[..., 2] - c
        z = np.zeros_like(c)
        i = h6.astype(int) % 6
        r = np.select([i==0,i==1,i==2,i==3,i==4,i==5],[c,x,z,z,x,c])
        g = np.select([i==0,i==1,i==2,i==3,i==4,i==5],[x,c,c,x,z,z])
        b = np.select([i==0,i==1,i==2,i==3,i==4,i==5],[z,z,x,c,c,x])
        rgb = np.stack([r+m, g+m, b+m], axis=-1)
        return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)

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
