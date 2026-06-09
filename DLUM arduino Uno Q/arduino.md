# Communication VSCode ↔ Arduino UNO Q

Ce document décrit la chaîne d'outils et les étapes pour compiler, flasher et
déboguer le firmware MCU du DLUM (sketch `dlum_mcu/`) depuis VSCode sur un PC
Windows, ainsi que pour interagir avec la partie Linux de la carte UNO Q.

## 1. Architecture rappel

L'Arduino UNO Q héberge **deux processeurs** sur la même carte :

- **MCU** : STM32U585, sous Zephyr RTOS. C'est lui qui exécute le `.ino`.
- **SoC Linux** : Debian 13 aarch64. Il sert l'UI web (`backend/dlum_server.py`)
  et fait passerelle vers le MCU.

Côté connectique USB unique :

- **Interface MI_00** (Android Composite ADB) → shell Linux via `adb`.
- **Interface MI_01** (CDC série) → port `COM` Windows.
  Ce COM est **bridgé par `arduino-router-serial`** côté Linux : tu ne parles
  pas directement à l'UART du MCU mais à `/dev/ttyGS0`, lui-même routé vers
  `/dev/ttyHS1` par le démon `arduino-router` en framing **msgpack-RPC**.

Concrètement, depuis le PC :

| Outil                       | Cible       | Via                       |
|-----------------------------|-------------|---------------------------|
| `arduino-cli compile`       | MCU         | (local, pas de carte)     |
| `arduino-cli upload`        | MCU         | OpenOCD/SWD via ADB       |
| `arduino-cli monitor`       | MCU `Serial1` | port COM (router msgpack) |
| `adb shell`                 | Linux       | USB ADB                   |
| Navigateur                  | Backend web | Wi-Fi, port 8000          |

## 2. Prérequis (déjà installés sur ce poste)

| Composant                  | Chemin                                                                                  | Version |
|----------------------------|-----------------------------------------------------------------------------------------|---------|
| `arduino-cli`              | `%LOCALAPPDATA%\Programs\arduino-cli\arduino-cli.exe`                                   | 1.4.1   |
| Core Arduino               | `arduino:zephyr` (FQBN `arduino:zephyr:unoq`)                                            | 0.54.1  |
| ADB récent                 | `C:\Android\platform-tools-new\platform-tools\adb.exe`                                  | 1.0.41  |
| VSCode                     | extension Microsoft (terminal PowerShell intégré suffit)                                 | —       |

> ⚠️ Le vieil ADB en `C:\Android\adb.exe` (v1.0.32) **ne fonctionne pas** avec
> l'UNO Q : utiliser exclusivement la version `platform-tools-new`.

> ⚠️ L'**extension Arduino officielle** de VSCode est dépréciée et ne connaît
> pas le core `arduino:zephyr`. On utilise directement `arduino-cli` dans le
> terminal — c'est plus simple et plus robuste.

### Première install sur un nouveau poste

Tout `winget` ci-dessous se lance dans un PowerShell **non admin** (sauf
mention contraire). Redémarrer VSCode après l'installation des outils CLI pour
que le `PATH` soit rafraîchi.

#### a. VSCode + Git + Python

```powershell
winget install --id Microsoft.VisualStudioCode -e
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
```

#### b. arduino-cli + core Zephyr

```powershell
winget install --id ArduinoSA.CLI -e
& "$env:LOCALAPPDATA\Programs\arduino-cli\arduino-cli.exe" core update-index
& "$env:LOCALAPPDATA\Programs\arduino-cli\arduino-cli.exe" core install arduino:zephyr
```

Vérifier ensuite que la board est connue :

```powershell
& "$env:LOCALAPPDATA\Programs\arduino-cli\arduino-cli.exe" board listall arduino:zephyr
# doit lister "arduino:zephyr:unoq"
```

#### c. ADB récent (platform-tools)

