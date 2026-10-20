# Kiralux-python

Pilotage **100 % Python** (libusb/pyusb) de la caméra **ThorLabs CS505MUP1**
(Kiralux 5 MP, CMOS **polarisation** monochrome, Sony IMX250MZR) sur **macOS/Linux**,
sans aucune librairie native ThorLabs.

Obtenu par reverse-engineering du protocole USB de la caméra (interopérabilité).

## État

| | |
|---|---|
| Protocole USB (commandes, config, trigger, lecture) | ✅ reverse-engineeré & fonctionnel |
| Handshake / infos (sernum, dims, température…) | ✅ |
| Acquisition petites ROI → image propre | ✅ |
| Acquisition plein format | ⚠️ pertes résiduelles en lecture (débit libusb-macOS) — voir [HANDOFF.md §6](HANDOFF.md) |

## Démarrage rapide (macOS)

```bash
brew install libusb
pip install libusb1 pyusb numpy pillow
export DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib

python macos/camera_usb.py --info
python macos/camera_usb.py --roi 712 512 1735 1535 --exp 20000 --s0 --out frame.png
```
La caméra doit être branchée directement sur la machine (détachée de toute VM).

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
