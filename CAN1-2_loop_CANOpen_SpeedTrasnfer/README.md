# CAN / CANopen Transfer Speed Test

Estimate **how long it takes to transfer a file of X MB over CAN / CANopen** under different conditions (bitrate, bus load, protocol), using one Raspberry Pi with two CAN interfaces.

**Main KPI: minutes per MB (min/MB)**, where MB = 1,000,000 bytes. The script also converts that into an estimated transfer time for a file size you choose (`--file-mb`).

---

## Hardware setup

- One Raspberry Pi with two SocketCAN interfaces named **`pican1`** and **`pican2`** (e.g. a dual-channel PiCAN board).
- Both interfaces wired to the **same CAN bus**, with **120 Ω termination at both ends**.
- Default roles:
  - `pican1` (`--a`): raw sender, CANopen SDO server.
  - `pican2` (`--b`): raw receiver, CANopen SDO client, background load generator.

## Installation

```bash
pip install python-can canopen
```

`iproute2` (`ip` command) is needed and is standard on Raspberry Pi OS. Configuring the interfaces needs root. If the script is not run as root it prefixes the `ip` commands with `sudo`, so you'll get a password prompt unless sudo is passwordless.

## Usage

```bash
# Only configure both interfaces (bitrate, restart-ms, txqueuelen, up)
./can_speed_test.py setup --bitrates 500000

# Everything at 500 kbit/s on an idle bus, estimate for a 5 MB file
./can_speed_test.py all --file-mb 5

# Full sweep: 4 bitrates x 3 background loads, results to CSV
./can_speed_test.py all --bitrates 125000,250000,500000,1000000 \
                        --bg-loads 0,30,60 --file-mb 10 --csv results.csv

# Only raw CAN, including duplex
./can_speed_test.py raw --bitrates 250000 --duplex

# Only SDO, larger transfers
./can_speed_test.py sdo --bitrates 250000 --sizes 4096,65536 --repeat 3

# Interfaces already configured by hand: do not touch them
./can_speed_test.py all --no-setup --bitrates 500000
```

Run `./can_speed_test.py -h` for all options.

### Main options

| Option | Default | Meaning |
|---|---|---|
| `test` | – | `setup`, `raw`, `sdo` or `all` |
| `--a` / `--b` | `pican1` / `pican2` | Interface names |
| `--bitrates` | `500000` | Comma-separated list; the script reconfigures the interfaces for each |
| `--bg-loads` | `0` | Background bus load in %, e.g. `0,30,60` |
| `--bg-id` | `0x050` | CAN ID of background frames (lower ID = higher priority than SDO) |
| `--file-mb` | `1` | File size used for the time estimate |
| `--csv` | – | Append all result rows to a CSV file |
| `--no-setup` | off | Do not run any `ip link` commands |
| `--restart-ms`, `--sample-point`, `--txqueuelen` | `100`, –, `1000` | Interface settings |
| `--raw-seconds` / `--frames` | `5` / – | Duration (or fixed frame count) of each raw test |
| `--sizes` | `4,256,4096` | SDO transfer sizes in bytes |
| `--directions` | `upload,download` | SDO directions |
| `--sdo-mode` | `auto` | `auto`, `segmented` or `block` (block needs an external server) |
| `--node`, `--index`, `--sub` | `5`, `0x2000`, `0` | SDO target object |
| `--block-sizes` | `127,32` | Block sizes (frames) for the calculated block estimate |
| `--turnaround-ms` | `2` | Receiver ack delay per block for the estimate. Use a larger value to model an ECU writing flash |
| `--no-local-server` | off | Test against an external CANopen node instead of the built-in one |

---

## Scenarios measured

For every bitrate × background load combination:

| Scenario | What it represents |
|---|---|
| **Theoretical** | Calculated maximum payload with 8-byte standard frames, reduced by the background load. No measurement. |
| **Raw simplex** | `pican1 → pican2` back-to-back frames, no handshake. Best case for any protocol. |
| **Block est.** | Calculated, not measured. SDO block transfer derived from the measured raw simplex frame time: per block of B frames, B×7 data bytes take (B+1) frame times (segments + ack) plus `--turnaround-ms`. With 0 ms turnaround this is raw × 7/8 × B/(B+1). Because it uses the measured frame time, stuffing and background load are included. |
| **Raw duplex** | Optional, only with `--duplex`. Both directions at the same time. The lower ID wins arbitration, so the streams run mostly one after the other; both directions are timed over the shared window. |
| **SDO upload / download** | Standard CANopen SDO (expedited ≤ 4 B, segmented above). Every transfer is verified byte for byte. |
| **Background load** | A separate process sends filler frames from `pican2` at a target % of bus capacity, with an ID that wins arbitration over SDO. This simulates machine traffic already on the bus. The achieved load is printed. |

## Output

1. Per-test lines while running: KiB/s, min/MB, OK/ERR, plus notes (lost frames, out-of-order frames, TX queue retries, SDO errors).
2. Interface state after each bitrate (error state, bus-off restarts, error counters) read from `ip -details -statistics -json`.
3. A **summary table** per bitrate / load / scenario / direction with KiB/s, min/MB and the estimated time for `--file-mb`. For SDO the summary uses the largest tested size, since that represents steady-state throughput.
4. Optional CSV with columns: `timestamp, file_MB, bitrate, bg_load_pct, scenario, direction, size_B, seconds, KiB_s, min_per_MB, est_file_min, ok, note`.

## Interpreting the results

