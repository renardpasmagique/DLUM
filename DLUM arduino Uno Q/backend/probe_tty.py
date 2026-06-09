"""Read/write /dev/ttyHS1 via pyserial, send a ping, capture any response."""
import serial
import time

PORT = "/dev/ttyHS1"
BAUD = 115200

print(f"opening {PORT}@{BAUD}...")
s = serial.Serial(PORT, BAUD, timeout=0.3)
print("opened OK")
time.sleep(0.5)

print("sending ping")
s.write(b'{"cmd":"ping"}\n')
s.flush()

end = time.time() + 6
buf = b""
while time.time() < end:
    data = s.read(512)
    if data:
        buf += data
        print("RX raw:", data)
print("--- total bytes:", len(buf), "---")
print("--- printable:", buf.decode("utf-8", errors="replace"))
s.close()
