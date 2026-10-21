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
brew install libusb                       # Linux : dnf/apt install libusb-1.0
pip install libusb1 numpy pillow
# (macOS seulement, si brew est dans un préfixe non standard :)
export DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib

python macos/polar_demo.py --exp 40000    # S0, DoLP, AoLP, fausse couleur
python macos/continuous_capture.py --n 30 # acquisition en boucle + FPS
```
La caméra doit être branchée directement sur la machine (détachée de toute VM).
Le module `kiralux.py` localise `libusb` tout seul sur les emplacements courants.

### La classe `Kiralux`
```python
from kiralux import Kiralux

with Kiralux() as cam:                  # ou Kiralux(serial="18658")
    cam.exposure_us = 20_000            # propriétés Pythoniques, synchronisées
    cam.gain_db     = 0                 #   avec la caméra
    cam.roi         = (0, 0, 2447, 2047)
    cam.binning     = (1, 1)
    print(cam.model, cam.serial, cam.temperature)

    frame = cam.snap()                  # -> PolarFrame (2048 x 2448 uint16)
    frame.s0        # intensité totale (Stokes S0), demi-résolution
    frame.dolp      # degré de polarisation linéaire   0..1
    frame.aolp      # angle de polarisation linéaire   -90..90°
    frame.stokes    # (S0, S1, S2)
    frame.channels  # (I0, I45, I90, I135)
    frame.falsecolor  # composite HSV (teinte=AoLP, sat=DoLP, valeur=S0) -> RGB

Kiralux.available()                     # numéros de série des caméras branchées
```
Les vues polarimétriques sont calculées **paresseusement** et mises en cache.

### Intégration PyHardwareLibrary (optionnelle)
`macos/kiralux_phl.py` adapte le driver à l'écosystème [DCC-Lab/PyHardwareLibrary](https://github.com/DCC-Lab/PyHardwareLibrary) :
`KiraluxCamera(CameraDevice, ExposureCapability, GainCapability)` — machine à états,
cycle de vie, notifications, boucle de capture et introspection des *capabilities*,
par **composition** d'un `Kiralux` (l'USB n'est pas réécrit). Dépendance optionnelle :
```bash
pip install "git+https://github.com/DCC-Lab/PyHardwareLibrary@master"
python macos/kiralux_phl.py
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
macos/
  kiralux.py            la classe Kiralux + PolarFrame (le driver)
  polar_demo.py         exemple : S0 / DoLP / AoLP / fausse couleur
  continuous_capture.py exemple : acquisition en boucle + FPS
  *.py                  scripts d'analyse/RE (format, débit, Linux…) — historiques
docs/         PROTOCOL.md, SDK_MAP.md, signatures d'API (SMNC_/tl_camera_/p2d_)
captures/     capture USBPcap du protocole + transcript ASCII décodé
HANDOFF.md    document de reprise (tout l'état, diagnostics, solution)
```

## Licence / note

Projet d'interopérabilité pour piloter du matériel possédé en propre.
Les binaires et le code source propriétaires ThorLabs ne sont pas redistribués ici.
ThorLabs, Kiralux et CS505MUP1 sont des marques de Thorlabs Inc.
