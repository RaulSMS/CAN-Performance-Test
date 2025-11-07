import socket

HOST = "0.0.0.0"  # listen on all interfaces
PORT = 5000       # port you choose

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind((HOST, PORT))
sock.listen(1)

print(f"Listening on {HOST}:{PORT}...")

conn, addr = sock.accept()
print(f"Connection from {addr}")

with conn:
    while True:
        data = conn.recv(1024)
        if not data:
            break
        print(f"Received: {data.decode().strip()}")
