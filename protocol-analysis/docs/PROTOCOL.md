# USB protocol of the ThorLabs CS505MUP1 (Kiralux) camera — reverse-engineering

> Obtained by USBPcap capture of a real acquisition session + decoding.
> Device: **VID 0x1313 / PID 0x4001**, USB 3.0 SuperSpeed, vendor class (0xFF).
> Key result: **self-documenting ASCII text protocol** — reimplementable in
> pyusb/libusb without any native ThorLabs component.

## 1. Descriptor (interface 0, class 0xFF, 5 endpoints)

| Endpoint | Dir | Type | maxpkt | burst | Role |
|----------|-----|------|--------|-------|------|
| `0x02`   | OUT | BULK | 1024   | 1     | Sending commands (ASCII) |
| `0x82`   | IN  | BULK | 1024   | 1     | Responses to commands (ASCII) |
| `0x83`   | IN  | BULK | 1024   | 16    | Image data (16384-byte chunks) |
| `0x01`   | OUT | BULK | 1024   | 16    | Secondary OUT (unused during acquisition) |
| `0x81`   | IN  | INTR | 128    | —     | Events/status (not required) |

## 2. Command framing

- The host writes a **1024-byte** buffer to `EP 0x02`: the command in ASCII,
  terminated by `\0`, then `\0` padding up to 1024.
- The camera replies with a **1024-byte** buffer on `EP 0x82`: `\0`-terminated ASCII response.
- Error response: `error <code>,<message>` (e.g. `error 4,Invalid command`).

## 3. Commands (vocabulary returned by `discover`)

```
error echo id info ver ping model name sernum unlock camera_radix exp roi hbin vbin
hot_pixel_correction stop start arm disarm hwtrig nframes state statusled temperature
image_dims image_width image_height pixel_bit_depth pixel_size pixel_width_nm
pixel_height_nm pixel_byte_ordering vflip hflip gain blklvl imgpack debug_radix gpo
time frametime color color_filter_phase ir_filter_type color_correction_matrix
output_color_space default_white_balance_matrix polar_phase sensor_readout_time
tags nvstor sfr pixel_clock_count_base
```

**Each command `X` has an `X.disc` variant** that returns its JSON description
(syntax, min/max, default, r/w flags). Example:
```
gain.disc → {"gain": {"desc":"applies gain factor to image","syntax":"gain [dB]",
             "min":0,"max":480,"inc":1,"default":0,"flags":["w"],"response":["integer"]}}
```
→ A script can query `<cmd>.disc` to auto-generate the complete API.

### Key commands observed

| Command             | Response           | Meaning |
|---------------------|--------------------|------|
| `id`                | `000000f648...`    | device identifier |
| `sernum`            | `18658`            | serial number |
| `model name`        | (CS505MUP1)        | model |
| `exp <us>`          | `<us>`             | exposure in microseconds |
| `gain <dB>`         | `<v>`              | gain (0–480, in 0.1 dB? cf. .disc) |
| `roi ...`           |                    | region of interest |
| `hbin`/`vbin`       |                    | binning |
| `hwtrig <mode>`     | `none hi`          | hardware trigger (`none`=soft) |
| `nframes <n>`       | `<n>`              | frames per trigger |
| `image_width`       | `2448`             | width |
| `image_height`      | `2048`             | height |
| `pixel_bit_depth`   | `12`               | depth |
| `arm`               | `armed`            | arms the acquisition |
| `start`             | `running`          | triggers (soft) → streams image on `0x83` |
| `stop`              | `stopped`          | stops |
| `disarm`            |                    | disarms |
| `temperature`       |                    | sensor temperature |
| `polar_phase`       |                    | polarization phase (polar camera) |

## 4. Acquisition sequence (one frame, software trigger)

Observed in the capture (exact order):
```
id                 → 000000f648...
sernum             → 18658
stop               → stopped            (ensures the stopped state)
discover           → <command list>
exp 20000          → 20000              (20 ms exposure)
hwtrig none        → none hi            (software mode)
nframes 1          → 1
image_width        → 2448
image_height       → 2048
pixel_bit_depth    → 12
arm                → armed
start              → running
<< read on EP 0x83: nframes × width × height × 2 bytes >>
   (here 2448 × 2048 × 2 = 10,027,008 bytes, read in 16384-byte chunks)
stop               → stopped
```

## 5. Pixel format

- 12 significant bits, stored as **uint16 little-endian** (2 bytes/pixel).
- Frame size = `image_width × image_height × 2`.
- Polarization camera: the raw image is a mosaic of micro-polarizers
  (0/45/90/135°). Polar de-mosaicing is done host-side (cf. `polar_phase`,
  and the legacy `thorlabs_tsi_polarization_processor.dll` pipeline).

## 6. Implications for macOS

- No firmware to upload (resident on the camera, FX3 self-boot).
- Vendor class 0xFF → no macOS kernel driver claims the device → **libusb
  can drive it directly**.
- All that is needed: `brew install libusb`, `pip install pyusb numpy pillow`, then
  write to/read from the bulk endpoints. See `tools/camera_usb.py`.
- **Hardware prerequisite**: unplug the camera from the Parallels VM (Devices → USB)
  so that macOS can see it. You cannot test from macOS while the VM holds it.
