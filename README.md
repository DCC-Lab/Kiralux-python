# kiralux

Pilotage **100 % Python** de la caméra **ThorLabs Kiralux CS505MUP1** (5 MP, CMOS
**polarisation** monochrome, Sony IMX250MZR) sur **macOS/Linux**, **sans aucune
librairie native ThorLabs**. Le transport USB passe par la classe `USBPort` de
[DCC-Lab/PyHardwareLibrary](https://github.com/DCC-Lab/PyHardwareLibrary).

Obtenu par reverse-engineering du protocole USB de la caméra (interopérabilité) —
toute la démarche et les outils de décodage sont dans
[`protocol-analysis/`](protocol-analysis/METHODOLOGY.md).

## Installation

```bash
pip install kiralux                 # tire hardwarelibrary + numpy
# ou, depuis les sources :
pip install git+https://github.com/DCC-Lab/Kiralux-python
```

libusb est requis au runtime (`pip` l'installe via pyusb sur la plupart des
plateformes). Si besoin : `brew install libusb` (macOS) / `dnf|apt install libusb-1.0`
(Linux). Sur macOS avec un préfixe brew non standard :

```bash
export DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib
```

La caméra doit être branchée directement sur la machine (détachée de toute VM).

## Démarrage rapide

```python
from kiralux import Kiralux

with Kiralux() as cam:                  # ou Kiralux(serial="18658")
    cam.exposure_us = 20_000            # propriétés synchronisées avec la caméra
    cam.gain_db     = 0
    cam.roi         = (0, 0, 2447, 2047)
    cam.binning     = (1, 1)
    print(cam.model, cam.serial, cam.temperature)

    frame = cam.snap()                  # -> PolarFrame (2048 × 2448 uint16)
    frame.s0            # intensité totale (Stokes S0), demi-résolution
    frame.dolp          # degré de polarisation linéaire   0..1
    frame.aolp          # angle de polarisation linéaire   -90..90°
    frame.stokes        # (S0, S1, S2)
    frame.channels      # (I0, I45, I90, I135)
    frame.falsecolor    # composite HSV (teinte=AoLP, sat=DoLP, valeur=S0) -> RGB

Kiralux.available()                     # numéros de série des caméras branchées
```

Les vues polarimétriques sont calculées **paresseusement** et mises en cache.

```bash
python examples/polar_demo.py --exp 40000     # S0, DoLP, AoLP, fausse couleur
python examples/continuous_capture.py --n 30  # acquisition en boucle + FPS
# (les exemples écrivent des PNG :  pip install "kiralux[examples]")
```

## Trois façons de piloter la caméra

Toutes dépendent uniquement de `hardwarelibrary` + `numpy`.

| Classe | Import | Pour quoi |
|---|---|---|
| **`Kiralux`** | `from kiralux import Kiralux` | Le driver direct et simple. `snap()` → `PolarFrame`. **Commencez ici.** |
| **`KiraluxDevice`** | `from kiralux import KiraluxDevice` | Même caméra, vocabulaire décrit par un `CommandDictionary` de PyHardwareLibrary. Fournit un **mock sans matériel** (voir [`tests/`](tests/)). |
| **`KiraluxCamera`** | `from kiralux import KiraluxCamera` | Adaptateur `CameraDevice` de PyHardwareLibrary : machine à états, notifications, boucle de capture, introspection des *capabilities*. |

Le choix entre `Kiralux` (simple) et `KiraluxDevice` (CommandDictionary) est
discuté dans la PR #2 : pour un usage local mono-caméra, `Kiralux` suffit ; le
`CommandDictionary` devient rentable pour les tests sans matériel / la CI.

## Le protocole en bref

Interface USB vendor (classe `0xFF`), 5 endpoints bulk. Protocole **texte ASCII**,
auto-documenté (`discover`, `<cmd>.disc`) :

- `0x02` OUT : commandes ASCII (buffer 1024 o, `\0`-terminé)
- `0x82` IN  : réponses ASCII
- `0x83` IN  : données image (en-tête 16384 o + pixels **12 bits packés Mono12p**)

Séquence : `stop → exp <us> → hwtrig none → nframes 1 → arm → start → [lire 0x83] → stop`.

**Deux clés** pour une image propre à ~95 MB/s (cf.
[`protocol-analysis/METHODOLOGY.md`](protocol-analysis/METHODOLOGY.md)) : lire
l'EP `0x83` en **transferts de 16384 o** (sinon ~1 MB/s), et **décoder chaque bloc
de 16384 o indépendamment** (les triplets 12-bit ne traversent pas les frontières
de bloc — c'était la cause du striping).

## Organisation

```
kiralux/                 le package distribuable (le driver)
  camera.py              classe Kiralux + PolarFrame
  device.py              KiraluxDevice + KiraluxPort (variante CommandDictionary)
  phl.py                 KiraluxCamera (adaptateur PyHardwareLibrary CameraDevice)
  protocol.json          vocabulaire de commandes (CommandDictionary)
examples/                polar_demo.py, continuous_capture.py
tests/                   test_command_dictionary.py (tourne sans caméra, via un mock)
protocol-analysis/       la démarche de reverse-engineering + les outils de décodage
  METHODOLOGY.md         comment le protocole a été décodé (concis)
  HANDOFF.md, REPORT.html, docs/, captures/, tools/
pyproject.toml           packaging moderne (dépend de hardwarelibrary>=2.2.0)
```

## Licence / note

Projet d'interopérabilité pour piloter du matériel possédé en propre, sous licence
[MIT](LICENSE). Les binaires et le code source propriétaires ThorLabs ne sont pas
redistribués ici. ThorLabs, Kiralux et CS505MUP1 sont des marques de Thorlabs, Inc.
