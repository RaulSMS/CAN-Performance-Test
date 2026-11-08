#!/usr/bin/env python3
"""
CAN / CANopen file-transfer time estimator for ONE Raspberry Pi with two CAN
interfaces (default pican1 + pican2, on the same bus, 120 ohm at both ends).

Goal: estimate how long a file of X MB takes over CAN / CANopen in different
scenarios. Main KPI: minutes per MB (MB = 1,000,000 bytes).

The script configures the interfaces itself (ip link, via sudo if not root),
sweeps bitrates and background bus loads, and for each combination measures:
  Theoretical   max payload with 8-byte standard frames (calculated, no test)
  Raw simplex   pican1 -> pican2 back-to-back frames (best case custom protocol)
  Block est.    SDO block transfer calculated from raw simplex: 7 B/frame, 1 ack per
                block, configurable turnaround (--block-sizes, --turnaround-ms)
  Raw duplex    optional (--duplex): both directions at once, timed over the shared window
  SDO upload    CANopen segmented/expedited, server on pican1, client on pican2
  SDO download  same, other direction (each transfer verified byte for byte)
Background load: a separate process sends filler frames from pican2 at a set
percentage of bus capacity with a HIGHER priority ID than SDO (pessimistic,
like machine traffic on a real bus).

Requirements:  pip install python-can canopen   (and iproute2, standard on Pi OS)

Examples:
  ./can_speed_test.py setup --bitrates 500000              # only configure interfaces
  ./can_speed_test.py all --file-mb 5                      # 500 kbit/s, idle bus
  ./can_speed_test.py all --bitrates 125000,250000,500000,1000000 --bg-loads 0,30,60 \
                          --file-mb 10 --csv results.csv  # full sweep
  ./can_speed_test.py sdo --bitrates 250000 --sizes 4096,65536 --repeat 3

Block transfer (fastest CANopen mode) is not supported by python-canopen's
local server. Run an external server on --a (e.g. CANopenLinux or a real ECU):
  ./can_speed_test.py sdo --no-local-server --node <id> --index <idx> --sdo-mode block
"""
import argparse
import csv
import json
import multiprocessing as mp
import os
import shutil
import socket
import statistics
import struct
import subprocess
import time

import can

try:
    import canopen
except ImportError:
    canopen = None

START_TIMEOUT = 10.0
MB = 1_000_000
VALID_BITRATES = {10000, 20000, 50000, 100000, 125000, 250000, 500000, 800000, 1000000}


# ================================================================ helpers
def theoretical_fps(bitrate, dlc=8):
    """Upper bound of standard frames/s: 44+8*dlc bits per frame + 3 bit IFS, no stuff bits.
    Real frames carry a few stuff bits (random data ~5-10), so measured raw is ~90-95 % of this."""
    return bitrate / (44 + 8 * dlc + 3)


def fmt_minutes(minutes):
    s = int(round(minutes * 60))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def make_row(args, bitrate, load, scenario, direction, nbytes, seconds, ok=True, note=""):
    bps = nbytes / max(seconds, 1e-9)
    min_per_mb = MB / max(bps, 1e-9) / 60
    return {"bitrate": bitrate, "bg_load_pct": load, "scenario": scenario, "direction": direction,
            "size_B": nbytes, "seconds": round(seconds, 4), "KiB_s": round(bps / 1024, 2),
            "min_per_MB": round(min_per_mb, 3), "est_file_min": round(min_per_mb * args.file_mb, 2),
            "ok": ok, "note": note}


