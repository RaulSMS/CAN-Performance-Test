# CAN / CANopen transfer speed: results

**Question:** how long does it take to transfer a file (e.g. a firmware image) from a
TCU to an ECU over CAN / CANopen, at different bitrates and with other traffic on the bus?

**Headline KPI:** minutes per MB (MB = 1,000,000 bytes). The 1 MB and 100 MB times below are
simply min/MB × 1 and × 100.

Run: 2026-11-08 16:05:06 · Tool: `can_speed_test.py` · Raw data: `results_v3.csv` · Bus logs: `candump_logs/20261108_160235`

## Test setup

- One Raspberry Pi 4 with a dual-channel PiCAN board (two MCP2515 CAN controllers on SPI),
  interfaces **pican1** and **pican2**, both wired to the **same CAN bus** with 120 Ω at both ends.
  pican1 plays the **sender (TCU)**, pican2 the **receiver (ECU)**.
- Classic CAN, 11-bit IDs, 8-byte frames. Bitrates: 125 kbit/s, 250 kbit/s, 500 kbit/s, 1000 kbit/s.
- **Background load** simulates other machine traffic already on the bus: a separate
  process sends filler frames (ID 0x050) at 0 / 30 / 60 % of the bus capacity. ID 0x050 has a
  *higher* priority than the test traffic, so the transfer always has to wait for it
  (pessimistic, like busy machine traffic).

## What each test does

| Test | Measured or calculated | What it does | What it tells you |
|---|---|---|---|
| **Theoretical maximum** | calculated | The most 8-byte frames that fit on the bus per second (44 + 64 bits per frame + 3 bits gap, no stuff bits), minus the background load. | Absolute ceiling. Nothing can be faster. |
| **Raw CAN** | measured | pican1 sends frames back-to-back to pican2 as fast as possible. All 8 bytes are payload (a sequence number + filler); no protocol, no handshake. pican2 checks the sequence numbers for lost or repeated frames. | Best case for *any* protocol on this bus. About 86–94 % of the theoretical maximum, because real frames contain a few extra "stuff bits". |
| **Block transfer estimate** | calculated from Raw | CANopen *SDO block transfer*, the fast CANopen mode normally used for firmware downloads. Each frame carries 7 data bytes (1 byte is a sequence number); after every block of N frames the receiver sends one acknowledge frame, and the sender waits for it (turnaround time, here 2 ms). Calculated from the measured raw frame time: per block, N × 7 bytes take (N + 1) frame times + turnaround. Shown for N = 127, 32, 16 frames per block (127 is the maximum; many devices use smaller blocks). | Realistic planning figure for a CANopen firmware download, as long as the ECU acknowledges quickly. |
| **SDO segmented download** | measured | Standard CANopen SDO download, the simplest mode: the client (pican2) writes a 4 KB object to the server (pican1) and must wait for an acknowledge after **every** 7-byte frame. Each transfer is checked byte for byte. Result is the median of 3 transfers. | Worst-case "plain" CANopen. Shows how much a ping-pong protocol loses when every frame waits for an answer. |

Why block transfer is not measured directly: the CANopen library used here (python-canopen) has no
block transfer on its server side. A real measurement needs a CANopen stack such as CANopenNode
or the real target ECU.

## Summary: time for a 100 MB file

**Background load 0 %**

| Bitrate | Raw CAN (best case) | Block transfer, 127 frames/block | Block transfer, 16 frames/block | SDO segmented |
|---|---|---|---|---|
| 125 kbit/s | 3 h 17 min | 3 h 50 min | 4 h 29 min | 10 h 06 min |
| 250 kbit/s | 1 h 39 min | 1 h 58 min | 2 h 30 min | 6 h 04 min |
| 500 kbit/s | 49 min 42 s | 1 h 01 min | 1 h 30 min | 4 h 13 min |
| 1000 kbit/s | 25 min 36 s \* | 32 min 36 s | 1 h 00 min | 3 h 10 min |

**Background load 30 %**

