# ThorImage CS505MUP1 — Reverse-engineering & pilotage Python macOS
## Document de reprise (handoff) — tout ce qui a été établi

> Objectif : piloter la caméra ThorLabs **CS505MUP1** (Kiralux 5 MP polarisation)
> en **Python pur** depuis macOS, sans aucune librairie native ThorLabs.
>
> État au moment du transfert : **protocole USB 100 % reverse-engineeré et
> fonctionnel** (commandes, config, trigger, lecture). **Blocage restant** :
> intégrité des données en lecture plein-format sur macOS/libusb (voir §6).

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

## 5. Ce qui MARCHE (prouvé sur macOS, Python pur)

- Énumération, `claimInterface`, envoi/réception de commandes ASCII : **OK**.
- Toute la séquence `exp/roi/arm/start/stop` : **OK**.
- Décodage 12 bits + géométrie (largeur 2448 confirmée par corrélation) : **OK**.
- **Petites ROI → image PROPRE** : ex. ROI 512×512, métriques isotropes
  (vmed≈hmed≈16, comme la référence TSI).
- Backend : `pyusb`/`usb1` sur `libusb` (brew), aucune lib ThorLabs.

---

## 6. ⛔ BLOCAGE RESTANT : intégrité des données en plein format

**Symptôme** : en plein format (ou grande ROI), l'image est striée
horizontalement + moiré diagonal ; le bas de frame manque (97–99 % reçu).

**Diagnostic établi** :
- Débit de lecture obtenu via libusb/macOS ≈ **1–1.5 MB/s** seulement
  (il faudrait ~26 MB/s : 7.5 Mo lus pendant le readout capteur de ~284 ms).
- Deux captures de la **même scène statique** ne partagent que **6 %** d'octets
  → pertes **non déterministes** (≈1 % d'octets perdus, éparpillés). Chaque octet
  perdu décale tout le reste → cisaillement/striping cumulatif.
- **Ce n'est PAS** : le hardware/lien (Windows OK même machine), ni le décodage
  (petites ROI propres), ni la mosaïque polar (la réf. TSI brute est lisse, vmed=8),
  ni le stride/offset/largeur (confirmés), ni un en-tête répété (aucun marqueur
  répété trouvé).
- **C'est** : le drainage USB3 depuis Python/libusb sur macOS n'arrive pas à garder
  la file de transferts **sans trou** au débit de rafale requis. Le SDK TSptI /
  CYUSB3 (Windows) y arrive via streaming noyau zéro-copie.

**Tentatives faites (insuffisantes)** :
- Lecture synchrone gros buffer → striée.
- **Async multi-buffer** (`usb1`, 48–96 transferts de 128–256 Ko) → 97–99 % reçu,
  nettement mieux (vmed 673→144) mais **pertes éparses résiduelles**.
- Thread dédié pompant `handleEvents` → pas d'amélioration de débit (~1.2 MB/s).
- **`sfr` pour ralentir le capteur** → améliore un peu, insuffisant seul.
- Même au capteur le plus lent (`sfr 100`, frame en ~8 s) il reste des pertes
  → le problème est bien le **débit/continuité de libusb-macOS**, pas la vitesse capteur.

**⚠️ Nuance non résolue** : même à petite ROI « métrique-propre », on observe parfois
un striping **régulier** (période ~16 lignes brutes) absent de la réf. TSI. À élucider
(cf. pistes ci-dessous) — possible perte à intervalle régulier, ou subtilité de format.

---

## 7. Pistes recommandées pour la suite (par priorité)

1. **Vérité terrain octet-à-octet** : capturer la **même scène statique immobile**
   via (a) TSI SDK sur Windows (décodage correct) et (b) USB brut, puis aligner pour
   confirmer définitivement en-tête/packing/ordre des lignes et isoler l'artefact régulier.
   → c'est l'idée « image Windows de référence » ; utile pour le FORMAT, pas pour
   reconstruire des pertes aléatoires.
2. **Débit libusb-macOS** : augmenter le nombre/å taille des transferts async,
   tester `libusb_set_option`, buffers noyau ; envisager une extension C ou
   `libusb` en mode zéro-copie. Benchmarker le débit brut EP 0x83 isolément.
3. **Contournement fiable immédiat — pont réseau** : lancer l'acquisition dans la
   VM Windows (SDK TSI, qui marche) et streamer les frames au Mac (IP Mac
   172.16.9.191). Donne des images propres tout de suite, 100 % pilotable en Python.
4. **Mode dégradé** : acquérir en petites ROI / tuiles propres et recomposer ;
   ou binning (`hbin`/`vbin`) pour réduire le volume.

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
│   ├── camera_usb.py       ← driver principal (commandes OK ; lecture full à finir)
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
python3 macos/camera_usb.py --info      # handshake : sernum 18658, 2448x2048, 12 bits
```
La caméra doit être branchée sur le Mac (détachée de la VM Parallels).