# ================================================================ interface setup
def _run(cmd, check=True):
    if os.geteuid() != 0 and shutil.which("sudo"):
        cmd = ["sudo"] + cmd
    print("  $ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def iface_info(name):
    try:
        out = subprocess.run(["ip", "-details", "-statistics", "-json", "link", "show", name],
                             check=True, capture_output=True, text=True).stdout
        d = json.loads(out)[0]
        info = d.get("linkinfo", {}).get("info_data", {})
        return {"operstate": d.get("operstate"), "state": info.get("state"),
                "bitrate": info.get("bittiming", {}).get("bitrate"),
                "restarts": info.get("restart_cnt", d.get("linkinfo", {}).get("info_xstats", {}).get("restarts")),
                "berr": info.get("berr_counter")}
    except Exception as e:
        return {"error": str(e)}


def setup_interfaces(args, bitrate):
    if bitrate not in VALID_BITRATES:
        print(f"  warning: {bitrate} is not a standard CAN bitrate")
    print(f"\n--- Configuring {args.a}, {args.b} @ {bitrate} bit/s ---")
    for name in (args.a, args.b):
        _run(["ip", "link", "set", name, "down"])
        cmd = ["ip", "link", "set", name, "type", "can", "bitrate", str(bitrate),
               "restart-ms", str(args.restart_ms)]
        if args.sample_point:
            cmd += ["sample-point", str(args.sample_point)]
        _run(cmd)
        _run(["ip", "link", "set", name, "txqueuelen", str(args.txqueuelen)])
        _run(["ip", "link", "set", name, "up"])
    time.sleep(0.5)
    for name in (args.a, args.b):
        info = iface_info(name)
        print(f"  {name}: {info}")
        if info.get("bitrate") not in (None, bitrate):
            raise SystemExit(f"{name} reports bitrate {info.get('bitrate')}, expected {bitrate}")


# ================================================================ background load
def _bg_worker(interface, channel, can_id, fps, stop, out):
    bus = can.Bus(interface=interface, channel=channel)
    period, credit, sent = 0.001, 0.0, 0
    # random payload: all-zero data would force maximum bit stuffing and distort the load %
    msg = can.Message(arbitration_id=can_id, is_extended_id=False, data=os.urandom(8))
    t0 = nxt = time.perf_counter()
    while not stop.is_set():
        credit += fps * period
        n = int(credit)
        credit -= n
        for _ in range(n):
            try:
                bus.send(msg, timeout=0)
                sent += 1
            except can.CanError:
                break
        nxt += period
        time.sleep(max(0.0, nxt - time.perf_counter()))
    out.put(sent / (time.perf_counter() - t0))
    bus.shutdown()


class BackgroundLoad:
    def __init__(self, args, bitrate, pct):
        self.pct, self.fps = pct, theoretical_fps(bitrate) * pct / 100
        self.bitrate, self.args = bitrate, args
        self.actual_pct = 0.0

    def __enter__(self):
        if self.pct > 0:
            self.stop, self.out = mp.Event(), mp.Queue()
            self.proc = mp.Process(target=_bg_worker, args=(self.args.interface, self.args.b,
                                   self.args.bg_id, self.fps, self.stop, self.out))
            self.proc.start()
            time.sleep(0.5)
        return self

    def __exit__(self, *exc):
        if self.pct > 0:
            self.stop.set()
            self.actual_pct = 100 * self.out.get(timeout=5) / theoretical_fps(self.bitrate)
            self.proc.join()
            print(f"  background load: target {self.pct} %, achieved ~{self.actual_pct:.1f} %")


# ================================================================ bus log (candump)
class CandumpLog:
    """Record bus traffic with candump while a scenario runs (at most --candump-seconds).

    Logs on --a only: thanks to SocketCAN local loopback, a socket on pican1 sees every frame
    on the bus, both pican1's own and the ones from pican2. Proof that the test traffic is real.
    """

    def __init__(self, args, bitrate, load, scenario):
        self.args, self.proc = args, None
        if args.candump_dir:
            name = f"{bitrate // 1000}k_load{load:02d}_{scenario.lower().replace(' ', '_')}.log"
            self.path = os.path.join(args.candump_dir, name)

    def __enter__(self):
        if self.args.candump_dir:
            self.f = open(self.path, "w")
            self.proc = subprocess.Popen(["nice", "-n", "19", "timeout", "-s", "INT", str(self.args.candump_seconds),
                                          "candump", "-ta", self.args.a],
                                         stdout=self.f, stderr=subprocess.STDOUT)
            time.sleep(0.2)  # let candump bind before traffic starts
        return self

    def __exit__(self, *exc):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.send_signal(2)  # SIGINT -> candump flushes and exits
            self.proc.wait(timeout=5)
            self.f.close()


# ================================================================ raw CAN
SO_TIMESTAMP = getattr(socket, "SO_TIMESTAMP", 29)  # 29 on Linux; not exported by Python 3.11
TIMEVAL_SIZE = struct.calcsize("@ll")


class _SeqCounter:
    """Counts frames by the 4-byte big-endian sequence number at the start of the payload."""

    def __init__(self):
        self.count = self.lost = self.dup = self.ooo = 0
        self.expected = self.first = self.last = None

    def add(self, ts, seq):
        self.first = ts if self.first is None else self.first
        self.last = ts
        if self.expected is not None:
            if seq == self.expected - 1:  # CAN retransmission after an error in the last EOF bit
                self.dup += 1
                return
            if seq > self.expected:
                self.lost += seq - self.expected
            elif seq < self.expected:
                self.ooo += 1
        self.expected = seq + 1
        self.count += 1


def _rx_worker(interface, channel, can_id, idle, ready, out):
    c = _SeqCounter()
    if interface == "socketcan":
        # Plain AF_CAN socket: python-can's recv() is too slow on a Pi at 1 Mbit/s, so the
        # kernel socket buffer overflows and frames are dropped although they were on the bus.
        s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, struct.pack("=II", can_id, 0x7FF))
        s.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMP, 1)
        s.bind((channel,))
        ready.set()
        s.settimeout(START_TIMEOUT)
        while True:
            try:
                data, anc, _, _ = s.recvmsg(16, 64)
            except socket.timeout:
                break
            sec, usec = struct.unpack("@ll", anc[0][2][:TIMEVAL_SIZE])  # struct timeval
            c.add(sec + usec / 1e6, struct.unpack(">I", data[8:12])[0])
            if c.count == 1:
                s.settimeout(idle)
        s.close()
    else:
        bus = can.Bus(interface=interface, channel=channel,
                      can_filters=[{"can_id": can_id, "can_mask": 0x7FF, "extended": False}])
        ready.set()
        deadline = time.monotonic() + START_TIMEOUT
        while True:
            msg = bus.recv(timeout=idle if c.count else max(deadline - time.monotonic(), 0.0))
            if msg is None:
                break
            c.add(msg.timestamp, struct.unpack(">I", bytes(msg.data[:4]))[0])
        bus.shutdown()
    out.put({"role": "rx", "can_id": can_id, "frames": c.count, "dup": c.dup, "ooo": c.ooo,
             "first": c.first, "last": c.last})


