# Reverse-engineering du protocole USB de la Kiralux CS505MUP1

Ce dossier rassemble **la démarche** et **les outils** ayant permis de piloter la
caméra ThorLabs Kiralux CS505MUP1 en Python pur, sans aucune librairie native
ThorLabs. Le driver qui en résulte vit à la racine du dépôt (package `kiralux/`) ;
ici, on documente *comment on y est arrivé* et *comment refaire l'analyse*.

> Pour la référence exhaustive (identité matériel, table des endpoints, format de
> frame octet par octet, séquence d'acquisition) : [`HANDOFF.md`](HANDOFF.md) et
> [`docs/PROTOCOL.md`](docs/PROTOCOL.md). [`REPORT.html`](REPORT.html) est le
> rapport visuel. Ce document-ci reste volontairement synthétique.

## La démarche, en cinq temps

1. **Observer le logiciel d'origine.** La caméra était pilotée par ThorImage sur
   une VM Windows (Parallels). Un driver générique Cypress (CYUSB3) place toute la
   logique en espace utilisateur : rien dans le noyau à imiter, tout passe par des
   transferts USB bulk observables. On capture donc une session complète au niveau
   USB avec **USBPcap** (`tools/capture/`), puis on exporte le trafic.

2. **Décoder le dialogue de commande.** Le trafic sur les endpoints `0x02`/`0x82`
   s'est révélé être du **texte ASCII** : des commandes écrites dans un buffer de
   1024 octets terminé par `\0`, des réponses lues de même. `tools/transcript.py`
   et `clean_capture.py` reconstruisent ce dialogue lisible
   ([`captures/transcript.txt`](captures/transcript.txt)). Découverte clé : la
   caméra **s'auto-documente** — `discover` liste toutes les commandes, et
   `<cmd>.disc` donne la syntaxe JSON de chacune. Le vocabulaire complet est donc
   obtenu de la caméra elle-même, pas deviné.

3. **Rejouer depuis Python.** Avec libusb (`pyusb`/`usb1`), on énumère la caméra
   (VID `0x1313` / PID `0x4001`, classe vendor `0xFF`, donc aucun driver noyau
   macOS ne la réclame), on réclame l'interface, et on reproduit la séquence
   `stop → exp → hwtrig none → nframes 1 → arm → start → [lire 0x83] → stop`. Les
   scripts `*_grab.py` sont les variantes successives de lecture de l'image.

4. **Décoder l'image.** Les pixels sont du **12-bit packé Mono12p** (2 pixels sur
   3 octets). La bonne variante de dépaquetage a été trouvée en minimisant le bruit
   horizontal (`unpack_test.py`, `demosaic_test.py`, `hypotheses.py`,
   `bruteforce.py`), puis la mosaïque de polarisation 2×2 (IMX250MZR) a été calée
   en S0/DoLP/AoLP (`polar_channels.py`).

5. **Résoudre le striping plein format** — le cœur du problème (détail ci-dessous).

## Le problème de stripes — ce qui l'a résolu

En plein format, l'image sortait **rayée**. Le diagnostic a demandé deux outils :
une analyse de *débit* (le pcap montrait que le SDK TSI lit une frame en 59 ms =
128 MB/s) et une analyse de *périodicité* des bandes (`autocorr.py`,
`rowprofile.py`, `find_stride.py`, `stride_scan.py`). Deux causes, deux correctifs,
tous deux dans le driver final :

- **Débit** : lire l'EP `0x83` en transferts de **16384 octets** (la taille de
  burst SuperSpeed). En 128 Ko, le débit s'effondre à ~1 MB/s et la caméra
  déborde ; en 16384 o, on atteint ~95 MB/s, 100 % reçu.
- **Alignement (la vraie cause des bandes)** : les triplets 12-bit **ne
  traversent pas** les frontières de bloc de 16384 o. Comme `16384 mod 3 = 1`,
  décoder le flux en continu décale l'alignement d'un octet par bloc, avec un
  battement de période `3 × 16384 o = 13.39 lignes` — exactement les bandes
  observées. **Fix : décoder chaque bloc de 16384 o indépendamment**, et
  concaténer les octets de « queue » (1/bloc) pour compléter les 306 derniers
  pixels. Résultat : `vmed 134 → 3`, 2048 lignes pleines.

Fausses pistes écartées (reproduites à l'identique sur Linux, donc *pas* un bug
d'OS) : perte libusb-macOS, hardware, stride/largeur, phase de mosaïque.

## Inventaire des outils (`tools/`)

Scripts d'analyse (non nécessaires à l'usage du driver ; conservés pour reproduire
ou prolonger l'étude) :

| Catégorie | Scripts représentatifs | Rôle |
|---|---|---|
| **Capture** | `capture/` (USBPcap `.ps1`/`.cmd`, `transcript.py`, `parse_usb.py`, `parse_descriptor.py`), `clean_capture.py` | Capturer la session USBPcap sous Windows, décoder le dialogue ASCII et les descripteurs |
| **Débit / lecture** | `async_grab*.py`, `thread_grab.py`, `slow_grab.py`, `fast_capture.py`, `grab_bigread.py`, `probe_rate.py`, `timing_test.py` | Variantes de lecture de l'EP 0x83 ; mesure du débit selon la taille de transfert |
| **Format / stride** | `find_stride.py`, `stride_scan.py`, `find_width.py`, `autocorr.py`, `rowprofile.py`, `deshear.py`, `unpack_test.py`, `unpack60.py`, `demosaic_test.py`, `diag_pack.py`, `hypotheses.py`, `bruteforce.py` | Trouver l'origine des bandes, la bonne variante de dépaquetage 12-bit, l'en-tête |
| **ROI / recadrage** | `roi_sweep.py`, `test_roi*.py`, `crop_test.py`, `crop_s0.py`, `full_view.py` | Corréler taille de ROI et propreté de l'image |
| **Polarisation** | `polar_channels.py`, `s0_off60.py` | Caler la mosaïque 2×2 → S0/DoLP/AoLP |
| **Référence TSI** | `compare_tsi.py`, `capture/tsi_discover.py`, `capture/tsi_grab_frame.py` | Comparer à l'acquisition du SDK ThorLabs d'origine |
| **Linux** | `linux_grab.py`, `linux_test.py` | Rejouer l'acquisition sous Linux (confirme : bug de format, pas d'OS) |

## Données de référence (`captures/`)

- [`cam_session.pcap`](captures/cam_session.pcap) — capture USBPcap d'une session ThorImage complète.
- [`transcript.txt`](captures/transcript.txt) / `decoded.txt` — dialogue de commande ASCII décodé.
- `raw_big.bin` — une frame plein format brute (7 536 640 o) telle que lue sur
  l'EP 0x83, pour rejouer le décodage **hors ligne** (sans caméra).
