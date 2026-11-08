# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A set of standalone Python and shell scripts for measuring CAN bus throughput and frame loss on a Raspberry Pi with SocketCAN interfaces. There is no package, build step, test suite or linter. Each script runs on its own (`python3 <script>.py -h` where argparse is used).

Dependencies: `pip install python-can` (plus `canopen` for the CANopen tool, `can-isotp` for `uds_client.py`). `can-utils` (`cansend`, `candump`) and `iproute2` are used by the shell scripts.

## Hardware assumptions

- Target is **one** Raspberry Pi with two SocketCAN interfaces, **`pican1`** and **`pican2`**, wired to the same bus with termination at both ends. Interface names are hard-coded defaults across nearly all scripts.
- Most scripts configure the interface themselves with `sudo ip link set <iface> down/up type can bitrate <N> restart-ms 100` and raise `txqueuelen` so fast send loops don't overflow the TX queue. They therefore need sudo, and running them **reconfigures live interfaces**.
- Results that matter are only meaningful on real hardware. python-can's `virtual` bus and `vcan` have no bitrate, so their timing figures are meaningless.

## Layout

- `local-can-performance-test.py`: original single-interface send benchmark. Sends N frames with a 2-byte counter in the last two payload bytes and reports msgs/s, inter-message time and estimated bus load. The README holds its reference results (cansend about 350 msg/s; python-can SocketCAN reaches about 96–98 % bus load).
- `test_feedback.py`: pican1 → pican2 loopback throughput and loss test.
- `CAN1-2_loop_CANOpen_SpeedTrasnfer/can_speed_test.py`: the most complete tool. It sweeps bitrates and background bus loads across theoretical, raw simplex/duplex and CANopen SDO scenarios. **Its README has detailed developer notes (code structure, conventions, how to test without hardware). Read it before changing that script.** Key rules from it:
  - Keep **min/MB** (MB = 1,000,000 bytes) as the headline KPI.
  - Every result row must be built with `make_row()` so it appears in both the summary and the CSV.
  - Raw TX/RX workers run in separate `multiprocessing` processes to avoid the GIL.
  - Prefer existing libraries (python-can, canopen, can-utils, CANopenNode) over hand-written protocol code.
  - Do not redesign the tool for two Pis.
- `uds_client.py` / `uds-isotp-raw.py`: UDS ReadDataByIdentifier (`22 F1 90`) over ISO-TP on 0x7E0/0x7E8. The first uses the `isotp` kernel socket. The second does ISO-TP by hand on a raw `AF_CAN` socket and sends flow control after every consecutive frame.
- `playground/`: throwaway experiments, including raw-socket vs `cansend` speed, a TCP↔SocketCAN bridge, a CODESYS TCP sender and echo/listener servers. Sample `candump` logs are in `cantrace_CAN*.log`. Some of these scripts still use the deprecated `bustype=`. Use `interface=` in new code.