def _tx_worker(interface, channel, can_id, frames, start, out):
    bus = can.Bus(interface=interface, channel=channel)
    tail, sent, retries = os.urandom(4), 0, 0
    start.wait()
    while sent < frames:
        try:
            bus.send(can.Message(arbitration_id=can_id, is_extended_id=False,
                                 data=struct.pack(">I", sent) + tail), timeout=0.1)
            sent += 1
        except can.CanError:  # TX queue full -> back off
            retries += 1
            time.sleep(0.0005)
    bus.shutdown()
    out.put({"role": "tx", "can_id": can_id, "frames": sent, "retries": retries})


def run_raw(args, bitrate, load, duplex):
    frames = args.frames or int(theoretical_fps(bitrate) * args.raw_seconds)
    links = [(args.a, args.b, args.can_id)] + ([(args.b, args.a, args.can_id + 1)] if duplex else [])
    out, start, procs, readies = mp.Queue(), mp.Event(), [], []
    for tx_ch, rx_ch, cid in links:
        r = mp.Event()
        readies.append(r)
        procs.append(mp.Process(target=_rx_worker, args=(args.interface, rx_ch, cid, args.idle, r, out)))
    for tx_ch, rx_ch, cid in links:
        procs.append(mp.Process(target=_tx_worker, args=(args.interface, tx_ch, cid, frames, start, out)))
    for p in procs:
        p.start()
    for r in readies:
        r.wait(5)
    start.set()
    res = [out.get(timeout=START_TIMEOUT + args.raw_seconds * 10 + 60) for _ in procs]
    for p in procs:
        p.join()
    scenario = "Raw duplex" if duplex else "Raw simplex"
    # Duplex: lower ID always wins arbitration, so the two streams mostly run one after the
    # other. Time every direction over the shared window (first frame of any stream to last
    # frame of any stream), i.e. how long both transfers take when they share the bus.
    rxs = [r for r in res if r["role"] == "rx" and r["frames"] > 1]
    window = (max(r["last"] for r in rxs) - min(r["first"] for r in rxs)) if rxs else 0.0
    rows = []
    for tx_ch, rx_ch, cid in links:
        tx = next(r for r in res if r["role"] == "tx" and r["can_id"] == cid)
        rx = next(r for r in res if r["role"] == "rx" and r["can_id"] == cid)
        lost = tx["frames"] - rx["frames"]
        seconds = window if duplex else ((rx["last"] - rx["first"]) if rx["frames"] > 1 else 0.0)
        note = f"lost {lost}, dup {rx['dup']}, ooo {rx['ooo']}, txretry {tx['retries']}"
        row = make_row(args, bitrate, load, scenario, f"{tx_ch}->{rx_ch}", rx["frames"] * 8, seconds,
                       ok=(lost == 0 and rx["frames"] > 1), note=note)
        print_row(row)
        rows.append(row)
        if not duplex and rx["frames"] > 1:
            # Every frame the sender got out was acked on the bus, even if the Pi receiver app
            # dropped it afterwards. So the bus frame time is window / frames sent.
            rows += block_estimate_rows(args, row, seconds / tx["frames"], lost)
    return rows


