import socket
import struct
import time
import threading

# ==== Configuration ====
SERVER_IP = "192.168.1.164"
SERVER_PORT = 12000
TOTAL_MESSAGES = 5000
DELAY_BETWEEN_MSGS = 0.001
CAN_INTERFACE = "pican1"
CAN_ID = 0x123

received_payloads = []
sent_count = 0
recv_count = 0
stop_receiving = False

# Timing
first_sent_time = None
first_received_time = None
last_sent_time = None
last_received_time = None


def can_listener(interface):
    """Read CAN frames directly from SocketCAN."""
    global stop_receiving, recv_count, first_received_time, last_received_time
    can_sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    can_sock.bind((interface,))
    can_sock.settimeout(1.0)
    print(f"📡 Listening on {interface}...")

    while not stop_receiving:
        try:
            frame, _ = can_sock.recvfrom(16)
            can_id, can_dlc, data = struct.unpack("=IB3x8s", frame)
            if can_id == CAN_ID:
                payload = data[:can_dlc].hex().upper()
                received_payloads.append(payload)
                recv_count += 1
                now = time.time()
                if first_received_time is None:
                    first_received_time = now
                last_received_time = now
                print(f"⬅️  RX[{recv_count:04d}]: {can_id:03X} [{can_dlc}] {payload}")
        except socket.timeout:
            continue
        except Exception as e:
            print(f"❌ CAN read error: {e}")
            break

    can_sock.close()


def send_test_sequence(ip, port, total_messages, delay):
    """Send sequential CAN-like messages over TCP."""
    global sent_count, first_sent_time, last_sent_time
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((ip, port))
            print(f"✅ Connected to {ip}:{port}")

            for i in range(total_messages):
                payload = f"{i:04X}"  # 0000 → 03E7
                msg = f"123#{payload}\n"
                now = time.time()
                if first_sent_time is None:
                    first_sent_time = now
                last_sent_time = now

                sock.sendall(msg.encode("ascii"))
                sent_count += 1
                print(f"[{sent_count:04d}] ➡️ Sent: {msg.strip()}")
                time.sleep(delay)

            print(f"✅ Sent {total_messages} messages")

    except Exception as e:
        print(f"❌ TCP Error: {e}")


def analyze_results():
    """Detect missing individual payloads and print timing stats."""
    print("\n🔍 Analyzing received payloads...")
    print(f"📤 Sent messages: {sent_count}")
    print(f"📥 Received messages: {recv_count}")

    if first_sent_time and first_received_time:
        print(f"⏱ Time first sent → first received: {first_received_time - first_sent_time:.6f} s")
    if last_sent_time and last_received_time:
        print(f"⏱ Time last sent → last received: {last_received_time - last_sent_time:.6f} s")
    if first_sent_time and last_received_time:
        print(f"⏱ Total duration: {last_received_time - first_sent_time:.6f} s")

    if not received_payloads:
        print("❌ No CAN frames received!")
        return

    received_nums = set(int(p, 16) for p in received_payloads)

    missing = []
    for expected in range(TOTAL_MESSAGES):
        if expected not in received_nums:
            missing.append(f"{expected:04X}")

    if missing:
        print(f"⚠️ Missing {len(missing)} individual messages:")
        print("   " + " ".join(missing))
    else:
        print("✅ No missing messages detected.")


if __name__ == "__main__":
    can_thread = threading.Thread(target=can_listener, args=(CAN_INTERFACE,))
    can_thread.start()

    time.sleep(0.5)  # allow listener to start

    send_test_sequence(SERVER_IP, SERVER_PORT, TOTAL_MESSAGES, DELAY_BETWEEN_MSGS)

    time.sleep(2)  # allow CAN frames to arrive
    stop_receiving = True
    can_thread.join()

    analyze_results()
