"""Diagnostic et redémarrage du serveur DLUM sur Arduino UNO Q."""
import paramiko, time, sys

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
    err = e.read().decode().strip()
    if label:
        print(f"\n=== {label} ===")
    if out: print(out)
    if err: print("ERR:", err)
    return out

# 1. Ports série
run("ls /dev/ttyS* /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || echo aucun", "Ports série")

# 2. Processus en cours
run("pgrep -a python3", "Processus python3")

# 3. Variable DLUM_SERIAL_PORT
run("grep -r DLUM_SERIAL /home/arduino/dlum/ 2>/dev/null | head -5 || echo non defini", "DLUM_SERIAL_PORT")

# 4. Service systemd
run("systemctl status dlum-server.service --no-pager 2>/dev/null | head -20", "Service dlum-server")

# 5. Logs via journalctl
run("journalctl -u dlum-server.service -n 20 --no-pager 2>/dev/null", "Logs service")

# 6. Redémarrage via systemd (conserve l'env DLUM_SERIAL_PORT=/dev/ttyHS1)
print("\n=== Redémarrage via systemd ===")
_, o, _ = c.exec_command("echo '5426liam' | sudo -S systemctl restart dlum-server.service 2>&1", timeout=15)
out = o.read().decode().strip()
if out: print(out)
time.sleep(3)

# 7. Vérifier
run("systemctl is-active dlum-server.service", "Statut service")
run("journalctl -u dlum-server.service -n 5 --no-pager 2>/dev/null", "Derniers logs")

c.close()
