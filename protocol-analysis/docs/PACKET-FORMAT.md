# Image packet format on endpoint 0x83 (and the stale-data trap)

Findings from a debugging session on the stripes / diagonal "slant" problem (2026-10-22). Everything below was measured on a CS505MUP1, full frame 2448 x 2048, 12-bit packed pixels; the decoder is `kiralux/frame.py::unpack_mosaic`. Cross-checked against an independent driver (Xavier and William's), which decodes a real frame identically.

## What the stream really looks like

A frame is a sequence of 16384-byte USB packets (460 of them for a full frame, 7 536 640 bytes). Every packet starts with `90 90 <seq16>` (a 16-bit little-endian packet number, so the fourth byte is its high byte, 0 for frames this size):

| Packet | Layout |
|---|---|
| 0 | `90 90 00 00` + tag list (`TSI`, `FCNT`, `PCKH`, `PCKL`, `IFMT`, `IOFF`, `ENDT`, 8 bytes each: a 4-byte name and a 4-byte little-endian value) + **pixels from byte 60** (`ENDT` position + 8) to the end of the packet |
| n >= 1 | `90 90 <seq16>` + **16380 bytes of pixels** |

Once the headers are stripped (60 bytes on packet 0, 4 on the others) the pixels are **one continuous Mono12p stream**: 16324 bytes from packet 0 is not a multiple of 3, so a triplet straddles packets 0 and 1, and the last byte of each packet is pixel data. This is what the independent driver written by Xavier and William does (`_strip_packet_headers`: 60 / 4 bytes, concatenate, unpack once), and it is how `unpack_mosaic` works now.

Tags seen on a real frame: `FCNT` = 1 (frame counter), `IFMT` = 0x1001 (Mono12p), `IOFF` = 7, `PCKH` = 14, `PCKL` = 65240176 (meaning of these three unknown; `PCKH`/`PCKL` may be a 64-bit counter).

### History: what the first decoder got wrong

The very first decoder assumed a 16384-byte header with no pixels, then 5461 triplets per 16384-byte block. That gave:

* a shear of +2 px per packet = 0.45 px/row at width 2448 (10922 px per block / 2448 = 4.46 rows per block), seen as a "diagonal" in the image;
* a horizontal offset of the whole image, seen as a vertical seam where the two halves of the scene do not match.

The second decoder (3-byte header, 5460 triplets restarted in each packet, last byte dropped as "padding") removed both, but it was still wrong for **one pixel per packet**: the last byte of a packet was thrown away and the first triplet of the next packet was built from the header's high byte (0) instead. 456 pixels of 5 million, with a low byte of 0 or 1, off from their same-polarizer neighbours by ~120 ADU (median) against ~17 with the correct decoding. Invisible in a picture, not in DoLP/AoLP. Found by comparing with the other driver on a real raw frame: the two decodings differed only there.

How the format was found (all reproducible with a raw frame):

1. Estimate the row shift over 40 channel rows by cross-correlating horizontal derivatives: +18 channel px = 0.45 px/row with 5461 triplets/block, **0 with 5460**.
2. With 5460 triplets/block a vertical seam remained. Searching the start offset `q` in packet 0 (triplet-aligned, `3..400`) for the smallest column discontinuity gave `q = 60` with a ratio max/median jump of 1.3 (35 for every other offset), no seam, no junk rows at the bottom.
3. The four bytes at the start of each packet are `90 90 <n> 00` with `n` = 1, 2, 3...; packet 0 starts `90 90 00 00 54 53 49 00` (`..TSI.`). The tags end with `ENDT` followed by a 4-byte value.

Total check: 16324 bytes in packet 0 + 459 x 16380 = 7 534 144 bytes = 5 022 762 px worth, more than the 5 013 504 needed. The surplus is simply discarded.

## The stale-data trap (after an abrupt stop)

If a process is killed in the middle of a capture (`kill`, a crash), the camera keeps ~190 KB (193 536 bytes measured) of the interrupted frame in its pipe. Every following capture then **starts with that leftover**: the frame header (`TSI`) shows up at byte 194 564 instead of byte 4, every packet boundary is wrong by the same amount, and the image comes out scrambled (stripes, vertical seam, fringes that are not in the scene) even though the decoder is right. It persists across captures, because each capture leaves the tail of its own frame behind.

Symptoms: `bytes.find(b"TSI\0")` is not 4; `pk[:, 0] == 0x90` is true for no packet; `0x90` is periodic at some offset other than 0.

Recovery that worked: after `STOP`, read EP 0x83 until it times out (short timeout, 100-300 ms) and discard what comes; the next frame starts at the right place and stays right. Unplugging and replugging the camera also clears it (the process-kill case once left the camera unresponsive to commands, `USBTimeoutError` on the first command, until replugged).

Both drivers now do that drain once at initialisation, right after the first `STOP` (`drain_image_endpoint` in `camera_device.py`; it stops at the first timeout and is bounded to 256 reads). A cheap sanity check that is *not* implemented: bytes 4..8 of packet 0 are `TSI\0`, so a frame that does not start with it could be rejected or resynchronised.

**Do not mistake saturation for stripes.** A frame at 30 ms on a bright scene had a mean of 3981 out of 4095; with a percentile contrast stretch the row-to-row noise of the saturated pixels shows up as horizontal stripes. The same scene at 1 ms (mean ~300, seam ratio 1.1, no stripes) was clean. Check `mosaic.max()` and the mean before suspecting the decoder.

## Other things that turned out *not* to matter

* USB link speed: the camera enumerates at 5 Gb/s when connected correctly. Through an adapter or a USB 2 path it came up at 480 Mb/s and the frames were visibly worse; check `system_profiler SPUSBHostDataType` (`Link Speed`) first.
* The class (`Kiralux` in `camera.py` vs `KiraluxCameraDevice`): same capture sequence, identical frames in an A/B test.
* `readStream` chunk size (16 KB / 64 KB / 256 KB): the full frame always arrives; a 1 MB chunk collapses to ~2 MB/s.
* Reading before or after `START`.
* The stride/width: 2448 is right (the local-stride scan is insensitive on smooth scenes; use the shear measurement above instead).

## Remaining oddities

* The first row of the mosaic sometimes has a higher row-to-row jump than the others (possibly sensor reference rows).
* `examples/preview.py --intensity` shows only S0, large; the default shows S0, DoLP, AoLP, the four channels and the false color. Stop it by closing the window; killing the process triggers the stale-data trap above.
