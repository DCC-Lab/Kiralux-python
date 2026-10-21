# ThorImage CS505MUP1 — Reverse-engineering & pilotage Python macOS
## Document de reprise (handoff) — tout ce qui a été établi

> Objectif : piloter la caméra ThorLabs **CS505MUP1** (Kiralux 5 MP polarisation)
> en **Python pur** depuis macOS, sans aucune librairie native ThorLabs.
>
> État : **COMPLET**. Protocole USB 100 % reverse-engineeré ; acquisition plein
> format propre (2448×2048, ~95 MB/s) ; traitement polarimétrique (S0/DoLP/AoLP).
> Driver = `macos/kiralux.py` (classe `Kiralux` + `PolarFrame`). Le striping
> « plein format » est résolu (cause + fix en §6).

---

## 1. Matériel / identité

| | |
|---|---|
| Modèle | **CS505MUP1** (Kiralux 5.0 MP, CMOS **polarisation** monochrome, Sony IMX250MZR) |
| Capteur | 2448 × 2048, 12 bits, pixel 3.45 µm |
| N° série (logique) | 18658 |
| USB | **VID 0x1313 / PID 0x4001**, USB 3.0 SuperSpeed, Cypress FX3, firmware résident |
| Driver Windows | CYUSB3 (générique Cypress) → toute la logique est en espace utilisateur |
| Classe USB | Vendor 0xFF → **aucun driver noyau macOS ne la réclame → libusb la pilote** |

**Fait clé** : sur **Windows (même Mac, via Parallels)** l'acquisition via le SDK
TSI est **parfaite** (image lisse). Donc le hardware/lien est bon ; le blocage
macOS est **purement logiciel** (voir §6).

---

## 2. Endpoints (interface 0, classe 0xFF, 5 endpoints)

| EP | Dir | Type | maxpkt | burst | Rôle |
|----|-----|------|--------|-------|------|
| `0x02` | OUT | BULK | 1024 | 1  | **Commandes** ASCII |
| `0x82` | IN  | BULK | 1024 | 1  | **Réponses** ASCII |
| `0x83` | IN  | BULK | 1024 | 16 | **Données image** (bursts de 16384 o) |
| `0x01` | OUT | BULK | 1024 | 16 | OUT secondaire (inutilisé) |
| `0x81` | IN  | INTR | 128  | — | Événements/statut (inutilisé) |

---

## 3. Protocole de commande (texte ASCII) — CONFIRMÉ

- Écrire un buffer de **1024 o** sur `0x02` : commande ASCII + `\0` + padding.
- Lire **1024 o** sur `0x82` : réponse ASCII `\0`-terminée.
- Erreur : `error <code>,<message>`.
- **`discover`** renvoie la liste de toutes les commandes.
- **`<cmd>.disc`** renvoie la syntaxe JSON de chaque commande (la caméra
  auto-documente son API — voir `../docs/PROTOCOL.md` pour le détail).

### Commandes clés
`id`, `sernum`, `model name`, `exp <us>`, `gain <dB>` (0–480), `roi <l> <t> <r> <b>`,
`hbin`, `vbin`, `nframes <n>`, `hwtrig <none|…>`, `arm`, `start`, `stop`, `disarm`,
`image_width`, `image_height`, `pixel_bit_depth`(12), `pixel_size`(2),
`imgpack <on|off>`, `pixel_byte_ordering`(little endian), `polar_phase`(90),
`color`(none polar), `temperature`, `sensor_readout_time`,
`sfr <off|on|rate>` (sensor frame rate, 100–35723), `pixel_clock_count_base`(99 MHz).

### Séquence d'acquisition (software trigger) — CONFIRMÉE
```
stop → exp <us> → hwtrig none → nframes 1 → [roi …] → arm → start ("running")
→ lire les données sur EP 0x83 → stop
```
En `hwtrig none`, **`start` est lui-même le déclencheur** (pas de trigger séparé).

---

## 4. Format de la frame image (EP 0x83)