| Bitrate | Raw CAN (best case) | Block transfer, 127 frames/block | Block transfer, 16 frames/block | SDO segmented |
|---|---|---|---|---|
| 125 kbit/s | 4 h 50 min | 5 h 38 min | 6 h 22 min | 13 h 12 min |
| 250 kbit/s | 2 h 22 min | 2 h 48 min | 3 h 23 min | 7 h 36 min |
| 500 kbit/s | 1 h 12 min | 1 h 27 min | 1 h 58 min | 5 h 20 min |
| 1000 kbit/s | 36 min 36 s | 45 min 54 s | 1 h 14 min | 4 h 06 min |

**Background load 60 %**

| Bitrate | Raw CAN (best case) | Block transfer, 127 frames/block | Block transfer, 16 frames/block | SDO segmented |
|---|---|---|---|---|
| 125 kbit/s | 8 h 37 min | 9 h 59 min | 10 h 57 min | 20 h 13 min |
| 250 kbit/s | 4 h 16 min | 4 h 59 min | 5 h 41 min | 10 h 20 min |
| 500 kbit/s | 2 h 15 min | 2 h 39 min | 3 h 14 min | 7 h 24 min |
| 1000 kbit/s | 1 h 03 min | 1 h 17 min | 1 h 47 min | 6 h 47 min |

## Detailed results per bitrate

KiB/s = payload throughput (1 KiB = 1024 bytes). min/MB = minutes per 1,000,000 bytes.

### 125 kbit/s

| Test | Load | KiB/s | min/MB | 1 MB | 100 MB |
|---|---|---|---|---|---|
| Theoretical maximum (calculated) | 0 % | 8.80 | 1.85 | 1 min 51 s | 3 h 05 min |
| Theoretical maximum (calculated) | 30 % | 6.16 | 2.64 | 2 min 39 s | 4 h 24 min |
| Theoretical maximum (calculated) | 60 % | 3.52 | 4.63 | 4 min 38 s | 7 h 42 min |
| Raw CAN, pican1 → pican2 (measured) | 0 % | 8.26 | 1.97 | 1 min 58 s | 3 h 17 min |
| Raw CAN, pican1 → pican2 (measured) | 30 % | 5.60 | 2.91 | 2 min 54 s | 4 h 50 min |
| Raw CAN, pican1 → pican2 (measured) | 60 % | 3.15 | 5.17 | 5 min 10 s | 8 h 37 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 0 % | 7.05 | 2.31 | 2 min 18 s | 3 h 50 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 30 % | 4.81 | 3.38 | 3 min 23 s | 5 h 38 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 60 % | 2.72 | 5.99 | 6 min 00 s | 9 h 59 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 0 % | 6.58 | 2.47 | 2 min 28 s | 4 h 07 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 30 % | 4.55 | 3.57 | 3 min 34 s | 5 h 57 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 60 % | 2.61 | 6.24 | 6 min 15 s | 10 h 24 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 0 % | 6.05 | 2.69 | 2 min 42 s | 4 h 29 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 30 % | 4.25 | 3.83 | 3 min 50 s | 6 h 22 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 60 % | 2.48 | 6.58 | 6 min 34 s | 10 h 57 min |
| SDO segmented download (measured) | 0 % | 2.68 | 6.07 | 6 min 04 s | 10 h 06 min |
| SDO segmented download (measured) | 30 % | 2.05 | 7.92 | 7 min 55 s | 13 h 12 min |
| SDO segmented download (measured) | 60 % | 1.34 | 12.13 | 12 min 08 s | 20 h 13 min |

### 250 kbit/s

