# Image packet format on endpoint 0x83 (and the stale-data trap)

Findings from a debugging session on the stripes / diagonal "slant" problem (2026-10-22). Everything below was measured on a CS505MUP1, full frame 2448 x 2048, 12-bit packed pixels; the decoder fix is `kiralux/frame.py::unpack_mosaic`.

## What the stream really looks like

A frame is a sequence of 16384-byte USB packets (460 of them for a full frame, 7 536 640 bytes). The pixel stream is **not** contiguous across them:

| Packet | Layout |
|---|---|
| 0 | `90 90 <seq>` + tag list (`TSI`, `FCNT`, `PCKH`, `PCKL`, `IFMT`, `IOFF`, `ENDT`, 8 bytes each) + **the first pixels of the image, starting right after `ENDT`+8 (byte 60)** + 1 padding byte |
| n >= 1 | `90 90 <seq>` + **16380 bytes = 5460 triplets** + 1 padding byte |

Two bytes of every packet's pixel area are therefore lost to the header, and 12-bit triplets restart in each packet. The old decoder assumed a 16384-byte header with no pixels and 5461 triplets per block; that gave:

* a shear of +2 px per packet = 0.45 px/row at width 2448 (10922 px per block / 2448 = 4.46 rows per block), seen as a "diagonal" in the image;
* a horizontal offset of the whole image, seen as a vertical seam where the two halves of the scene do not match.

How it was found (all reproducible with a raw frame):

1. Estimate the row shift over 40 channel rows by cross-correlating horizontal derivatives: +18 channel px = 0.45 px/row with 5461 triplets/block, **0 with 5460**.
2. With 5460 triplets/block a vertical seam remained. Searching the start offset `q` in packet 0 (triplet-aligned, `3..400`) for the smallest column discontinuity gave `q = 60` with a ratio max/median jump of 1.3 (35 for every other offset), no seam, no junk rows at the bottom.
3. The four bytes at the start of each packet are `90 90 <n> 00` with `n` = 1, 2, 3...; packet 0 starts `90 90 00 00 54 53 49 00` (`..TSI.`). The tags end with `ENDT` followed by a 4-byte value.

Total check: 10882 px in packet 0 (from byte 60) + 459 x 10920 = 5 023 162 px, more than the 5 013 504 needed. The surplus is simply discarded.

## The stale-data trap (after an abrupt stop)

If a process is killed in the middle of a capture (`kill`, a crash), the camera keeps ~190 KB (193 536 bytes measured) of the interrupted frame in its pipe. Every following capture then **starts with that leftover**: the frame header (`TSI`) shows up at byte 194 564 instead of byte 4, every packet boundary is wrong by the same amount, and the image comes out scrambled (stripes, vertical seam, fringes that are not in the scene) even though the decoder is right. It persists across captures, because each capture leaves the tail of its own frame behind.

Symptoms: `bytes.find(b"TSI\0")` is not 4; `pk[:, 0] == 0x90` is true for no packet; `0x90` is periodic at some offset other than 0.

Recovery that worked: after `STOP`, read EP 0x83 until it times out (short timeout, 100-300 ms) and discard what comes; the next frame starts at the right place and stays right. Unplugging and replugging the camera also clears it (the process-kill case once left the camera unresponsive to commands, `USBTimeoutError` on the first command, until replugged).

**TODO (not done yet, untested on hardware at the time of writing)**: do that drain once at initialisation in `Kiralux.__init__` and `KiraluxCameraDevice.doInitializeDevice`, right after the first `STOP`. A cheap sanity check on every frame is that bytes 4..8 of packet 0 are `TSI\0`; raise a clear error (or resynchronise on the `TSI` tag) when they are not.

## Other things that turned out *not* to matter

* USB link speed: the camera enumerates at 5 Gb/s when connected correctly. Through an adapter or a USB 2 path it came up at 480 Mb/s and the frames were visibly worse; check `system_profiler SPUSBHostDataType` (`Link Speed`) first.
* The class (`Kiralux` in `camera.py` vs `KiraluxCameraDevice`): same capture sequence, identical frames in an A/B test.
* `readStream` chunk size (16 KB / 64 KB / 256 KB): the full frame always arrives; a 1 MB chunk collapses to ~2 MB/s.
* Reading before or after `START`.
* The stride/width: 2448 is right (the local-stride scan is insensitive on smooth scenes; use the shear measurement above instead).

## Remaining oddities

* The first row of the mosaic sometimes has a higher row-to-row jump than the others (possibly sensor reference rows).
* `examples/preview.py --intensity` shows only S0, large; the default shows S0, DoLP, AoLP, the four channels and the false color. Stop it by closing the window; killing the process triggers the stale-data trap above.