Taille totale reçue = **16384 (en-tête) + largeur×hauteur×1.5** (12 bits packés).
Ex. plein format : 16384 + 2448×2048×1.5 = **7 536 640 o**.

### En-tête (16384 o, au début)
Bloc de tags au tout début (puis contenu/padding jusqu'à 16384) :
```
offset 0x00 : 90 90 00 00                (magic)
offset 0x04 : "TSI\0"  + valeur
offset 0x0c : "FCNT"   + frame count (=1)
offset 0x14 : "PCKH"   + timestamp high
offset 0x1c : "PCKL"   + timestamp low   (change à chaque frame)
offset 0x24 : "IFMT"   + 0x1001          (format image)
offset 0x2c : "IOFF"   + 7
offset 0x34 : "ENDT"   + 0               (fin des tags, ~offset 60)
```
⚠️ **À confirmer** : la région [60:16384] contient des octets non nuls ; savoir si
c'est du padding/metadata ou le début des pixels reste à vérifier sur une capture
*propre* (cf. §6). L'arithmétique `16384 + W·H·1.5 = total` (vérifiée sur plusieurs
tailles de ROI) plaide pour **en-tête = 16384, pixels à partir de 16384**.

### Pixels : 12 bits packés "Mono12p" (scheme A) — CONFIRMÉ
2 pixels sur 3 octets, little-endian :
```python
p0 = b0 | ((b1 & 0x0F) << 8)
p1 = (b1 >> 4) | (b2 << 4)
```
(Déterminé en minimisant le bruit horizontal ; les variantes B/C/D sont moins bonnes.)
`imgpack off` **ne change pas** la taille USB (toujours 1.5 o/px) malgré la réponse.

### Polarisation (mosaïque 2×2 — IMX250MZR)
Micro-polariseurs 0°/45°/90°/135° en tuile 2×2. Intensité **S0 = moyenne du
super-pixel 2×2**. Pour DoLP/AoLP il faut connaître la phase exacte de la tuile
(à caler ; cf. `polar_phase`). Réf. de traitement : SDK `thorlabs_tsi_sdk`
(module polarisation) et repo https://github.com/Thorlabs/Camera_Examples/tree/main/Python

---

## 5. Ce qui MARCHE — ✅ COMPLET (macOS & Linux, Python pur)

- Énumération, `claimInterface`, commandes ASCII, séquence `exp/roi/arm/start/stop`.
- **Acquisition plein format → image PROPRE** (vmed≈3, comme la réf. TSI).
- Débit **~95 MB/s**, 100 % reçu, frame en ~80 ms.
- Backend : `usb1`/`libusb`, aucune lib ThorLabs. Testé macOS (direct) **et**
  Linux/CentOS (usb1, natif).

---

## 6. ✅ LE PROBLÈME DE STRIPING — RÉSOLU

Le striping « plein format » avait **deux causes**, toutes deux corrigées dans
`kiralux.py` :

### 6.1 Débit — taille de transfert
Lire EP 0x83 en transferts de **16384 octets** (= la taille de burst SuperSpeed,
`bMaxBurst=15`), avec beaucoup de transferts async concurrents (N=256).
- Transferts de 128 Ko → **~1 MB/s** (effondré) → la caméra pace/déborde.
- Transferts de 16384 o → **~95 MB/s**, 100 % reçu, frame en ~80 ms.
- Référence : le SDK TSI lit lui aussi en 16384 o (vu dans le pcap : 460 transferts,
  frame complète en **59 ms = 128 MB/s**).

### 6.2 Décodage — alignement par bloc de 16384 (LA cause du striping)
Les **triplets 12-bit ne traversent PAS les frontières de bloc de 16384 o**.
Comme `16384 mod 3 = 1`, décoder le flux comme un continuum décale l'alignement
des triplets de 1 octet à chaque bloc, se recalant tous les 3 blocs → **beat de
période 3×16384 o = 13.39 lignes** = les bandes observées.
**Fix** : décoder chaque bloc de 16384 o **indépendamment** (5461 triplets complets
= 16383 o/bloc). Résultat : **vmed 134 → 3** (propre). Voir `Kiralux._decode()`.