# ================================================================ block transfer estimate
def block_estimate_rows(args, raw, t_frame, rx_lost=0):
    """Calculated SDO block transfer throughput from a measured raw simplex run.

    Per block of B frames: B segment frames (7 data bytes each, 1 byte seq number) + 1 ack
    frame, plus the receiver's turnaround before it sends the ack. t_frame is the measured
    bus time per frame, so bit stuffing and background load are already included.
    With turnaround 0 this is raw * 7/8 * B/(B+1). Start/end/CRC frames are ignored.
    """
    rows = []
    bus_bps = 8 / t_frame
    for blk in args.block_sizes:
        if not 1 <= blk <= 127:
            raise SystemExit(f"--block-sizes: {blk} outside 1..127")
        t_block = (blk + 1) * t_frame + args.turnaround_ms / 1000
        note = f"calculated, {100 * 7 * blk / t_block / bus_bps:.0f} % of raw bus rate {bus_bps / 1024:.2f} KiB/s"
        if rx_lost:
            note += f" (Pi rx dropped {rx_lost} frames, bus rate from frames sent)"
        row = make_row(args, raw["bitrate"], raw["bg_load_pct"], "Block est.",
                       f"blk {blk}, {args.turnaround_ms:g} ms", 7 * blk, t_block, note=note)
        print_row(row)
        rows.append(row)
    return rows


# ================================================================ CANopen SDO
def make_domain_od(index, sub):
    od = canopen.ObjectDictionary()
    VarCls = getattr(canopen.objectdictionary, "ODVariable", None) or canopen.objectdictionary.Variable
    var = VarCls("TestDomain", index, sub)
    var.data_type = canopen.objectdictionary.DOMAIN
    var.access_type = "rw"
    od.add_object(var)
    return od


def run_sdo(args, bitrate, load):
    if canopen is None:
        raise SystemExit("canopen not installed: pip install canopen")
    srv_net = server = None
    if not args.no_local_server:
        srv_net = canopen.Network()
        # kernel filter: only SDO requests reach Python. Otherwise every background frame is
        # handled in Python too, and at 1 Mbit/s + high load the SDO replies arrive too late.
        srv_net.connect(interface=args.interface, channel=args.a,
                        can_filters=[{"can_id": 0x600 + args.node, "can_mask": 0x7FF, "extended": False}])
        server = canopen.LocalNode(args.node, make_domain_od(args.index, args.sub))
        srv_net.add_node(server)
    cli_net = canopen.Network()
    cli_net.connect(interface=args.interface, channel=args.b,
                    can_filters=[{"can_id": 0x580 + args.node, "can_mask": 0x7FF, "extended": False}])
    client = cli_net.add_node(args.node, None)
    client.sdo.RESPONSE_TIMEOUT = args.timeout
    rows = []
    try:
        for direction in args.directions:
            for size in args.sizes:
                times, ok, err = [], True, ""
                for _ in range(args.repeat):
                    data = os.urandom(size)
                    try:
                        if direction == "upload" and server:
                            server.set_data(args.index, args.sub, data)
                        t0 = time.perf_counter()
                        if direction == "download":
                            if args.sdo_mode == "block":
                                with client.sdo.open(args.index, args.sub, "wb", size=size, block_transfer=True) as f:
                                    f.write(data)
                            else:
                                client.sdo.download(args.index, args.sub, data,
                                                    force_segment=(args.sdo_mode == "segmented"))
                            times.append(time.perf_counter() - t0)
                            if server:
                                ok &= bytes(server.get_data(args.index, args.sub)) == data
                        else:
                            if args.sdo_mode == "block":
                                with client.sdo.open(args.index, args.sub, "rb", block_transfer=True) as f:
                                    got = f.read()
                            else:
                                got = client.sdo.upload(args.index, args.sub)
                            times.append(time.perf_counter() - t0)
                            if server:
                                ok &= bytes(got) == data
                    except Exception as e:  # SDO timeout/abort, e.g. under heavy load
                        ok, err = False, f"{type(e).__name__}: {e}"
                if not times:
                    print(f"  SDO {direction} {size} B failed: {err}")
                    continue
                avg = statistics.median(times)  # median: one slow run (Pi scheduling) must not skew it
                note = f"median of {len(times)}/{args.repeat} runs, {size / max(times) / 1024:.2f}-" \
                       f"{size / min(times) / 1024:.2f} KiB/s" + (f", {err}" if err else "") + \
                       ("" if server else ", external server (not verified)")
                mode = args.sdo_mode if args.sdo_mode != "auto" else ("expedited" if size <= 4 else "segmented")
                row = make_row(args, bitrate, load, f"SDO {mode}", direction, size, avg, ok, note)
                print_row(row)
                rows.append(row)
    finally:
        cli_net.disconnect()
        if srv_net:
            srv_net.disconnect()
    return rows