| Test | Load | KiB/s | min/MB | 1 MB | 100 MB |
|---|---|---|---|---|---|
| Theoretical maximum (calculated) | 0 % | 17.60 | 0.93 | 56 s | 1 h 32 min |
| Theoretical maximum (calculated) | 30 % | 12.32 | 1.32 | 1 min 19 s | 2 h 12 min |
| Theoretical maximum (calculated) | 60 % | 7.04 | 2.31 | 2 min 19 s | 3 h 51 min |
| Raw CAN, pican1 → pican2 (measured) | 0 % | 16.38 | 0.99 | 1 min 00 s | 1 h 39 min |
| Raw CAN, pican1 → pican2 (measured) | 30 % | 11.39 | 1.43 | 1 min 26 s | 2 h 22 min |
| Raw CAN, pican1 → pican2 (measured) | 60 % | 6.34 | 2.57 | 2 min 34 s | 4 h 16 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 0 % | 13.77 | 1.18 | 1 min 11 s | 1 h 58 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 30 % | 9.67 | 1.68 | 1 min 41 s | 2 h 48 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 60 % | 5.43 | 3.00 | 3 min 00 s | 4 h 59 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 0 % | 12.33 | 1.32 | 1 min 19 s | 2 h 12 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 30 % | 8.88 | 1.83 | 1 min 50 s | 3 h 03 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 60 % | 5.13 | 3.17 | 3 min 10 s | 5 h 17 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 0 % | 10.82 | 1.50 | 1 min 30 s | 2 h 30 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 30 % | 8.01 | 2.03 | 2 min 02 s | 3 h 23 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 60 % | 4.76 | 3.42 | 3 min 25 s | 5 h 41 min |
| SDO segmented download (measured) | 0 % | 4.46 | 3.65 | 3 min 39 s | 6 h 04 min |
| SDO segmented download (measured) | 30 % | 3.57 | 4.56 | 4 min 34 s | 7 h 36 min |
| SDO segmented download (measured) | 60 % | 2.62 | 6.21 | 6 min 13 s | 10 h 20 min |

### 500 kbit/s

| Test | Load | KiB/s | min/MB | 1 MB | 100 MB |
|---|---|---|---|---|---|
| Theoretical maximum (calculated) | 0 % | 35.19 | 0.46 | 28 s | 46 min 18 s |
| Theoretical maximum (calculated) | 30 % | 24.63 | 0.66 | 40 s | 1 h 06 min |
| Theoretical maximum (calculated) | 60 % | 14.08 | 1.16 | 1 min 09 s | 1 h 55 min |
| Raw CAN, pican1 → pican2 (measured) | 0 % | 32.77 | 0.50 | 30 s | 49 min 42 s |
| Raw CAN, pican1 → pican2 (measured) | 30 % | 22.41 | 0.73 | 44 s | 1 h 12 min |
| Raw CAN, pican1 → pican2 (measured) | 60 % | 12.04 | 1.35 | 1 min 21 s | 2 h 15 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 0 % | 26.70 | 0.61 | 37 s | 1 h 01 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 30 % | 18.62 | 0.87 | 52 s | 1 h 27 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 60 % | 10.20 | 1.59 | 1 min 36 s | 2 h 39 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 0 % | 22.17 | 0.73 | 44 s | 1 h 13 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 30 % | 16.20 | 1.00 | 1 min 00 s | 1 h 40 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 60 % | 9.34 | 1.74 | 1 min 45 s | 2 h 54 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 0 % | 18.07 | 0.90 | 54 s | 1 h 30 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 30 % | 13.80 | 1.18 | 1 min 11 s | 1 h 58 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 60 % | 8.39 | 1.94 | 1 min 56 s | 3 h 14 min |
| SDO segmented download (measured) | 0 % | 6.43 | 2.53 | 2 min 32 s | 4 h 13 min |
| SDO segmented download (measured) | 30 % | 5.08 | 3.20 | 3 min 12 s | 5 h 20 min |
| SDO segmented download (measured) | 60 % | 3.66 | 4.45 | 4 min 27 s | 7 h 24 min |

### 1000 kbit/s

| Test | Load | KiB/s | min/MB | 1 MB | 100 MB |
|---|---|---|---|---|---|
| Theoretical maximum (calculated) | 0 % | 70.38 | 0.23 | 14 s | 23 min 06 s |
| Theoretical maximum (calculated) | 30 % | 49.27 | 0.33 | 20 s | 33 min 00 s |
| Theoretical maximum (calculated) | 60 % | 28.15 | 0.58 | 35 s | 57 min 48 s |
| Raw CAN, pican1 → pican2 (measured) \* | 0 % | 63.49 | 0.26 | 15 s | 25 min 36 s |
| Raw CAN, pican1 → pican2 (measured) | 30 % | 44.45 | 0.37 | 22 s | 36 min 36 s |
| Raw CAN, pican1 → pican2 (measured) | 60 % | 25.54 | 0.64 | 38 s | 1 h 03 min |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 0 % | 49.92 | 0.33 | 20 s | 32 min 36 s |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 30 % | 35.44 | 0.46 | 28 s | 45 min 54 s |
| Block transfer estimate (127 frames/block, 2 ms turnaround) | 60 % | 21.09 | 0.77 | 46 s | 1 h 17 min |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 0 % | 36.65 | 0.44 | 27 s | 44 min 24 s |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 30 % | 28.05 | 0.58 | 35 s | 58 min 00 s |
| Block transfer estimate (32 frames/block, 2 ms turnaround) | 60 % | 18.09 | 0.90 | 54 s | 1 h 30 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 0 % | 27.04 | 0.60 | 36 s | 1 h 00 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 30 % | 21.93 | 0.74 | 45 s | 1 h 14 min |
| Block transfer estimate (16 frames/block, 2 ms turnaround) | 60 % | 15.19 | 1.07 | 1 min 04 s | 1 h 47 min |
| SDO segmented download (measured) | 0 % | 8.54 | 1.91 | 1 min 54 s | 3 h 10 min |
| SDO segmented download (measured) | 30 % | 6.60 | 2.47 | 2 min 28 s | 4 h 06 min |
| SDO segmented download (measured) | 60 % | 4.00 | 4.07 | 4 min 04 s | 6 h 47 min |