> Les octets de « queue » (1/bloc = dernier octet de chaque bloc de 16384), une fois
> **concaténés**, forment les **306 derniers pixels** (la fin de la dernière ligne) :
> `main + tail = 5 013 504 = 2448×2048` exact → **2048 lignes pleines**. Résolu.

**Fausses pistes écartées en chemin** (documentées pour mémoire) : ce n'était PAS
une perte de données libusb-macOS, ni le hardware, ni le stride/largeur, ni la
mosaïque polar. Reproduit à l'identique sur **Linux** → bug de format/approche, pas d'OS.

---

## 7. Fait depuis / raffinements possibles

**Fait** : plein format 2448×2048 exact ; polarimétrie complète (Stokes S0/S1/S2,
DoLP, AoLP, fausse-couleur HSV) dans `PolarFrame` ; API élégante `Kiralux`
(propriétés `exposure_us`/`gain_db`/`roi`/`binning`, `snap()`, context manager,
`available()`) ; testé macOS **et** Linux/CentOS.

**Raffinements possibles** :
1. **Mode « live » haut-FPS** : réutiliser les transferts USB entre frames et rester
   armé (`nframes 0`/continu) au lieu de arm/start par frame (actuel ~2.4 fps plein 5 MP,
   limité par la reconfig + allocation, pas par le transfert ~80 ms).
2. **Calibration polarimétrique** : appliquer les matrices de correction par-pixel du
   IMX250MZR (ce que fait le SDK TSI) pour une précision DoLP/AoLP métrologique.
3. Triggers matériels (`hwtrig`), multi-frames (`nframes > 1`).

---

## 8. Carte du répertoire (voir aussi README.md)

```
ThorImageRE/
├── HANDOFF.md              ← CE DOCUMENT (reprise)
├── REPORT.html             ← rapport visuel (artifact)
├── docs/
│   ├── PROTOCOL.md         ← protocole USB détaillé
│   ├── SDK_MAP.md          ← archi .NET + SDK natif
│   ├── CameraLib_SMNC_pinvoke.txt   (93 fonctions SMNC_)
│   ├── tsi_camera_sdk_exports.txt   (132 fonctions tl_camera_)
│   └── p2d_lib_pinvoke.txt          (52 fonctions p2d_)
├── macos/                  ← Python pur (pyusb/usb1/libusb) — cible macOS
│   ├── kiralux.py          ← classe Kiralux + PolarFrame (le driver)
│   ├── polar_demo.py / continuous_capture.py  ← exemples
│   ├── async_grab*.py, thread_grab.py, slow_grab.py  ← variantes de lecture async
│   ├── roi_sweep.py        ← balaye les tailles de ROI (propre vs strié)
│   ├── *_test.py, find_*.py, deshear.py, bruteforce.py ← diagnostics format/stride
│   └── raw_big.bin         ← capture brute plein format (pour analyse offline)
├── captures/
│   ├── cam_session.pcap    ← capture USBPcap d'une session (Windows)
│   ├── transcript.txt      ← transcript ASCII décodé du protocole
│   └── decoded.txt
├── src/                    ← assemblies .NET décompilées (C#)
└── tools/                  ← scripts RE côté Windows (ilspy, capture, TSI ctypes…)
```

## 9. Environnement reproductible (macOS)
```bash
brew install libusb
pip install pyusb libusb1 numpy pillow
export DYLD_FALLBACK_LIBRARY_PATH=$(brew --prefix)/lib   # pour que pyusb trouve libusb
# (ici le brew est en préfixe custom : /Users/dccote/.local/homebrew/lib)
python3 -c "from kiralux import Kiralux; c=Kiralux(); print(c.model,c.serial); c.close()"
```
La caméra doit être branchée sur le Mac (détachée de la VM Parallels).
