import base64
import socket
import subprocess
import threading
from pathlib import Path


LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 18994
PLINK = r"C:\Program Files\PuTTY\plink.exe"
SSH_HOST = "10.101.0.36"
SSH_PORT = "2222"
SSH_USER = "v6yvdcnv#root#bec2604c-ae04-4222-85f3-b399f6ab2e51"
SSH_PASS = "Qingbei36974!"
REMOTE_HOST = "127.0.0.1"
REMOTE_PORT = 18992
LOG_PATH = Path(r"E:\Desktop\lunwen\reports\local_minicpmo_exec_tunnel.log")


def log(msg: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


REMOTE_BRIDGE_SOURCE = f"""
import socket, sys, threading
s = socket.create_connection(('{REMOTE_HOST}', {REMOTE_PORT}))
def sock_to_remote():
    try:
        while True:
            data = sys.stdin.buffer.read1(65536)
            if not data:
                break
            s.sendall(data)
    except Exception:
        pass
    try:
        s.shutdown(socket.SHUT_WR)
    except Exception:
        pass
threading.Thread(target=sock_to_remote, daemon=True).start()
try:
    while True:
        data = s.recv(65536)
        if not data:
            break
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
except Exception:
    pass
try:
    s.close()
except Exception:
    pass
"""

REMOTE_BRIDGE_B64 = base64.b64encode(REMOTE_BRIDGE_SOURCE.encode("utf-8")).decode("ascii")
REMOTE_BRIDGE = (
    "python3 -u -c "
    f"\"import base64; exec(base64.b64decode('{REMOTE_BRIDGE_B64}').decode('utf-8'))\""
)


def pump_sock_to_proc(sock: socket.socket, proc: subprocess.Popen) -> None:
    try:
        while True:
            data = sock.recv(65536)
            if not data:
                break
            proc.stdin.write(data)
            proc.stdin.flush()
    except Exception:
        pass
    try:
        proc.stdin.close()
    except Exception:
        pass


def pump_proc_to_sock(proc: subprocess.Popen, sock: socket.socket) -> None:
    try:
        while True:
            data = proc.stdout.read(65536)
            if not data:
                break
            sock.sendall(data)
    except Exception:
        pass
    try:
        sock.shutdown(socket.SHUT_WR)
    except Exception:
        pass


def handle_client(sock: socket.socket) -> None:
    log("client connected")
    proc = subprocess.Popen(
        [
            PLINK,
            "-ssh",
            "-batch",
            "-P",
            SSH_PORT,
            "-l",
            SSH_USER,
            "-pw",
            SSH_PASS,
            SSH_HOST,
            REMOTE_BRIDGE,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    t1 = threading.Thread(target=pump_sock_to_proc, args=(sock, proc), daemon=True)
    t2 = threading.Thread(target=pump_proc_to_sock, args=(proc, sock), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    log("client disconnected")
    try:
        sock.close()
    except Exception:
        pass
    try:
        proc.terminate()
    except Exception:
        pass


def serve() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((LISTEN_HOST, LISTEN_PORT))
        srv.listen(50)
        log(f"listening http://{LISTEN_HOST}:{LISTEN_PORT} -> {SSH_HOST}:{REMOTE_PORT}")
        print(f"listening http://{LISTEN_HOST}:{LISTEN_PORT}", flush=True)
        while True:
            client, _ = srv.accept()
            threading.Thread(target=handle_client, args=(client,), daemon=True).start()


if __name__ == "__main__":
    try:
        serve()
    except Exception as exc:
        log(f"fatal: {exc!r}")
        raise