## How to read these numbers

- **Raw CAN reaches about 86–94 % of the theoretical maximum.** The rest are stuff bits the CAN
  controller inserts into every frame.
- **Block transfer is the number to plan with** for a CANopen firmware download: about
  79–86 % of raw with 127-frame blocks. It is lowest at 1 Mbit/s and with small blocks, because
  the fixed turnaround wait after each block weighs more when the block itself is sent faster.
- **Segmented SDO is much slower** (13–43 % of raw here) because every 7 bytes need a full
  request/acknowledge round trip. Its speed is set mostly by how fast the other side answers, not
  by the bus: on this Pi one round trip takes about 0.8 ms even at 1 Mbit/s, so going from
  125 kbit/s to 1 Mbit/s (8× the bus speed) makes SDO only about 3× faster. These numbers include
  the Raspberry Pi's own reaction time (Linux + Python + SPI CAN controller), which varies by about
  ±20 % from run to run. A real ECU may react faster or slower.
- **Background load** slows raw and block transfer roughly in proportion to the bus share it
  takes. Segmented SDO lost relatively less in this test (e.g. at 500 kbit/s with 60 % load:
  raw −63 %, SDO −43 %), because most of its time is spent waiting for the answer, not on the bus.
- **Firmware updates on real ECUs:** the ECU often delays its acknowledge while it writes to
  flash. Then flash write speed, not the bus, sets the transfer time. Neither this Pi-to-Pi test
  nor the estimate captures that; a measurement against the real target ECU is the next step.
- Rows marked with **\*** had frames dropped by the Pi's *receiving* software (the Pi can't
  always read 1 Mbit/s fast enough). The frames were on the bus, so the bus rate and the block
  estimate (which uses the frames sent) are still valid; the raw KiB/s shown is what the Pi
  received.

## Bus logs (proof that the traffic is real)

For every measured test, `candump` recorded the bus on pican1 for up to 10 s (folder `candump_logs/20261108_160235`). pican1 sees every frame on the bus, its own and pican2's. Frame counts per CAN ID:

| CAN ID | Meaning |
|---|---|
| 0x100 | raw test frames |
| 0x050 | background load |
| 0x605 | SDO request (client → server) |
| 0x585 | SDO response (server → client) |