Télécharger
[platform-tools.zip](https://dl.google.com/android/repository/platform-tools-latest-windows.zip)
et le décompresser dans `C:\Android\platform-tools-new\` (chemin attendu par
les commandes du repo). **Ne pas** garder un ancien `C:\Android\adb.exe`
isolé : il sera plus prioritaire dans le PATH et cassera la chaîne (cf. note
ci-dessus).

```powershell
# Vérification
& "C:\Android\platform-tools-new\platform-tools\adb.exe" version
# doit afficher "Android Debug Bridge version 1.0.41" ou supérieur
```

#### d. Pilote USB Windows pour l'UNO Q

Au premier branchement, Windows installe automatiquement deux interfaces :

- **MI_00** → driver `WinUSB` (ADB). Si Windows refuse, installer Zadig
  ([zadig.akeo.ie](https://zadig.akeo.ie/)) et associer manuellement le device
  `Arduino UNO Q (Interface 0)` à `WinUSB`.
- **MI_01** → driver série CDC standard (créé tout seul un `COM`).

Tester avec :

```powershell
& "C:\Android\platform-tools-new\platform-tools\adb.exe" devices
Get-PnpDevice -Class Ports -PresentOnly | Where-Object FriendlyName -match 'USB'
```

#### e. Extensions VSCode recommandées

```powershell
code --install-extension ms-vscode.cpptools          # IntelliSense pour les .ino
code --install-extension ms-python.python            # backend Python
code --install-extension ms-python.vscode-pylance    # type-checking Python
code --install-extension ms-vscode.powershell        # terminal/scripts PS
code --install-extension dotjoshjohnson.xml          # lecture des unit systemd / svg
```

Ces extensions permettent à VSCode de supporter le développement Arduino UNO Q et
le backend Python du DLUM sans tenter de forcer l'ancienne extension Arduino
officielle.

Un fichier de recommandations de workspace a été ajouté : `.vscode/extensions.json`.

> ⚠️ **Ne PAS installer** l'extension `vsciot-vscode.vscode-arduino` (Arduino
> for VSCode) : elle est en *maintenance mode* et ne reconnaît pas le core
> `arduino:zephyr`. Elle ajoutera des faux-positifs dans IntelliSense et
> tentera de lancer un `arduino-cli` interne incompatible.

#### f. Workspace `.vscode/` à la racine du projet

Créer (ou laisser Git créer si déjà committé) `.vscode/settings.json` :

```json
{
  "files.eol": "\n",
  "[python]": { "editor.defaultFormatter": "ms-python.python" },
  "C_Cpp.default.includePath": [
    "${env:LOCALAPPDATA}/Arduino15/packages/arduino/hardware/zephyr/0.54.1/cores/arduino",
    "${env:LOCALAPPDATA}/Arduino15/packages/arduino/hardware/zephyr/0.54.1/variants/arduino_uno_q_stm32u585xx",
    "${env:LOCALAPPDATA}/Arduino15/packages/arduino/hardware/zephyr/0.54.1/libraries/**"
  ],
  "C_Cpp.default.defines": ["ARDUINO=10607", "ARDUINO_ARCH_ZEPHYR"],
  "files.associations": { "*.ino": "cpp" }
}
```

Ces chemins permettent à IntelliSense de résoudre `Arduino.h`, `Servo.h`, etc.
sans erreur dans les `.ino`. Adapter le `0.54.1` si une autre version du core
est installée (vérif : `dir "$env:LOCALAPPDATA\Arduino15\packages\arduino\hardware\zephyr"`).

#### g. Récap des chemins à connaître après install

| Ressource                    | Chemin                                                                    |
|------------------------------|---------------------------------------------------------------------------|
| arduino-cli                  | `%LOCALAPPDATA%\Programs\arduino-cli\arduino-cli.exe`                     |
| Cores Arduino                | `%LOCALAPPDATA%\Arduino15\packages\`                                      |
| ADB                          | `C:\Android\platform-tools-new\platform-tools\adb.exe`                    |
| Settings utilisateur VSCode  | `%APPDATA%\Code\User\settings.json`                                       |
| Profil PowerShell            | `%USERPROFILE%\Documents\PowerShell\Microsoft.PowerShell_profile.ps1`     |

## 3. Détecter la carte

Brancher le câble USB unique de l'UNO Q sur le PC. Windows expose alors
**deux interfaces** :

```powershell
Get-PnpDevice -Class Ports -PresentOnly | Where-Object FriendlyName -match 'USB'
& "C:\Android\platform-tools-new\platform-tools\adb.exe" devices
```

Tu dois voir :

- Un nouveau port `COM` (le numéro varie selon le PC : ici `COM3`, sur d'autres
  postes ça peut être `COM4`, `COM7`, etc.). VID=`2341`, PID=`0078`, MI_01.
- Un appareil ADB (ex. `1663532562   device`).

> Si `COM3` est déjà pris par autre chose (ex. un Icom USB-to-Serial), Windows
> assigne le COM suivant disponible. Toujours **relire** le port avant chaque
> commande.

## 4. Workflow VSCode

Ouvrir le dossier projet (`e:\10 - Presta\UNOQ`) dans VSCode. Le terminal
intégré (PowerShell) est tout ce dont on a besoin.

### 4.1 Compiler le sketch MCU

```powershell
& "$env:LOCALAPPDATA\Programs\arduino-cli\arduino-cli.exe" compile `
    -b arduino:zephyr:unoq `
    .\dlum_mcu
```

Sortie attendue : `Sketch uses XXX bytes (Y%) of program storage`. Pas de
warning bloquant, sinon vérifier le sketch.

### 4.2 Téléverser sur le MCU

```powershell
& "$env:LOCALAPPDATA\Programs\arduino-cli\arduino-cli.exe" upload `
    -b arduino:zephyr:unoq `
    -p COM3 `
    .\dlum_mcu
```

Le flash passe par **OpenOCD/SWD bit-bangé via libgpiod** côté Linux : il ne
traverse PAS `arduino-router`. Le MCU est donc reflashable même si le routeur
est arrêté.

### 4.3 Monitor série (les `Serial.print` du MCU)

```powershell
& "$env:LOCALAPPDATA\Programs\arduino-cli\arduino-cli.exe" monitor `
    -p COM3 -c baudrate=115200
```

> ⚠️ **Subtilité critique** : sur le MCU, `Serial` (USART1) sort sur les pins
> physiques D0/D1 du header → **invisible** depuis le PC. Pour que les
> `print()` arrivent jusqu'au COM Windows, il faut utiliser **`Serial1`**
> (LPUART1). C'est `Serial1` qui passe par `/dev/ttyHS1` puis le routeur.

Si le moniteur affiche des erreurs `invalid packet, expected array, got: int8`
côté Linux (visibles via `journalctl -u arduino-router`), c'est que ton firmware
écrit du texte brut sur `Serial1` au lieu d'un frame msgpack-RPC. Trois sorties
possibles, documentées dans `reference_unoq_architecture.md` :

1. Désactiver `arduino-router` et utiliser `/dev/ttyHS1` directement.
2. Utiliser `SocketWrapper` pour exposer un socket TCP depuis le MCU.
3. Implémenter un client msgpack-RPC dans le firmware.

## 5. Accès au Linux (debug, logs, services)

### 5.1 Shell ADB

```powershell
& "C:\Android\platform-tools-new\platform-tools\adb.exe" shell
```

L'utilisateur par défaut est `arduino` (membre des groupes `dialout`, `gpio`).

### 5.2 Logs des services DLUM

```bash
# Une fois dans le shell ADB :
sudo journalctl -u dlum-server -f
sudo journalctl -u dlum-netwatch -f
sudo journalctl -u arduino-router -f
```

### 5.3 Push de fichiers (backend Python, units systemd)

```powershell
$adb = "C:\Android\platform-tools-new\platform-tools\adb.exe"
& $adb push backend/dlum_server.py /home/arduino/dlum/
& $adb shell sudo systemctl restart dlum-server
```

## 6. Tâches VSCode (optionnel mais pratique)

Pour appeler tout ça en un raccourci `Ctrl+Shift+B`, créer
`.vscode/tasks.json` à la racine :

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "MCU: compile",
      "type": "shell",
      "command": "${env:LOCALAPPDATA}\\Programs\\arduino-cli\\arduino-cli.exe",
      "args": ["compile", "-b", "arduino:zephyr:unoq", "${workspaceFolder}/dlum_mcu"],
      "group": { "kind": "build", "isDefault": true },
      "problemMatcher": ["$gcc"]
    },
    {
      "label": "MCU: upload (COM3)",
      "type": "shell",
      "command": "${env:LOCALAPPDATA}\\Programs\\arduino-cli\\arduino-cli.exe",
      "args": ["upload", "-b", "arduino:zephyr:unoq", "-p", "COM3", "${workspaceFolder}/dlum_mcu"],
      "group": "build"
    },
    {
      "label": "MCU: monitor (COM3)",
      "type": "shell",
      "command": "${env:LOCALAPPDATA}\\Programs\\arduino-cli\\arduino-cli.exe",
      "args": ["monitor", "-p", "COM3", "-c", "baudrate=115200"],
      "presentation": { "reveal": "always", "panel": "dedicated" }
    },
    {
      "label": "Linux: shell ADB",
      "type": "shell",
      "command": "C:\\Android\\platform-tools-new\\platform-tools\\adb.exe",
      "args": ["shell"],
      "presentation": { "reveal": "always", "panel": "dedicated" }
    }
  ]
}
```

> Ajuster le `COM3` si le port assigné par Windows est différent.

## 7. Dépannage rapide

| Symptôme                                            | Cause probable                                          | Action                                                                 |
|-----------------------------------------------------|---------------------------------------------------------|------------------------------------------------------------------------|
| `arduino-cli upload` : `port not found`             | Mauvais COM, ou carte non énumérée                      | `Get-PnpDevice -Class Ports`, vérifier MI_01                           |
| Upload qui hang puis timeout                        | OpenOCD côté Linux bloqué, GPIO 70 figé                 | `adb shell sudo systemctl restart arduino-router`                      |
| `adb devices` vide                                  | Vieux ADB en cache, ou ADB serveur planté               | Tuer `adb.exe`, relancer avec **platform-tools-new**                   |
| Aucun output au moniteur                            | Sketch utilise `Serial` au lieu de `Serial1`            | Remplacer `Serial.print` → `Serial1.print` dans `dlum_mcu.ino`         |
| Moniteur reçoit des bytes mais journal hurle msgpack| Conflit avec `arduino-router`                           | Voir §4.3, choisir un des trois chemins                                |
| Carte ne broadcast plus 192.168.42.1                | `dlum-netwatch` n'a pas basculé en AP                   | `journalctl -u dlum-netwatch`, vérifier qu'aucun WiFi connu n'est dispo|

## 8. Références internes au repo

- `projet.md` : spécification fonctionnelle DLUM
- `dlum_mcu/dlum_mcu.ino` : firmware MCU
- `backend/` : serveur web Python + units systemd
- `docs/cablage.md` + `docs/cablage-schema.svg` : câblage physique servos/bouton
