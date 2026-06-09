"""Trouver la config de démarrage + tester les ports série sur l'Arduino UNO Q."""
import paramiko, time

HOST = "192.168.137.184"
USER = "arduino"
PASS = "5426liam"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PASS, timeout=10)
print("Connecté !")

def run(cmd, label=""):
    _, o, e = c.exec_command(cmd, timeout=10)
    out = o.read().decode().strip()
    if label: print(f"\n=== {label} ===")
    if out: print(out)
    else: print("(vide)")
    return out

run("cat /etc/rc.local 2>/dev/null | head -20", "rc.local")
run("ls /etc/systemd/system/ 2>/dev/null | grep dlum", "systemd dlum")
run("crontab -l 2>/dev/null", "crontab")
run("ls /home/arduino/ArduinoApps/ 2>/dev/null", "ArduinoApps")
run("cat /home/arduino/dlum/start.sh /home/arduino/dlum/run.sh /home/arduino/dlum/.env 2>/dev/null", "scripts démarrage")
run("cat /proc/540/environ 2>/dev/null | tr '\\0' '\\n' | grep -i 'serial\\|dlum\\|tty'", "env netwatch")
run("ls -la /dev/ttyS*", "ttyS permissions")
run("cat /proc/$(pgrep -f dlum_server | head -1)/environ 2>/dev/null | tr '\\0' '\\n' | grep -i 'serial\\|tty\\|dlum'", "env dlum_server")

# Tuer tous les serveurs dupliqués et relancer avec ttyS1
print("\n=== Relance avec ttyS1 ===")
run("pkill -f dlum_server.py; sleep 1; echo killed")
time.sleep(2)

chan = c.get_transport().open_session()
chan.exec_command("cd /home/arduino/dlum && DLUM_SERIAL_PORT=/dev/ttyS1 python3 dlum_server.py > /tmp/dlum.log 2>&1 &")
chan.close()
time.sleep(4)

out = run("tail -8 /tmp/dlum.log", "Logs après relance avec ttyS1")
if "Serial open" in out:
    print("\n✓ MCU connecté via /dev/ttyS1 !")
elif "Serial" in out:
    print("\n⚠ Activité série détectée")
else:
    # Essayer ttyS0
    print("\n→ ttyS1 ne marche pas, essai ttyS0...")
    run("pkill -f dlum_server.py; sleep 1; echo killed")
    time.sleep(2)
    chan = c.get_transport().open_session()
    chan.exec_command("cd /home/arduino/dlum && DLUM_SERIAL_PORT=/dev/ttyS0 python3 dlum_server.py > /tmp/dlum.log 2>&1 &")
    chan.close()
    time.sleep(4)
    run("tail -8 /tmp/dlum.log", "Logs avec ttyS0")

c.close()
print("\nFIN")