| Log file | Duration | Frames | 0x050 | 0x100 | 0x585 | 0x605 | 0x100 sent by test |
|---|---|---|---|---|---|---|---|
| `125k_load00_raw_simplex.log` | 3.2 s | 3378 | 0 | 3378 | 0 | 0 | 3378 |
| `125k_load00_sdo.log` | 4.5 s | 3522 | 0 | 0 | 1761 | 1761 |  |
| `125k_load30_raw_simplex.log` | 5.4 s | 5213 | 1835 | 3378 | 0 | 0 | 3378 |
| `125k_load30_sdo.log` | 8.0 s | 6242 | 2720 | 0 | 1761 | 1761 |  |
| `125k_load60_raw_simplex.log` | 9.1 s | 9529 | 6151 | 3378 | 0 | 0 | 3378 |
| `125k_load60_sdo.log` | 9.9 s | 10231 | 6709 | 0 | 1761 | 1761 |  |
| `250k_load00_raw_simplex.log` | 3.2 s | 6756 | 0 | 6756 | 0 | 0 | 6756 |
| `250k_load00_sdo.log` | 2.7 s | 3522 | 0 | 0 | 1761 | 1761 |  |
| `250k_load30_raw_simplex.log` | 5.3 s | 10361 | 3605 | 6756 | 0 | 0 | 6756 |
| `250k_load30_sdo.log` | 5.6 s | 7315 | 3793 | 0 | 1761 | 1761 |  |
| `250k_load60_raw_simplex.log` | 9.1 s | 18991 | 12235 | 6756 | 0 | 0 | 6756 |
| `250k_load60_sdo.log` | 6.8 s | 12663 | 9141 | 0 | 1761 | 1761 |  |
| `500k_load00_raw_simplex.log` | 3.2 s | 13321 | 0 | 13321 | 0 | 0 | 13513 |
| `500k_load00_sdo.log` | 1.9 s | 3522 | 0 | 0 | 1761 | 1761 |  |
| `500k_load30_raw_simplex.log` | 5.4 s | 20858 | 7345 | 13513 | 0 | 0 | 13513 |
| `500k_load30_sdo.log` | 4.5 s | 9655 | 6133 | 0 | 1761 | 1761 |  |
| `500k_load60_raw_simplex.log` | 9.5 s | 39166 | 25653 | 13513 | 0 | 0 | 13513 |
| `500k_load60_sdo.log` | 5.5 s | 18350 | 14828 | 0 | 1761 | 1761 |  |
| `1000k_load00_raw_simplex.log` | 3.3 s | 24621 | 0 | 24621 | 0 | 0 | 27027 |
| `1000k_load00_sdo.log` | 1.4 s | 3522 | 0 | 0 | 1761 | 1761 |  |
| `1000k_load30_raw_simplex.log` | 5.5 s | 41126 | 14525 | 26601 | 0 | 0 | 27027 |
| `1000k_load30_sdo.log` | 4.0 s | 14400 | 10878 | 0 | 1761 | 1761 |  |
| `1000k_load60_raw_simplex.log` | 9.0 s | 73574 | 46554 | 27020 | 0 | 0 | 27027 |
| `1000k_load60_sdo.log` | 5.2 s | 31814 | 28292 | 0 | 1761 | 1761 |  |

The SDO logs are complete: each 4 KB download is 1 initiate + 586 data segments of 7 bytes, each with one acknowledge, so 3 transfers = 3 × 587 = 1761 frames on 0x605 and 1761 on 0x585. The raw logs are complete up to 250 kbit/s. At 500 kbit/s and 1 Mbit/s on a lightly loaded bus, candump (run at lowest CPU priority so it doesn't slow the test) can't keep up with back-to-back frames and misses a few percent of them; compare the 0x100 column with the frames the test sent. The test's own receiver counts every frame separately.

First frames of `125k_load00_raw_simplex.log`:

```
 (1794150156.532546)  pican1  100   [8]  00 00 00 00 E2 B2 98 A3
 (1794150156.533471)  pican1  100   [8]  00 00 00 01 E2 B2 98 A3
 (1794150156.534440)  pican1  100   [8]  00 00 00 02 E2 B2 98 A3
 (1794150156.535385)  pican1  100   [8]  00 00 00 03 E2 B2 98 A3
```

First frames of `125k_load00_sdo.log`:

```
 (1794150160.454543)  pican1  605   [8]  21 00 20 00 00 10 00 00
 (1794150160.456033)  pican1  585   [8]  60 00 20 00 00 00 00 00
 (1794150160.457639)  pican1  605   [8]  00 1C A6 F8 7B 07 C4 2F
 (1794150160.459009)  pican1  585   [8]  20 00 00 00 00 00 00 00
```

In the raw log, bytes 0–3 are the sequence number counting up. In the SDO log, `21 00 20 00 00 10 00 00` on 0x605 starts a download of 0x1000 = 4096 bytes to object 0x2000, the server confirms with `60` on 0x585, and the data segments follow, each acknowledged on 0x585.

## How to reproduce

```
../.venv/bin/python can_speed_test.py all --bitrates 125000,250000,500000,1000000 --bg-loads 0,30,60 --csv results.csv
python3 make_results.py results.csv -o results.md
```
