#!/usr/bin/env python3
"""
Build results.md from a can_speed_test.py CSV (and optionally its candump logs).

  python3 make_results.py results_v3.csv -o results.md     # logs: newest candump_logs/ folder

Uses the newest run in the CSV (rows with the latest timestamp). Times for 1 MB and
100 MB are min/MB x size (MB = 1,000,000 bytes).
"""
import argparse
import collections
import csv
import glob
import os
import re

SCENARIO_ORDER = ["Theoretical", "Raw simplex", "Block est.", "SDO segmented", "SDO expedited",
                  "SDO block", "Raw duplex"]


def fmt_time(minutes):
    s = int(round(minutes * 60))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min {s:02d} s" if m else f"{s} s"


def label(r):
    if r["scenario"] == "Block est.":
        return f"Block transfer estimate ({r['direction'].replace('blk ', '').replace(',', ' frames/block,')} turnaround)"
    if r["scenario"].startswith("SDO"):
        return f"{r['scenario']} {r['direction']} (measured)"
    if r["scenario"] == "Raw simplex":
        return "Raw CAN, pican1 → pican2 (measured)"
    if r["scenario"] == "Theoretical":
        return "Theoretical maximum (calculated)"
    return f"{r['scenario']} {r['direction']}"


def sort_key(r):
    sc = next((i for i, s in enumerate(SCENARIO_ORDER) if r["scenario"].startswith(s)), 99)
    blk = re.match(r"blk (\d+)", r["direction"])
    return sc, -int(blk.group(1)) if blk else 0, r["direction"]


