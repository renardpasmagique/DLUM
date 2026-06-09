"""Probe arduino-router via RPC unix socket + monitor TCP port."""
import msgpack
import socket
import sys
import time
import threading

UNIX_SOCK = "/var/run/arduino-router.sock"
MONITOR_HOST = "127.0.0.1"
MONITOR_PORT = 7500


def reader(name, sock, stop):
    unp = msgpack.Unpacker(raw=False)
    raw_buf = b""
    while not stop.is_set():
        try:
            sock.settimeout(0.5)
            data = sock.recv(4096)
            if not data:
                print(f"[{name}] EOF")
                return
            raw_buf += data
            print(f"[{name}] raw {data!r}")
            try:
                unp.feed(data)
                for msg in unp:
                    print(f"[{name}] msgpack {msg!r}")
            except Exception:
                pass
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[{name}] err {e}")
            return


def main():
    stop = threading.Event()

    print("--- monitor (TCP 7500) ---")
    mon = socket.create_connection((MONITOR_HOST, MONITOR_PORT))
    mon_t = threading.Thread(target=reader, args=("MON", mon, stop), daemon=True)
    mon_t.start()

    print("--- rpc (unix socket) ---")
    rpc = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        rpc.connect(UNIX_SOCK)
    except PermissionError as e:
        print("RPC connect failed (need root?):", e)
        time.sleep(2)
        stop.set()
        return
    except FileNotFoundError as e:
        print("RPC socket missing:", e)
        time.sleep(2)
        stop.set()
        return

    rpc_t = threading.Thread(target=reader, args=("RPC", rpc, stop), daemon=True)
    rpc_t.start()

    msgid = 1
    def call(method, params):
        nonlocal msgid
        m = msgid; msgid += 1
        req = [0, m, method, params]
        rpc.sendall(msgpack.packb(req, use_bin_type=True))
        print(f"[RPC>] call id={m} {method}({params!r})")

    time.sleep(0.5)
    call("$/version", [])
    time.sleep(0.5)
    call("mon/write", [b'{"cmd":"ping"}\n'])
    time.sleep(0.5)
    # poll mon/read with max-bytes param every 200ms for ~5s
    end = time.time() + 5
    while time.time() < end:
        call("mon/read", [4096])
        time.sleep(0.4)

    stop.set()
    rpc_t.join(timeout=1)
    mon_t.join(timeout=1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
