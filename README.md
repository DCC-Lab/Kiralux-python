# Kiralux-python

Pilotage **100 % Python** (libusb/pyusb) de la caméra **ThorLabs CS505MUP1**
(Kiralux 5 MP, CMOS **polarisation** monochrome, Sony IMX250MZR) sur **macOS/Linux**,
sans aucune librairie native ThorLabs.

Obtenu par reverse-engineering du protocole USB de la caméra (interopérabilité).

## État — ✅ fonctionnel

| | |
|---|---|
| Protocole USB (commandes, config, trigger, lecture) | ✅ reverse-engineeré & fonctionnel |
| Handshake / infos (sernum, dims, température…) | ✅ |
| **Acquisition plein format → image propre** | ✅ ~95 MB/s, vmed≈3 (macOS & Linux) |
| Intensité S0 (démosaïquage polar) | ✅ |
| Raffinements (dernière ligne, DoLP/AoLP, triggers HW) | voir [HANDOFF.md §7](HANDOFF.md) |

Deux clés (cf. [HANDOFF.md §6](HANDOFF.md)) : lire EP 0x83 en **transferts de 16384 o**
(sinon ~1 MB/s), et **décoder chaque bloc de 16384 o indépendamment** (les triplets
12-bit ne traversent pas les frontières de bloc).

## Démarrage rapide (macOS)

```bash
brew install libusb
pip install libusb1 numpy pillow
export DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib    # macOS (sur Linux: rien a faire)

python macos/camera_usb.py --info                     # infos (sernum, dims, temperature)
python macos/camera_usb.py --exp 20000 --s0 --out frame.png   # 1 frame -> intensite S0
python macos/polar_demo.py --exp 40000                # S0, DoLP, AoLP, fausse couleur
python macos/continuous_capture.py --n 30             # acquisition continue + FPS
```
La caméra doit être branchée directement sur la machine (détachée de toute VM).

### En bibliothèque
```python
from camera_usb import Kiralux
with Kiralux() as cam:
    mosaic = cam.grab(exposure_us=20000)      # ndarray uint16 (2048, 2448), mosaique polar
    S0   = Kiralux.polar_s0(mosaic)           # intensite
    dolp = Kiralux.polar_dolp(mosaic)         # degre de polarisation 0..1
    aolp = Kiralux.polar_aolp(mosaic)         # angle -90..90 deg
    rgb  = Kiralux.polar_falsecolor(mosaic)   # HSV: teinte=AoLP, sat=DoLP, val=S0
```

## Le protocole en bref

Interface USB vendor (classe 0xFF), 5 endpoints bulk. Protocole **texte ASCII**,
auto-documenté (`discover`, `<cmd>.disc`) :

- `0x02` OUT : commandes ASCII (buffer 1024 o, `\0`-terminé)
- `0x82` IN  : réponses ASCII
- `0x83` IN  : données image (en-tête 16384 o + pixels **12 bits packés Mono12p**)

Séquence : `stop → exp <us> → hwtrig none → nframes 1 → arm → start → [lire 0x83] → stop`.

Détails complets : [`docs/PROTOCOL.md`](docs/PROTOCOL.md) ·
Reprise/état : [`HANDOFF.md`](HANDOFF.md) · Architecture SDK : [`docs/SDK_MAP.md`](docs/SDK_MAP.md)

## Organisation

```
macos/        driver Python (camera_usb.py) + scripts d'analyse (async, ROI, format)
docs/         PROTOCOL.md, SDK_MAP.md, signatures d'API (SMNC_/tl_camera_/p2d_)
captures/     capture USBPcap du protocole + transcript ASCII décodé
HANDOFF.md    document de reprise (tout l'état, diagnostics, pistes)
```

## Licence / note

Projet d'interopérabilité pour piloter du matériel possédé en propre.
Les binaires et le code source propriétaires ThorLabs ne sont pas redistribués ici.
ThorLabs, Kiralux et CS505MUP1 sont des marques de Thorlabs Inc.
