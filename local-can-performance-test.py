import can
import time
import argparse
import statistics
import subprocess
import sys

# === Global Defaults ===
DEFAULT_INTERFACE = "pican1"
DEFAULT_BAUDRATE = 250000
DEFAULT_MESSAGES = 5000

def setup_can_interface(interface, baudrate):
    """Set up CAN interface using system commands"""
    try:
        print(f"Bringing down interface {interface}...")
        subprocess.run(["sudo", "ip", "link", "set", interface, "down"], check=True)
        print(f"Bringing up interface {interface} with baudrate {baudrate}...")
        subprocess.run([
            "sudo", "ip", "link", "set", interface, "up",
            "type", "can", "bitrate", str(baudrate), "restart-ms", "100"
        ], check=True)
        subprocess.run(["sudo", "ip", "link", "set", interface, "txqueuelen", str(DEFAULT_MESSAGES*2)], check=True)

        print("Interface setup complete.\n")
    except subprocess.CalledProcessError as e:
        print(f"Error setting up CAN interface: {e}")
        sys.exit(1)

def calculate_bus_load(num_messages, data_bytes, baudrate, total_time):
    """Estimate CAN bus load as % of max utilization"""
    total_bits = num_messages * (44 + data_bytes * 8)  # 44 bits overhead per standard CAN frame
    max_bits_per_second = baudrate
    bus_load = (total_bits / total_time) / max_bits_per_second * 100
    return bus_load

def main():
    parser = argparse.ArgumentParser(description="CAN Socket Performance Test")
    parser.add_argument("--interface", default=DEFAULT_INTERFACE, help="CAN interface (default pcan1)")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE, help="CAN bus baudrate (default 250k)")
    parser.add_argument("--messages", type=int, default=DEFAULT_MESSAGES, help="Number of messages to send")
    args = parser.parse_args()

    # Set up CAN interface
    setup_can_interface(args.interface, args.baudrate)

    # Initialize CAN bus
    bus = can.interface.Bus(channel=args.interface, interface='socketcan', bitrate=args.baudrate)

    msg = can.Message(arbitration_id=0x123, data=[0x11]*8, is_extended_id=False)
    timestamps = []

    print(f"Sending {args.messages} messages on {args.interface} at {args.baudrate} bps...")

    start_time = time.time()
    for i in range(args.messages):
        # payload: first 6 bytes fixed, last 2 bytes = message counter
        counter = i % 65536  # 2-byte counter wrap-around
        data = [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, (counter >> 8) & 0xFF, counter & 0xFF]
        msg = can.Message(arbitration_id=0x123, data=data, is_extended_id=False)
        
        send_time = time.time()
        bus.send(msg, timeout=0.2)  # prevent buffer overflow
        timestamps.append(send_time)
    end_time = time.time()

    # Metrics
    total_time = end_time - start_time
    msgs_per_sec = args.messages / total_time

    # Calculate inter-message times
    inter_times = [t2 - t1 for t1, t2 in zip(timestamps[:-1], timestamps[1:])]
    mean_time = statistics.mean(inter_times)
    max_time = max(inter_times)
    min_time = min(inter_times)

    # Estimate bus load
    bus_load = calculate_bus_load(args.messages, len(msg.data), args.baudrate, total_time)

    print("\n=== Performance Metrics ===")
    print(f"Total time: {total_time:.6f} s")
    print(f"Messages per second: {msgs_per_sec:.2f}")
    print(f"Inter-message time (s): min={min_time:.6f}, mean={mean_time:.6f}, max={max_time:.6f}")
    print(f"Estimated bus load: {bus_load:.2f}%")

if __name__ == "__main__":
    main()
