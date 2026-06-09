"""
Copie les fichiers backend DLUM modifiés vers l'Arduino UNO Q via SSH/SFTP,
puis redémarre le serveur sur la cible.
"""
import paramiko, sys, os

HOST = "192.168.137.184"
USER = "arduino"
PASS = "5426liam"

LOCAL_BASE = r"C:\Users\liams\Desktop\DLUM-propre\backend"

# Fichiers à copier : (chemin local relatif, chemin distant absolu)
FILES = [
    ("static/index.html",    "/home/pi/DLUM-propre/backend/static/index.html"),
    ("static/draft.js",      "/home/pi/DLUM-propre/backend/static/draft.js"),
    ("static/draft.css",     "/home/pi/DLUM-propre/backend/static/draft.css"),
    ("dlum_server.py",       "/home/pi/DLUM-propre/backend/dlum_server.py"),
    ("settings_store.py",    "/home/pi/DLUM-propre/backend/settings_store.py"),
]

def find_remote_base(ssh):
    """Détecte le dossier DLUM sur la cible."""
    candidates = [
        "/home/arduino/dlum/backend",
        "/home/arduino/dlum",
        "/home/arduino/DLUM-propre/backend",
        "/home/pi/DLUM-propre/backend",
        "/home/pi/dlum/backend",
        "/root/DLUM-propre/backend",
        "/opt/dlum/backend",
    ]
    for c in candidates:
        _, stdout, _ = ssh.exec_command(f"test -d {c} && echo YES")
        if stdout.read().strip() == b"YES":
            return c
    return None

def main():
    print(f"Connexion à {USER}@{HOST} …")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, username=USER, password=PASS, timeout=10)
    except Exception as e:
        print(f"ERREUR connexion : {e}")
        sys.exit(1)
    print("Connecté !")

    # Détection du dossier distant
    remote_base = find_remote_base(ssh)
    if remote_base is None:
        # Lister home pour aider
        _, out, _ = ssh.exec_command("ls /home/pi/")
        print("Dossiers disponibles :", out.read().decode())
        print("ERREUR : dossier DLUM introuvable sur la cible.")
        ssh.close()
        sys.exit(1)
    print(f"Dossier distant trouvé : {remote_base}")

    sftp = ssh.open_sftp()

    for local_rel, remote_path in FILES:
        # Recalcule le chemin distant selon le base détecté
        filename = os.path.basename(local_rel)
        subdir   = os.path.dirname(local_rel)
        if subdir:
            remote_full = remote_base + "/" + subdir + "/" + filename
        else:
            remote_full = remote_base + "/" + filename

        local_full = os.path.join(LOCAL_BASE, local_rel)
        if not os.path.exists(local_full):
            print(f"  SKIP (introuvable localement) : {local_full}")
            continue
        try:
            sftp.put(local_full, remote_full)
            print(f"  ✓ {local_rel} → {remote_full}")
        except Exception as e:
            print(f"  ✗ {local_rel} : {e}")

    sftp.close()

    # Redémarrer le serveur DLUM sur la cible
    print("\nRedémarrage du serveur DLUM …")
    restart_cmds = [
        "sudo systemctl restart dlum 2>/dev/null && echo 'systemctl OK'",
        "pkill -f dlum_server && sleep 1 && echo 'pkill OK'",
    ]
    for cmd in restart_cmds:
        _, out, err = ssh.exec_command(cmd)
        result = out.read().decode().strip()
        if result:
            print(f"  {result}")
            break

    ssh.close()
    print("\nDéploiement terminé !")

if __name__ == "__main__":
    main()
