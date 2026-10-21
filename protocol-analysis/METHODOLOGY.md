# Reverse-engineering the Kiralux CS505MUP1 USB protocol

This folder gathers **the approach** and **the tools** that made it possible to
drive the ThorLabs Kiralux CS505MUP1 camera in pure Python, with no ThorLabs
native libraries. The resulting driver lives at the repository root (the
`kiralux/` package); here we document *how we got there* and *how to redo the
analysis*.

> For the byte-level reference (hardware identity, endpoint table, frame format,
> acquisition sequence), see [`docs/PROTOCOL.md`](docs/PROTOCOL.md) and
> [`docs/SDK_MAP.md`](docs/SDK_MAP.md). [`REPORT.html`](REPORT.html) is the visual
> report. This document stays deliberately concise.

## The approach, in five stages

1. **Observe the original software.** The camera was driven by ThorImage on a
   Windows VM (Parallels). A generic Cypress driver (CYUSB3) puts all the logic in
   user space: nothing in the kernel to imitate, everything goes through
   observable USB bulk transfers. So we capture a full session at the USB level
   with **USBPcap** (`tools/capture/`), then export the traffic.

2. **Decode the command dialog.** The traffic on endpoints `0x02`/`0x82` turned
   out to be **ASCII text**: commands written into a 1024-byte buffer terminated
   by `\0`, responses read back the same way. `tools/capture/transcript.py` and
   `clean_capture.py` reconstruct this readable dialog
   ([`captures/transcript.txt`](captures/transcript.txt)). Key discovery: the
   camera **documents itself** — `discover` lists every command, and `<cmd>.disc`
   gives the JSON syntax of each one. The full vocabulary is therefore obtained
   from the camera itself, not guessed.

3. **Replay from Python.** With libusb (`pyusb`/`usb1`), we enumerate the camera
   (VID `0x1313` / PID `0x4001`, vendor class `0xFF`, so no macOS kernel driver
   claims it), claim the interface, and reproduce the sequence
   `stop -> exp -> hwtrig none -> nframes 1 -> arm -> start -> [read 0x83] -> stop`.
   The `*_grab.py` scripts are the successive variants of the image read.

4. **Decode the image.** The pixels are **12-bit packed Mono12p** (2 pixels per 3
   bytes). The correct unpacking variant was found by minimizing horizontal noise
   (`unpack_test.py`, `demosaic_test.py`, `hypotheses.py`, `bruteforce.py`), then
   the 2x2 polarization mosaic (IMX250MZR) was aligned into S0/DoLP/AoLP
   (`polar_channels.py`).

5. **Resolve the full-frame striping** — the core problem (detail below).

## The striping problem — what fixed it

At full frame, the image came out **striped**. The diagnosis needed two tools: a
*throughput* analysis (the pcap showed the TSI SDK reads a frame in 59 ms =
128 MB/s) and a *periodicity* analysis of the stripes (`autocorr.py`,
`rowprofile.py`, `find_stride.py`, `stride_scan.py`). Two causes, two fixes, both
in the final driver:

- **Throughput**: read endpoint `0x83` in **16384-byte transfers** (the
  SuperSpeed burst size). At 128 KB, throughput collapses to ~1 MB/s and the
  camera overruns; at 16384 bytes, we reach ~95 MB/s, 100% received.
- **Alignment (the real cause of the stripes)**: 12-bit triplets **do not cross**
  the 16384-byte block boundaries. Since `16384 mod 3 = 1`, decoding the stream
  as a continuum shifts the triplet alignment by one byte per block, with a beat
  period of `3 x 16384 bytes = 13.39 lines` — exactly the stripes observed.
  **Fix: decode each 16384-byte block independently**, and concatenate the "tail"
  bytes (1 per block) to complete the last 306 pixels. Result: `vmed 134 -> 3`,
  a full 2048 lines.

False leads ruled out (reproduced identically on Linux, so *not* an OS bug):
libusb-macOS loss, hardware, stride/width, mosaic phase.

## Tool inventory (`tools/`)

Analysis scripts (not needed to use the driver; kept to reproduce or extend the
study):

| Category | Representative scripts | Role |
|---|---|---|
| **Capture** | `capture/` (USBPcap `.ps1`/`.cmd`, `transcript.py`, `parse_usb.py`, `parse_descriptor.py`), `clean_capture.py` | Capture the USBPcap session on Windows, decode the ASCII dialog and the descriptors |
| **Throughput / read** | `async_grab*.py`, `thread_grab.py`, `slow_grab.py`, `fast_capture.py`, `grab_bigread.py`, `probe_rate.py`, `timing_test.py` | Variants of the 0x83 read; throughput vs transfer size |
| **Format / stride** | `find_stride.py`, `stride_scan.py`, `find_width.py`, `autocorr.py`, `rowprofile.py`, `deshear.py`, `unpack_test.py`, `unpack60.py`, `demosaic_test.py`, `diag_pack.py`, `hypotheses.py`, `bruteforce.py` | Find the origin of the stripes, the correct 12-bit unpacking variant, the header |
| **ROI / cropping** | `roi_sweep.py`, `test_roi*.py`, `crop_test.py`, `crop_s0.py`, `full_view.py` | Correlate ROI size with image cleanliness |
| **Polarization** | `polar_channels.py`, `s0_off60.py` | Align the 2x2 mosaic -> S0/DoLP/AoLP |
| **TSI reference** | `compare_tsi.py`, `capture/tsi_discover.py`, `capture/tsi_grab_frame.py` | Compare against the original ThorLabs SDK acquisition |
| **Linux** | `linux_grab.py`, `linux_test.py` | Replay the acquisition on Linux (confirms: a format bug, not an OS one) |

## Reference data (`captures/`)

- [`cam_session.pcap`](captures/cam_session.pcap) — USBPcap capture of a full ThorImage session.
- [`transcript.txt`](captures/transcript.txt) / `decoded.txt` — decoded ASCII command dialog.
- `raw_big.bin` — one raw full-frame (7,536,640 bytes) as read from endpoint
  `0x83`, to replay the decoding **offline** (no camera needed).