def load_rows(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    last = max(r["timestamp"] for r in rows)
    rows = [r for r in rows if r["timestamp"] == last]
    for r in rows:
        r["bitrate"], r["bg_load_pct"], r["size_B"] = int(r["bitrate"]), int(r["bg_load_pct"]), int(r["size_B"])
        r["KiB_s"], r["min_per_MB"] = float(r["KiB_s"]), float(r["min_per_MB"])
        r["ok"] = r["ok"] == "True"
    # per bitrate/load/scenario/direction keep the largest size (steady-state SDO)
    best = {}
    for r in rows:
        k = (r["bitrate"], r["bg_load_pct"], r["scenario"], r["direction"])
        if k not in best or r["size_B"] >= best[k]["size_B"]:
            best[k] = r
    return last, list(best.values())


def log_evidence(log_dir):
    """Per-log frame counts per CAN ID plus a few sample lines."""
    out = []
    for path in sorted(glob.glob(os.path.join(log_dir, "*.log")),
                       key=lambda p: (int(os.path.basename(p).split("k_")[0]), p)):
        ids, first, lines, t0, t1 = collections.Counter(), [], 0, None, None
        with open(path) as f:
            for line in f:
                m = re.match(r"\s*\((\d+\.\d+)\)\s+\S+\s+([0-9A-F]+)\s+\[", line)
                if not m:
                    continue
                ts = float(m.group(1))
                t0 = ts if t0 is None else t0
                t1 = ts
                ids[m.group(2)] += 1
                lines += 1
                if len(first) < 4:
                    first.append(line.rstrip())
        out.append((os.path.basename(path), lines, (t1 - t0) if lines > 1 else 0.0, ids, first))
    return out


ID_MEANING = {"100": "raw test frames", "050": "background load", "605": "SDO request (client → server)",
              "585": "SDO response (server → client)"}

INTRO = """\
# CAN / CANopen transfer speed: results

**Question:** how long does it take to transfer a file (e.g. a firmware image) from a
TCU to an ECU over CAN / CANopen, at different bitrates and with other traffic on the bus?

**Headline KPI:** minutes per MB (MB = 1,000,000 bytes). The 1 MB and 100 MB times below are
simply min/MB × 1 and × 100.

Run: {run} · Tool: `can_speed_test.py` · Raw data: `{csv}`{logs_line}

## Test setup

- One Raspberry Pi 4 with a dual-channel PiCAN board (two MCP2515 CAN controllers on SPI),
  interfaces **pican1** and **pican2**, both wired to the **same CAN bus** with 120 Ω at both ends.
  pican1 plays the **sender (TCU)**, pican2 the **receiver (ECU)**.
- Classic CAN, 11-bit IDs, 8-byte frames. Bitrates: {bitrates}.
- **Background load** simulates other machine traffic already on the bus: a separate
  process sends filler frames (ID 0x050) at {loads} % of the bus capacity. ID 0x050 has a
  *higher* priority than the test traffic, so the transfer always has to wait for it
  (pessimistic, like busy machine traffic).

## What each test does

| Test | Measured or calculated | What it does | What it tells you |
|---|---|---|---|
| **Theoretical maximum** | calculated | The most 8-byte frames that fit on the bus per second (44 + 64 bits per frame + 3 bits gap, no stuff bits), minus the background load. | Absolute ceiling. Nothing can be faster. |
| **Raw CAN** | measured | pican1 sends frames back-to-back to pican2 as fast as possible. All 8 bytes are payload (a sequence number + filler); no protocol, no handshake. pican2 checks the sequence numbers for lost or repeated frames. | Best case for *any* protocol on this bus. About 86–94 % of the theoretical maximum, because real frames contain a few extra "stuff bits". |
| **Block transfer estimate** | calculated from Raw | CANopen *SDO block transfer*, the fast CANopen mode normally used for firmware downloads. Each frame carries 7 data bytes (1 byte is a sequence number); after every block of N frames the receiver sends one acknowledge frame, and the sender waits for it (turnaround time, here {turnaround} ms). Calculated from the measured raw frame time: per block, N × 7 bytes take (N + 1) frame times + turnaround. Shown for N = {blocks} frames per block (127 is the maximum; many devices use smaller blocks). | Realistic planning figure for a CANopen firmware download, as long as the ECU acknowledges quickly. |
| **SDO segmented download** | measured | Standard CANopen SDO download, the simplest mode: the client (pican2) writes a 4 KB object to the server (pican1) and must wait for an acknowledge after **every** 7-byte frame. Each transfer is checked byte for byte. Result is the median of 3 transfers. | Worst-case "plain" CANopen. Shows how much a ping-pong protocol loses when every frame waits for an answer. |

Why block transfer is not measured directly: the CANopen library used here (python-canopen) has no
block transfer on its server side. A real measurement needs a CANopen stack such as CANopenNode
or the real target ECU.
"""

CAVEATS = """\
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
- Rows marked with **\\*** had frames dropped by the Pi's *receiving* software (the Pi can't
  always read 1 Mbit/s fast enough). The frames were on the bus, so the bus rate and the block
  estimate (which uses the frames sent) are still valid; the raw KiB/s shown is what the Pi
  received.
"""


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv")
    p.add_argument("--logs", default="auto",
                   help="candump log folder of the same run (default: newest folder in candump_logs/, '' = none)")
    p.add_argument("-o", "--out", default="results.md")
    p.add_argument("--turnaround", default="2", help="turnaround used in the run (for the text)")
    a = p.parse_args()

    if a.logs == "auto":
        dirs = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(a.csv)), "candump_logs", "*/")))
        a.logs = os.path.relpath(dirs[-1].rstrip("/")) if dirs else ""
    run, rows = load_rows(a.csv)
    bitrates = sorted({r["bitrate"] for r in rows})
    loads = sorted({r["bg_load_pct"] for r in rows})
    blocks = sorted({int(m.group(1)) for r in rows if (m := re.match(r"blk (\d+)", r["direction"]))},
                    reverse=True)
    md = [INTRO.format(run=run, csv=os.path.basename(a.csv),
                       logs_line=f" · Bus logs: `{a.logs}`" if a.logs else "",
                       bitrates=", ".join(f"{b // 1000} kbit/s" for b in bitrates),
                       loads=" / ".join(str(l) for l in loads), turnaround=a.turnaround,
                       blocks=", ".join(map(str, blocks)))]

    def get(br, load, scenario, direction_prefix=""):
        return next((r for r in rows if r["bitrate"] == br and r["bg_load_pct"] == load
                     and r["scenario"] == scenario and r["direction"].startswith(direction_prefix)), None)

    # ---- headline table: 100 MB, idle bus
    md.append("## Summary: time for a 100 MB file\n")
    for load in loads:
        md.append(f"**Background load {load} %**\n")
        md.append("| Bitrate | Raw CAN (best case) | Block transfer, 127 frames/block | "
                  f"Block transfer, {blocks[-1]} frames/block | SDO segmented |")
        md.append("|---|---|---|---|---|")
        for br in bitrates:
            cells = []
            for sc, d in (("Raw simplex", ""), ("Block est.", f"blk {blocks[0]},"),
                          ("Block est.", f"blk {blocks[-1]},"), ("SDO segmented", "download")):
                r = get(br, load, sc, d)
                cells.append(fmt_time(r["min_per_MB"] * 100) + ("" if r["ok"] else " \\*") if r else "–")
            md.append(f"| {br // 1000} kbit/s | " + " | ".join(cells) + " |")
        md.append("")

    # ---- detail tables per bitrate
    md.append("## Detailed results per bitrate\n")
    md.append("KiB/s = payload throughput (1 KiB = 1024 bytes). min/MB = minutes per 1,000,000 bytes.\n")
    for br in bitrates:
        md.append(f"### {br // 1000} kbit/s\n")
        md.append("| Test | Load | KiB/s | min/MB | 1 MB | 100 MB |")
        md.append("|---|---|---|---|---|---|")
        for r in sorted((r for r in rows if r["bitrate"] == br), key=lambda r: (sort_key(r), r["bg_load_pct"])):
            star = "" if r["ok"] else " \\*"
            md.append(f"| {label(r)}{star} | {r['bg_load_pct']} % | {r['KiB_s']:.2f} | {r['min_per_MB']:.2f} | "
                      f"{fmt_time(r['min_per_MB'])} | {fmt_time(r['min_per_MB'] * 100)} |")
        md.append("")

    md.append(CAVEATS)

    # ---- bus log evidence
    if a.logs and os.path.isdir(a.logs):
        md.append("## Bus logs (proof that the traffic is real)\n")
        md.append(f"For every measured test, `candump` recorded the bus on pican1 for up to 10 s "
                  f"(folder `{a.logs}`). pican1 sees every frame on the bus, its own and pican2's. "
                  "Frame counts per CAN ID:\n")
        md.append("| CAN ID | Meaning |\n|---|---|")
        for k, v in ID_MEANING.items():
            md.append(f"| 0x{k} | {v} |")
        md.append("")
        ev = log_evidence(a.logs)
        all_ids = sorted({i for e in ev for i in e[3]})
        # raw frames the test actually sent = received by the test + lost (from the CSV note)
        sent = {}
        for r in rows:
            if r["scenario"] == "Raw simplex":
                m = re.search(r"lost (-?\d+)", r["note"])
                sent[f"{r['bitrate'] // 1000}k_load{r['bg_load_pct']:02d}_raw_simplex.log"] = \
                    r["size_B"] // 8 + (int(m.group(1)) if m else 0)
        md.append("| Log file | Duration | Frames | " + " | ".join(f"0x{i}" for i in all_ids)
                  + " | 0x100 sent by test |")
        md.append("|---|---|---|" + "---|" * len(all_ids) + "---|")
        for name, n, dur, ids, _ in ev:
            md.append(f"| `{name}` | {dur:.1f} s | {n} | " + " | ".join(str(ids.get(i, 0)) for i in all_ids)
                      + f" | {sent.get(name, '')} |")
        md.append("")
        md.append("The SDO logs are complete: each 4 KB download is 1 initiate + 586 data segments of 7 bytes, "
                  "each with one acknowledge, so 3 transfers = 3 × 587 = 1761 frames on 0x605 and 1761 on "
                  "0x585. The raw logs are complete up to 250 kbit/s. At 500 kbit/s and 1 Mbit/s on a "
                  "lightly loaded bus, candump (run at lowest CPU priority so it doesn't slow the test) "
                  "can't keep up with back-to-back frames and misses a few percent of them; compare the "
                  "0x100 column with the frames the test sent. The test's own receiver counts every "
                  "frame separately.\n")
        samples = [e for e in ev if e[0].endswith("load00_raw_simplex.log")][:1] + \
                  [e for e in ev if e[0].endswith("load00_sdo.log")][:1]
        for name, _, _, _, first in samples:
            md.append(f"First frames of `{name}`:\n\n```\n" + "\n".join(first) + "\n```\n")
        md.append("In the raw log, bytes 0–3 are the sequence number counting up. In the SDO log, "
                  "`21 00 20 00 00 10 00 00` on 0x605 starts a download of 0x1000 = 4096 bytes to "
                  "object 0x2000, the server confirms with `60` on 0x585, and the data segments follow, "
                  "each acknowledged on 0x585.\n")

    md.append("## How to reproduce\n")
    md.append("```\n../.venv/bin/python can_speed_test.py all --bitrates "
              + ",".join(map(str, bitrates)) + " --bg-loads " + ",".join(map(str, loads))
              + " --csv results.csv\npython3 make_results.py results.csv -o results.md\n```\n")
    with open(a.out, "w") as f:
        f.write("\n".join(md))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
