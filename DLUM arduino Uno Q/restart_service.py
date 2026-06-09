"""Redémarrer via systemd dlum-server.service."""
import paramiko, time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.137.184', username='arduino', password='5426liam', timeout=10)
print("Connecté !")

def run(cmd, label=""):
    _, o, e = c.exec_command(cmd, timeout=12)
    out = o.read().decode().strip()
    err = e.read().decode().strip()
    if label: print(f"\n=== {label} ===")
    if out: print(out)
    if err: print("ERR:", err[:200])
    return out

# Voir le contenu du service
run("cat /etc/systemd/system/dlum-server.service", "dlum-server.service")
run("groups arduino", "groupes arduino")

# Tuer les serveurs lancés manuellement
run("pkill -f dlum_server.py 2>/dev/null; echo ok", "kill manual")
time.sleep(2)

# Redémarrer via systemd avec le mot de passe sudo en stdin
_, o, e = c.exec_command("echo '5426liam' | sudo -S systemctl restart dlum-server.service 2>&1", timeout=15)
out = o.read().decode().strip()
err = e.read().decode().strip()
print("\n=== systemctl restart ===")
if out: print(out)
if err: print(err[:300])

time.sleep(3)

# Vérifier le statut
run("systemctl status dlum-server.service --no-pager | head -25", "status service")
run("journalctl -u dlum-server.service -n 15 --no-pager 2>/dev/null", "logs service")

c.close()
print("\nFIN")
