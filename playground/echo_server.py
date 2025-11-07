#!/usr/bin/env python3
import socket, traceback

HOST = "0.0.0.0"
PORT = 65432

def main():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(5)                          # backlog 5
        print(f"Echo server listening on {HOST}:{PORT}")
    except Exception as e:
        print("Failed to bind/listen:", e)
        traceback.print_exc()
        return

    while True:
        try:
            conn, addr = s.accept()
            print(f"Accepted connection from {addr}")
            with conn:
                conn.settimeout(30)
                while True:
                    data = conn.recv(4096)
                    if not data:
                        print(f"Client {addr} closed connection")
                        break
                    print(f"Received from {addr!s}: {data!r}")
                    conn.sendall(data)
        except KeyboardInterrupt:
            print("Shutting down")
            break
        except Exception as e:
            print("Exception in accept loop:", e)
            traceback.print_exc()

if __name__ == "__main__":
    main()
