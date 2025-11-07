#!/usr/bin/env python3
"""
TCP to SocketCAN Bridge Server (High Performance)
Receives CAN messages over TCP and forwards them to a SocketCAN interface.

Message Format (ASCII):
  Normal CAN: <CAN_ID>#<DATA>
  Extended CAN: <CAN_ID>##<DATA>
"""

import socket
import struct
import sys
import time

CAN_EFF_FLAG = 0x80000000

def parse_can_message(msg_str):
    """Parse CAN message string into CAN ID, data, and flags."""
    msg_str = msg_str.strip()

    if '##' in msg_str:
        can_id_str, data_str = msg_str.split('##', 1)
        is_extended = True
    elif '#' in msg_str:
        can_id_str, data_str = msg_str.split('#', 1)
        is_extended = False
    else:
        raise ValueError("Invalid format")

    can_id = int(can_id_str, 16)
    data_bytes = bytes.fromhex(data_str) if data_str else b''

    if len(data_bytes) > 8:
        raise ValueError("Data too long")

    return can_id, data_bytes, is_extended


def create_can_frame(can_id, data, is_extended):
    """Create a SocketCAN frame structure."""
    if is_extended:
        can_id |= CAN_EFF_FLAG

    dlc = len(data)
    data_padded = data.ljust(8, b'\x00')

    # same layout as your original: can_id (4), can_dlc (1), can_flags (1), pad(2), data(8)
    return struct.pack("=IBB2x8s", can_id, dlc, 0, data_padded)


def handle_client(client_sock, can_socket, addr):
    """Handle incoming TCP client connection."""
    print(f"[+] Client connected: {addr}")
    buffer = ""
    msg_count = 0

    # Running delta stats (no big-list kept)
    last_time = None
    delta_count = 0
    delta_sum = 0.0
    delta_min = None
    delta_max = None

    client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)

    try:
        while True:
            data = client_sock.recv(65536)
            if not data:
                # client closed connection
                break

            buffer += data.decode('ascii', errors='ignore')

            # Process complete messages
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()

                if not line:
                    continue

                try:
                    can_id, can_data, is_extended = parse_can_message(line)
                    frame = create_can_frame(can_id, can_data, is_extended)

                    # Send to CAN with retry on buffer full
                    retry_count = 0
                    while retry_count < 5:
                        try:
                            can_socket.send(frame)
                            break
                        except OSError as e:
                            # errno 105 = ENOBUFS (No buffer space available)
                            if getattr(e, "errno", None) == 105:
                                time.sleep(0.001)
                                retry_count += 1
                            else:
                                raise

                    msg_count += 1

                    # Track delta times (time between consecutive frames processed here)
                    now = time.time()
                    if last_time is not None:
                        d = now - last_time
                        delta_count += 1
                        delta_sum += d
                        if (delta_min is None) or (d < delta_min):
                            delta_min = d
                        if (delta_max is None) or (d > delta_max):
                            delta_max = d
                    last_time = now

                    # Send ACK every 100 messages or immediately for small batches
                    if msg_count % 100 == 0 or '\n' not in buffer:
                        try:
                            client_sock.send(b"OK\n")
                        except OSError:
                            # client may have gone away — break outer loops gracefully
                            raise

                except Exception as e:
                    # reply to client with error, but keep server running for this client
                    try:
                        client_sock.send(f"ERROR: {e}\n".encode())
                    except OSError:
                        # can't send error back (client gone) -> break
                        raise

    except Exception as e:
        print(f"[!] Client error: {e}")
    finally:
        # Print session summary (keeps the original behavior + stats)
        if delta_count > 0:
            delta_mean = delta_sum / delta_count
            print(
                f"[-] Client disconnected: {addr} "
                f"(sent {msg_count} msgs, Δt mean={delta_mean:.6f}s "
                f"min={delta_min:.6f}s max={delta_max:.6f}s)"
            )
        else:
            print(f"[-] Client disconnected: {addr} (sent {msg_count} msgs, no Δt samples)")

        try:
            client_sock.close()
        except Exception:
            pass


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <CAN_INTERFACE> <TCP_PORT>")
        print(f"Example: {sys.argv[0]} can0 5555")
        sys.exit(1)

    can_interface = sys.argv[1]
    tcp_port = int(sys.argv[2])

    # Create SocketCAN socket
    try:
        can_socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        can_socket.bind((can_interface,))
        can_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
        print(f"[+] Bound to CAN interface: {can_interface}")
    except Exception as e:
        print(f"[!] Failed to open CAN interface '{can_interface}': {e}")
        sys.exit(1)

    # Create TCP server socket
    try:
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_socket.bind(("0.0.0.0", tcp_port))
        tcp_socket.listen(5)
    except Exception as e:
        print(f"[!] Failed to create/bind TCP socket on port {tcp_port}: {e}")
        can_socket.close()
        sys.exit(1)

    print(f"[+] TCP server listening on port {tcp_port}")
    print(f"[+] Ready to forward CAN messages to {can_interface}")

    try:
        while True:
            try:
                client_sock, addr = tcp_socket.accept()
                # blocking, single-client-at-a-time like your original design
                handle_client(client_sock, can_socket, addr)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # Log and continue accepting new clients
                print(f"[!] Error while accepting/handling client: {e}")
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
    finally:
        try:
            tcp_socket.close()
        except Exception:
            pass
        try:
            can_socket.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
