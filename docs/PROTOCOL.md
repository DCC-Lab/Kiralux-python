# Protocole USB de la caméra ThorLabs CS505MUP1 (Kiralux) — reverse-engineering

> Obtenu par capture USBPcap d'une session d'acquisition réelle + décodage.
> Device : **VID 0x1313 / PID 0x4001**, USB 3.0 SuperSpeed, classe vendor (0xFF).
> Résultat clé : **protocole texte ASCII** auto-documenté — réimplémentable en
> pyusb/libusb sans aucun composant natif ThorLabs.

## 1. Descripteur (interface 0, classe 0xFF, 5 endpoints)

| Endpoint | Dir | Type | maxpkt | burst | Rôle |
|----------|-----|------|--------|-------|------|
| `0x02`   | OUT | BULK | 1024   | 1     | Envoi des commandes (ASCII) |
| `0x82`   | IN  | BULK | 1024   | 1     | Réponses aux commandes (ASCII) |
| `0x83`   | IN  | BULK | 1024   | 16    | Données image (chunks 16384 o) |
| `0x01`   | OUT | BULK | 1024   | 16    | OUT secondaire (non utilisé à l'acquisition) |
| `0x81`   | IN  | INTR | 128    | —     | Événements/statut (non requis) |

## 2. Framing des commandes

- Le host écrit un buffer de **1024 octets** sur `EP 0x02` : la commande en ASCII,
  terminée par `\0`, puis padding `\0` jusqu'à 1024.
- La caméra répond par un buffer **1024 o** sur `EP 0x82` : réponse ASCII `\0`-terminée.
- Réponse d'erreur : `error <code>,<message>` (ex. `error 4,Invalid command`).

## 3. Commandes (vocabulaire renvoyé par `discover`)

```
error echo id info ver ping model name sernum unlock camera_radix exp roi hbin vbin
hot_pixel_correction stop start arm disarm hwtrig nframes state statusled temperature
image_dims image_width image_height pixel_bit_depth pixel_size pixel_width_nm
pixel_height_nm pixel_byte_ordering vflip hflip gain blklvl imgpack debug_radix gpo
time frametime color color_filter_phase ir_filter_type color_correction_matrix
output_color_space default_white_balance_matrix polar_phase sensor_readout_time
tags nvstor sfr pixel_clock_count_base
```

**Chaque commande `X` possède une variante `X.disc`** qui renvoie sa description JSON
(syntaxe, min/max, défaut, flags r/w). Exemple :
```
gain.disc → {"gain": {"desc":"applies gain factor to image","syntax":"gain [dB]",
             "min":0,"max":480,"inc":1,"default":0,"flags":["w"],"response":["integer"]}}
```
→ Un script peut interroger `<cmd>.disc` pour auto-générer l'API complète.

### Commandes clés observées

| Commande            | Réponse            | Sens |
|---------------------|--------------------|------|
| `id`                | `000000f648...`    | identifiant device |
| `sernum`            | `18658`            | numéro de série |
| `model name`        | (CS505MUP1)        | modèle |
| `exp <us>`          | `<us>`             | exposition en microsecondes |
| `gain <dB>`         | `<v>`              | gain (0–480, en 0.1 dB ? cf. .disc) |
| `roi ...`           |                    | région d'intérêt |
| `hbin`/`vbin`       |                    | binning |
| `hwtrig <mode>`     | `none hi`          | trigger matériel (`none`=soft) |
| `nframes <n>`       | `<n>`              | frames par trigger |
| `image_width`       | `2448`             | largeur |
| `image_height`      | `2048`             | hauteur |
| `pixel_bit_depth`   | `12`               | profondeur |
| `arm`               | `armed`            | arme l'acquisition |
| `start`             | `running`          | déclenche (soft) → stream image sur `0x83` |
| `stop`              | `stopped`          | arrête |
| `disarm`            |                    | désarme |
| `temperature`       |                    | température capteur |
| `polar_phase`       |                    | phase polarisation (caméra polar) |

## 4. Séquence d'acquisition (une frame, software trigger)

Observée dans la capture (ordre exact) :
```
id                 → 000000f648...
sernum             → 18658
stop               → stopped            (s'assure de l'état arrêté)
discover           → <liste commandes>
exp 20000          → 20000              (expo 20 ms)
hwtrig none        → none hi            (mode software)
nframes 1          → 1
image_width        → 2448
image_height       → 2048
pixel_bit_depth    → 12
arm                → armed
start              → running
<< lecture sur EP 0x83 : nframes × width × height × 2 octets >>
   (ici 2448 × 2048 × 2 = 10 027 008 o, lus en chunks de 16384 o)
stop               → stopped
```

## 5. Format des pixels

- 12 bits significatifs, stockés en **uint16 little-endian** (2 o/pixel).
- Taille frame = `image_width × image_height × 2`.
- Caméra polarisation : l'image brute est une mosaïque de micro-polariseurs
  (0/45/90/135°). Le dé-mosaïquage polar se fait côté hôte (cf. `polar_phase`,
  et l'ancien pipeline `thorlabs_tsi_polarization_processor.dll`).

## 6. Implications pour macOS

- Aucun firmware à uploader (résident sur la caméra, FX3 self-boot).
- Classe vendor 0xFF → aucun driver noyau macOS ne réclame le device → **libusb
  peut le piloter directement**.
- Il suffit de : `brew install libusb`, `pip install pyusb numpy pillow`, puis
  écrire/lire sur les endpoints bulk. Voir `tools/camera_usb.py`.
- **Prérequis matériel** : débrancher la caméra de la VM Parallels (Devices → USB)
  pour que macOS la voie. On ne peut pas tester depuis macOS tant que la VM la tient.
