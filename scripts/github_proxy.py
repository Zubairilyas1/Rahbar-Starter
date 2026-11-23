import socket
import select
import sys
import threading
import traceback

def handle_client(client_sock):
    target_sock = None
    try:
        req = b""
        while b"\r\n\r\n" not in req:
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            req += chunk
        
        print("Received request:", req[:100], flush=True)
        lines = req.split(b"\r\n")
        first_line = lines[0].decode("latin1", errors="ignore")
        if not first_line.startswith("CONNECT"):
            client_sock.close()
            return
        
        target_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        target_sock.settimeout(10.0)
        target_sock.connect(("140.82.121.3", 443))
        print("Connected to 140.82.121.3:443", flush=True)
        
        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        print("Sent 200 Connection Established", flush=True)
        
        # Bi-directional forwarding
        client_sock.setblocking(True)
        target_sock.setblocking(True)

        def forward(src, dst):
            try:
                while True:
                    d = src.recv(32768)
                    if not d:
                        break
                    dst.sendall(d)
            except Exception:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        t1 = threading.Thread(target=forward, args=(client_sock, target_sock))
        t2 = threading.Thread(target=forward, args=(target_sock, client_sock))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception as e:
        print("Error in proxy handler:", e, flush=True)
        traceback.print_exc()
    finally:
        try:
            client_sock.close()
        except Exception:
            pass
        if target_sock:
            try:
                target_sock.close()
            except Exception:
                pass

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 8085))
    server.listen(10)
    print("GitHub CONNECT proxy listening on 127.0.0.1:8085 -> 140.82.121.3:443", flush=True)
    
    while True:
        client_sock, _ = server.accept()
        t = threading.Thread(target=handle_client, args=(client_sock,), daemon=True)
        t.start()

if __name__ == "__main__":
    main()