# ================================================================ output
def print_row(r):
    print(f"  {r['scenario']:13s} {r['direction']:16s} {r['size_B']:8d} B  {r['KiB_s']:8.2f} KiB/s  "
          f"{r['min_per_MB']:8.2f} min/MB  {'OK ' if r['ok'] else 'ERR'}  {r['note']}")


def print_summary(rows, file_mb):
    # steady state: per bitrate/load/scenario/direction keep the largest transfer size
    best = {}
    for r in rows:
        k = (r["bitrate"], r["bg_load_pct"], r["scenario"], r["direction"])
        if k not in best or r["size_B"] >= best[k]["size_B"]:
            best[k] = r
    print(f"\n{'=' * 96}\nSUMMARY  (MB = 10^6 bytes; SDO uses the largest tested size)\n{'=' * 96}")
    print(f"{'bitrate':>8} {'load':>5}  {'scenario':13} {'direction':16} {'KiB/s':>9} {'min/MB':>9} "
          f"{'time for ' + str(file_mb) + ' MB':>16}  ok")
    for k in sorted(best, key=lambda k: (k[0], k[1], k[2], k[3])):
        r = best[k]
        print(f"{r['bitrate']:>8} {str(r['bg_load_pct']) + '%':>5}  {r['scenario']:13} {r['direction']:16} "
              f"{r['KiB_s']:>9.2f} {r['min_per_MB']:>9.2f} {fmt_minutes(r['est_file_min']):>16}  "
              f"{'yes' if r['ok'] else 'NO'}")