- **Theoretical:** true upper bound (no stuff bits): at 250 kbit/s about **0.93 min/MB**, at 500 kbit/s about **0.46 min/MB**. Halving the bitrate doubles the time. Measured raw simplex reaches ~93 % of it (stuff bits).
- **Raw** is the upper bound for any real protocol. It counts all 8 bytes per frame as payload; a real custom protocol would also need sequencing and flow control.
- **CANopen block transfer** (7 data bytes per frame, one ack per block of up to 127 frames) typically reaches **~80–87 % of raw**. With small blocks or a slow receiver it is ~60–75 %. Planning figure: **block ≈ raw × 0.85**. These are estimates from protocol overhead, not measurements.
- **Segmented SDO** waits for an ack after every 7 bytes, so it reaches roughly **35–45 % of raw**. It also suffers more from background load, because every round trip has to win arbitration again.
- **SDO results include the Pi's own latency** (Linux + Python). A real ECU may answer faster or slower.
- **Firmware updates on real devices:** the receiver often delays acks while writing flash, so flash write speed can dominate. Measure against the real target ECU for final numbers.

---

## Limitations and known issues

- **No block transfer with the built-in server.** python-canopen's `SdoServer` (used by `LocalNode`) aborts block upload and download. To test block mode, run an external server on `pican1`, e.g. [CANopenLinux](https://github.com/CANopenNode/CANopenLinux) (CANopenNode on SocketCAN) or a real ECU, then use `--no-local-server --sdo-mode block`.
- **No CAN FD.** Only classic CAN, 8-byte frames, standard 11-bit IDs.
- **Theoretical frame size** is 44 + 8·DLC bits + 3 bits interframe space, without stuff bits, so it is an upper bound. Background load % is relative to the same frame rate.
- **Background load pacing** sends small bursts every 5 ms, which is an approximation of evenly spread traffic.
- **Test status:** run on the real hardware (pican1 + pican2) at 250 kbit/s with 0/30/60 % background load, using `--no-setup`. Other bitrates need the built-in `ip link` setup (sudo).

## Roadmap / ideas

- [x] Calculated "block estimate" row: raw × 7/8 × blksize/(blksize+1), minus a configurable turnaround time.
- [ ] Measured block transfer against CANopenLinux running on `pican1`.
- [ ] Measurement against a real target ECU.
- [ ] CAN FD support (if the hardware supports it).
- [ ] Plot the CSV (min/MB vs bitrate per scenario).
- [ ] Optional extended (29-bit) IDs for background load, to mimic J1939 traffic.

---

## Notes for developers / Claude Code

### Project context
- Goal: estimate transfer time of an X MB file over CAN/CANopen. **Keep min/MB as the headline KPI** in any new output.
- Target machine: **one** Raspberry Pi with two interfaces, `pican1` and `pican2`. Do not redesign for two Pis.
- Preference: use existing libraries (python-can, canopen, can-utils, CANopenNode) before writing protocol code by hand.

### Code structure (`can_speed_test.py`, single file)

| Part | Functions / classes |
|---|---|
| Helpers | `theoretical_fps()`, `fmt_minutes()`, `make_row()` (every result is a dict built here, which keeps the summary and CSV consistent) |
| Interface setup | `_run()` (adds `sudo` if not root), `iface_info()` (parses `ip -json`), `setup_interfaces()` |
| Background load | `_bg_worker()` (process), `BackgroundLoad` context manager |
| Block estimate | `block_estimate_rows()` (calculated rows from the raw simplex rows) |
| Raw CAN | `_rx_worker()`, `_tx_worker()` (each in its own `multiprocessing.Process`, to avoid the GIL), `run_raw()` |
| CANopen SDO | `make_domain_od()` (DOMAIN object 0x2000:0), `run_sdo()` (LocalNode server on `--a` and client on `--b`, in one process, each on its own `canopen.Network`) |
| Output | `print_row()`, `print_summary()`, CSV writing in `main()` |
| CLI | `main()`: loop over bitrates → setup → loop over background loads → scenarios |

### Conventions
- Raw frames: standard ID (`--can-id`, duplex uses `can-id + 1`), payload = 4-byte big-endian sequence number + 4 random bytes. The receiver filters by ID in the kernel and detects lost or out-of-order frames from the sequence number.
- `MB = 1_000_000` bytes. KiB/s uses 1024.
- New scenarios should return a list of `make_row()` dicts, so they show up in the summary and CSV automatically.
- Setup is skipped automatically when `--interface` is not `socketcan`.

### Testing without CAN hardware
python-can's `virtual` interface works in-process only; it does not cross processes. Put both sides on the same channel name:

```python
import importlib.util, argparse
spec = importlib.util.spec_from_file_location("t", "can_speed_test.py")
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)
a = argparse.Namespace(interface="virtual", a="vbus", b="vbus", node=5, index=0x2000, sub=0,
                       sizes=[4, 4096], directions=["upload", "download"], sdo_mode="auto",
                       repeat=2, timeout=1.0, no_local_server=False, file_mb=10)
t.print_summary(t.run_sdo(a, 500000, 0), 10)
```

Raw and background workers can be tested by running them in `threading.Thread` with `threading.Event` / `queue.Queue` in place of the multiprocessing versions. Speed figures on the virtual bus are meaningless, since it has no bitrate.

On Linux with root you can also use kernel `vcan` interfaces (`ip link add dev vcan0 type vcan`). Note that two separate vcan interfaces are not connected to each other, and vcan ignores bitrate settings.