# ================================================================ main
def int_list(s):
    return [int(x) for x in s.split(",")]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("test", choices=["setup", "raw", "sdo", "all"])
    p.add_argument("--a", default="pican1", help="raw sender / SDO server")
    p.add_argument("--b", default="pican2", help="raw receiver / SDO client / background load")
    p.add_argument("--interface", default="socketcan")
    p.add_argument("--bitrates", type=int_list, default=[500000], help="e.g. 125000,250000,500000,1000000")
    p.add_argument("--bg-loads", type=int_list, default=[0], help="background bus load %%, e.g. 0,30,60")
    p.add_argument("--bg-id", type=lambda x: int(x, 0), default=0x050, help="background frame ID (low = high priority)")
    p.add_argument("--file-mb", type=float, default=1.0, help="file size to estimate transfer time for")
    p.add_argument("--csv", help="append all results to this CSV")
    g = p.add_argument_group("interface setup")
    g.add_argument("--no-setup", action="store_true", help="do not touch the interfaces (already configured)")
    g.add_argument("--restart-ms", type=int, default=100, help="auto-restart after bus-off")
    g.add_argument("--sample-point", type=float, help="e.g. 0.875")
    g.add_argument("--txqueuelen", type=int, default=1000)
    g = p.add_argument_group("raw")
    g.add_argument("--raw-seconds", type=float, default=3.0, help="approx. duration of each raw test")
    g.add_argument("--frames", type=int, help="fixed frame count instead of --raw-seconds")
    g.add_argument("--can-id", type=lambda x: int(x, 0), default=0x100)
    g.add_argument("--idle", type=float, default=0.5, help="raw rx: stop after this many s without frames")
    g.add_argument("--duplex", action="store_true", help="raw test: also run duplex")
    g = p.add_argument_group("block transfer estimate (calculated from measured raw simplex)")
    g.add_argument("--block-sizes", type=int_list, default=[127, 32, 16],
                   help="SDO block sizes in frames (1..127), e.g. 127,32,16")
    g.add_argument("--turnaround-ms", type=float, default=2.0,
                   help="receiver ack delay per block in ms (Pi ~1-2, ECU writing flash: much more)")
    g = p.add_argument_group("sdo")
    g.add_argument("--node", type=int, default=5)
    g.add_argument("--index", type=lambda x: int(x, 0), default=0x2000)
    g.add_argument("--sub", type=int, default=0)
    g.add_argument("--sizes", type=int_list, default=[4096],
                   help="SDO transfer sizes in bytes; throughput is steady from ~4 KB on")
    g.add_argument("--directions", type=lambda s: s.split(","), default=["download"],
                   help="download = client writes to server (TCU -> ECU, like a firmware download); upload,download for both")
    g.add_argument("--sdo-mode", choices=["auto", "segmented", "block"], default="auto")
    g.add_argument("--repeat", type=int, default=3)
    g.add_argument("--timeout", type=float, default=1.0)
    g.add_argument("--no-local-server", action="store_true")
    g = p.add_argument_group("bus log")
    g.add_argument("--candump-dir", default="candump_logs",
                   help="write a candump log per measured scenario to <dir>/<run time>/ ('' = off)")
    g.add_argument("--candump-seconds", type=float, default=10.0, help="max log length per scenario")
    args = p.parse_args()
    if args.sdo_mode == "block" and not args.no_local_server:
        p.error("python-canopen's local server has no block transfer; use --no-local-server with an external server")
    setup = not args.no_setup and args.interface == "socketcan"
    if args.candump_dir and (args.interface != "socketcan" or not shutil.which("candump")):
        print("  candump logs disabled (needs socketcan and can-utils)")
        args.candump_dir = ""
    if args.candump_dir and args.test != "setup":
        args.candump_dir = os.path.join(args.candump_dir, time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(args.candump_dir, exist_ok=True)
        print(f"  candump logs: {args.candump_dir}/")

    if args.test == "setup":
        setup_interfaces(args, args.bitrates[0])
        return

    rows = []
    for bitrate in args.bitrates:
        if setup:
            setup_interfaces(args, bitrate)
        th = theoretical_fps(bitrate) * 8
        for load in args.bg_loads:
            print(f"\n=== {bitrate} bit/s, background load {load} % ===")
            rows.append(make_row(args, bitrate, load, "Theoretical", "-", int(th * (1 - load / 100)), 1.0,
                                 note="calculated, 8 B frames"))
            with BackgroundLoad(args, bitrate, load) as bg:
                if args.test in ("raw", "all"):
                    with CandumpLog(args, bitrate, load, "raw simplex"):
                        rows += run_raw(args, bitrate, load, duplex=False)
                    if args.duplex:
                        with CandumpLog(args, bitrate, load, "raw duplex"):
                            rows += run_raw(args, bitrate, load, duplex=True)
                if args.test in ("sdo", "all"):
                    with CandumpLog(args, bitrate, load, "sdo"):
                        rows += run_sdo(args, bitrate, load)
        if setup:
            for name in (args.a, args.b):
                print(f"  {name} after tests: {iface_info(name)}")

    print_summary(rows, args.file_mb)
    if args.csv:
        new = not os.path.exists(args.csv)
        with open(args.csv, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp", "file_MB"] + list(rows[0].keys()))
            if new:
                w.writeheader()
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            for r in rows:
                w.writerow({"timestamp": ts, "file_MB": args.file_mb, **r})
        print(f"\nResults appended to {args.csv}")


if __name__ == "__main__":
    main()
