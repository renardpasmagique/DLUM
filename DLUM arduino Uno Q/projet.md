# 🧵 DLUM — Digital Loom Upgrade Module

## 1. 🎯 Objectif du projet

Le **DLUM** est un module permettant de transformer un métier à tisser traditionnel à pédales en un métier semi-automatisé piloté numériquement.

- Remplacement des pédales mécaniques par des actionneurs motorisés
- Pilotage via une interface logicielle
- Création et exécution de motifs numériques

---

## 2. ⚙️ Fonctionnement du métier traditionnel

- Métier en bois avec **4 cadres**
- Chaque cadre est contrôlé par une pédale
- Activation :
  - Minimum : **1 pédale**
  - Maximum : **3 pédales simultanément**
- Permet la création de la foule pour le passage du fil de trame

---

## 3. 🔌 Transformation avec DLUM

### 3.1 Composants

- **4 servomoteurs** (1 par cadre) — choix v1 : servos standard taille
  haute torsion (ex. MG996R, ~10 kg·cm) ou servos linéaires si la course
  verticale du cadre dépasse celle d'un palonnier rotatif.
  *Alternatives : actionneurs linéaires électriques pour cadres lourds,
  ou solénoïdes ON/OFF si la levée est très courte.*
- **Carte Arduino UNO Q** (1 seule carte = MCU + ordinateur Linux) :
  - MCU : STM32U585 (Cortex-M33, Zephyr RTOS) → pilotage temps réel des servos
  - Linux : Debian 13 sur Qualcomm Dragonwing aarch64 → héberge l'UI web,
    la bibliothèque de motifs et le serveur d'état
  - Matrice LED 12×8 intégrée → indicateur visuel séquence/cadres levés
- **Bouton physique** (passage à la séquence suivante) — connecté à un
  GPIO du MCU avec interruption
- **Alimentation servos** : 5–6 V externe dédiée (les servos ne doivent
  PAS être alimentés par l'USB du UNO Q)
- **Interface logicielle** : application web servie par le UNO Q lui-même,
  accessible depuis n'importe quel navigateur sur le réseau local

---

### 3.2 Logique de fonctionnement

1. Création du motif sur l’interface
2. Conversion en séquences de levée
3. Utilisation sur le métier :

- Appui bouton → levée des cadres (1 à 3 max)
- Maintien en position
- Appui suivant :
  - Descente des cadres
  - Pause (~5 secondes)
  - Activation séquence suivante

---

## 4. 🧠 Interface logicielle

### 4.1 Philosophie

- Interface visuelle type grille
- Simulation en temps réel
- Préparation complète avant tissage

---

## 5. 🧩 Modules de l’interface

### 5.1 🎨 Éditeur de motifs

- Grille interactive
- Ligne = séquence
- Colonne = cadre
- Activation max : 3 cadres par ligne

#### Outils :
- Dessin manuel
- Symétrie
- Répétition
- Génération automatique

---

### 5.2 🌈 Gestion des couleurs

- Palette :
  - Haut → fils de chaîne
  - Côté → fils de trame
- Aperçu du rendu textile

---

### 5.3 🧵 Structure de tissage

#### Remettage (Threading)
- Attribution des fils aux cadres

#### Liftplan
- Définition des cadres levés par ligne

#### Trame
- Ordre et couleur des fils

#### Armure
- Simulation du rendu final

---

### 5.4 💾 Bibliothèque de motifs

- Sauvegarde
- Chargement
- Organisation (nom, tags)
- Aperçu visuel

---

### 5.5 🔍 Outils avancés

- Analyse des flottés
- Génération aléatoire
- Import d’image
- Calcul de densité et fils

---

## 6. 🎛️ Mode Production

### 6.1 Connexion

- Bouton connecter/déconnecter
- Indicateur :
  - Connecté
  - Déconnecté

---

### 6.2 Interface de tissage

- Ligne active surlignée
- Navigation :
  - Avancer
  - Reculer

---

### 6.3 Contrôle physique

- Bouton :
  - Passe à la séquence suivante
- Limite automatique :
  - Max 3 cadres levés

---

## 7. 🔧 Mode Maintenance / Pilotage manuel

Onglet **Pilotage** uniquement (la contrainte métier 1–3 cadres est levée
ici car il s'agit d'opérations de mise au point hardware) :

- Contrôle individuel des moteurs :
  - Toggle ON/OFF par moteur (cadre 1, 2, 3, 4)
- Contrôle global :
  - **Tout lever** (les 4 cadres en haut — bypass de la limite 1-3)
  - **Tout abaisser**
- Levée libre : sélection 1 à 3 cadres + envoi (respecte la contrainte
  comme en production)

---

## 7bis. ⚙️ Onglet Réglages (diagnostic hardware)

Pour vérifier que les sorties physiques du MCU correspondent bien aux
moteurs câblés (en cas d'inversion, mauvais câblage, etc.) :

### Test physique de chaque sortie

- 4 boutons **"Tester sortie D9"**, **"Tester sortie D10"**, **"Tester sortie D11"**, **"Tester sortie D12"**
- Quand on clique : le servo branché sur ce pin physique fait un cycle
  unique (haut → maintien 1s → bas), indépendamment du mapping logique
- L'utilisateur observe **quel cadre physique bouge** et note la
  correspondance réelle

### Remappage logique → physique

- 4 sélecteurs : "Cadre 1 → [D9 / D10 / D11 / D12]", idem pour 2, 3, 4
- Une fois le mapping défini, **toute commande** émise depuis Pilotage,
  Tissage, ou tout autre onglet utilise cette table de translation
- Le mapping est **persisté** sur la carte (fichier JSON côté Linux)
  et survit aux reboots
- Bouton **"Réinitialiser au défaut"** : remet 1→D9, 2→D10, 3→D11, 4→D12

Cas typique d'usage : tu câbles 4 servos sans faire attention à l'ordre,
tu testes chaque pin → tu notes que D9 contrôle en fait ton "cadre 3"
physique → tu mappes Cadre 3 → D9 dans les réglages → tout fonctionne
correctement ensuite sans recâbler.

---

## 7ter. 🦶 Bouton externe / pédale (contact sec)

Pour avancer à la duite suivante sans toucher à l'UI (mains occupées,
navette dans une main, peigne dans l'autre), un contact sec externe
peut être branché.

### Câblage

| Borne du bouton | Borne UNO Q |
|---|---|
| Contact 1 (commun) | **D2** |
| Contact 2 | **GND** |

- Type de contact : **NO** (normalement ouvert)
- Pas de résistance externe nécessaire (le firmware utilise `INPUT_PULLUP`
  qui maintient la ligne à 3.3V au repos)
- Quand on appuie, la ligne D2 est tirée à 0V → interruption sur front
  descendant → événement `button` envoyé au backend → `next_step()`
  exécuté
- Anti-rebond logiciel : 50 ms (constante `DEBOUNCE_MS` du firmware)

### Choix de matériel

- **Bouton poussoir momentané** classique
- **Pédale guitare/piano** (la plupart sont des contacts secs NO/NC,
  on prend le NO)
- **Pédale industrielle interrupteur sec** (comme une pédale de machine
  à coudre — jack 6.35 mm le plus souvent)

### Comportement

- Un appui = avance d'une duite (avec cycle tassage → levée comme
  d'habitude)
- Fonctionne **sans navigateur ouvert** : le backend reçoit l'événement
  bouton via la bridge série MCU↔Linux et déclenche `seq.next_step()`
  directement
- Si l'auto-play est en cours, l'appui sur le bouton avance prématurément
  d'une duite (court-circuite l'intervalle)

---

## 8. ⏱️ Logique temporelle (cycle d'une duite)

Pour chaque clic "Duite suivante →" en mode Tissage :

1. **Tassage** : tous les cadres descendent et restent en bas pendant
   un délai paramétrable (par défaut 2500 ms, plage 0 à 6000 ms,
   réglable dans Réglages → "Tassage entre duites").
   Cette phase laisse le temps au tisseur de tasser la trame avec
   le peigne.
2. **Levée** : les cadres concernés par la duite suivante remontent
   selon le plan de levée. Mouvement lissé sur ~300 ms.
3. **Maintien** : les cadres restent dans cette position jusqu'au
   prochain clic "Duite suivante →" (le tisseur passe alors la
   navette).
4. (retour au point 1)

Cas particuliers :
- "Duite précédente ←" applique la même séquence (tassage puis levée
  du motif précédent).
- "Arrêter (tout abaisser)" coupe immédiatement, pas de tassage.
- En mode Pilotage manuel, pas de tassage automatique (les commandes
  sont directes).

---

## 8bis bis. 🔆 Affichage matrice LED 12×8

La carte UNO Q dispose d'une matrice LED de 12 colonnes × 8 lignes
sur le PCB. Deux modes d'affichage :

### Mode défaut (pas de motif chargé)

- **4 cadres × 3 colonnes chacun** : chaque groupe représente un cadre.
  Allumé si levé.
- **Ligne 8 (du bas)** : barre de progression `currentStep modulo 12`.

### Mode aperçu tissu (motif chargé en Tissage)

À chaque duite, le backend calcule un bitmap **8 lignes × 12 colonnes**
représentant les **8 dernières duites** (du plus ancien en haut au
plus récent en bas) sur les **12 premiers fils de chaîne**, en
appliquant la formule `LED_on = liftplan[pick][threading[col]] == 1`
(la chaîne ressort si son cadre est levé). Le résultat est poussé au
MCU via la commande `led_set` (8 entiers 12-bit). Cela donne un aperçu
réel du dessin du tissu en train de se faire, qui défile au fur et à
mesure.

Implémentation :
- Librairie bundled `Arduino_LED_Matrix` côté MCU.
- Backend : `Sequencer._push_led_drawdown()` après chaque step.
- Commandes firmware : `led_set` (push bitmap), `led_clear` (retour mode
  défaut).

---

## 8ter. 📚 Bibliothèque de motifs

Pour permettre à l'utilisateur de sauvegarder ses propres motifs
(au-delà des préréglages toile/sergé/etc.) et de les retrouver
au prochain démarrage :

- Onglet **Plan de tissage** → bouton **"💾 Sauvegarder le motif courant"**
- Modal demandant un nom + description optionnelle
- Stockage : un fichier JSON par motif dans `~/dlum/library/<slug>.json`
  (incluant threading + liftplan + couleurs warp/trame + dimensions +
  date de création)
- Liste affichée en cartes dans le même onglet, click pour charger,
  bouton suppression
- Les motifs sauvegardés apparaissent **également** dans le sélecteur
  de préréglages du draft, dans un groupe « 📚 Bibliothèque » sous
  les préréglages standard (toile, sergé…). Cela permet de les charger
  via le même menu que les motifs de base.

Endpoints WebSocket : `library_list`, `library_get`, `library_save`,
`library_delete`. Persistance survit aux reboots.

---

## 8quater. ▶ Lecture automatique en Tissage

L'onglet Tissage propose un mode "lecture auto" :
- Champ **intervalle** (1-60 secondes entre duites)
- Bouton **▶ Démarrer auto** : lance la séquence automatique. À chaque
  intervalle, on émet automatiquement un "Duite suivante" (avec son
  cycle tassage + levée).
- Bouton **⏸ Arrêter auto** : stoppe la boucle (les cadres restent dans
  leur position courante).
- L'arrêt manuel ("Arrêter, tout abaisser") stoppe aussi l'auto.

Côté backend, c'est une `asyncio.Task` qui appelle `next_step` en
boucle avec `await asyncio.sleep(interval)` entre chaque appel.

---

## 8bis. 🎚️ Calibration servo (Réglages)

### Plage des servos

Les servos utilisés sont des **270°** (PWM 500-2500 µs). Le firmware
pilote chaque sortie via `writeMicroseconds` avec mappage linéaire
0°–270° → 500-2500 µs. Si tu utilises des servos 180° standards,
limite simplement les angles utilisés à 0-180° dans l'UI.

### Calibration par cadre

Chaque cadre a sa propre paire **angle bas** / **angle haut**
configurable indépendamment depuis Réglages → "Calibration servo".
Boutons ±1° et ±5° pour ajuster, bouton "▶" qui envoie le servo
à la position cible immédiatement (live preview pour vérifier
visuellement que le cadre est dans la bonne position).

### Boutons de référence ⊘ 0° / ◐ 135° / ⏹ 270°

Sur chaque carte de calibration, trois boutons pour envoyer le servo
à des positions absolues de référence :
- **⊘ 0°** : zéro mécanique du servo (utile pour vérifier le point
  de référence absolu, par ex. au montage du palonnier)
- **◐ 135°** : milieu de plage
- **⏹ 270°** : butée maximale

Indépendants des valeurs Bas/Haut configurées — c'est juste pour
tester les positions extrêmes pendant le montage hardware.

---

## 8quinquies. 🔢 Nombre de cadres configurable (2 à 8)

Le système supporte de **2 à 8 cadres** (par défaut 4). Le réglage est
dans Réglages → "Nombre de cadres". Modifier la valeur :
- Met à jour la sécurité métier : le nombre de cadres autorisés à se
  lever simultanément devient `1 ≤ raised ≤ N−1`.
- Reconfigure dynamiquement toute l'UI (toggle Pilotage, grille de
  l'éditeur simple, plan de levée du draft, mappage, calibration).
- Pousse `set_frame_count` au MCU pour qu'il attache/détache les servos
  correspondants à la volée (pins additionnels D5, D6, D8, D3 pour
  cadres 5-8, en complément de D9, D10, D11, D12).
- Persisté dans `settings.json` côté Linux.

Pins physiques disponibles dans l'ordre :
| Cadre | Pin |
|---|---|
| 1 | D9  |
| 2 | D10 |
| 3 | D11 |
| 4 | D12 |
| 5 | D5  |
| 6 | D6  |
| 7 | D8  |
| 8 | D3  |

### Persistance

- Mappage logique → physique : `~/dlum/motor_map.json`
- Angles down/up + délai tassage : `~/dlum/settings.json`
- Au boot, le backend pousse les angles persistés au MCU dès la
  connexion série établie (sinon le MCU repartirait sur ses
  défauts hardcodés).

---

## 9. 🧱 Architecture technique

### Hardware

- **Arduino UNO Q** (carte hybride MCU + Linux)
- 4 servomoteurs + alimentation 5–6 V dédiée
- Bouton poussoir + résistance pull-up (ou `INPUT_PULLUP` interne)
- Optionnel : LEDs de statut, connecteur d'alim externe pour les servos

#### Brochage MCU (proposition v1)

| Fonction | Pin UNO Q | Notes |
|---|---|---|
| Servo cadre 1 | D9 (PWM) | |
| Servo cadre 2 | D10 (PWM) | |
| Servo cadre 3 | D11 (PWM) | |
| Servo cadre 4 | D6 (PWM) | |
| Bouton "Suivant" | D2 | `INPUT_PULLUP`, déclenchement sur front descendant |
| LED matrix 12×8 | interne | indicateur de séquence courante |
| GND commun | GND | masse commune carte ↔ alim servos |

---

### Software

#### Architecture en couches

```
┌─────────────────────────────────────────┐
│  Navigateur (PC/tablette/smartphone)    │
│  Éditeur de motifs, mode production     │
└──────────────────┬──────────────────────┘
                   │ HTTP / WebSocket
┌──────────────────▼──────────────────────┐
│  UNO Q — côté Linux (Debian 13)         │
│  • Backend Python (FastAPI)             │
│  • Bibliothèque de motifs (SQLite)      │
│  • Bridge MCU (UART interne)            │
└──────────────────┬──────────────────────┘
                   │ JSON over UART
┌──────────────────▼──────────────────────┐
│  UNO Q — côté MCU (STM32U585 / Zephyr)  │
│  • Pilotage 4 servos                    │
│  • Lecture bouton (interruption)        │
│  • Sécurité : max 3 cadres levés        │
└──────────────────┬──────────────────────┘
                   │ PWM
┌──────────────────▼──────────────────────┐
│  4 servos → 4 cadres du métier          │
└─────────────────────────────────────────┘
```

#### Protocole MCU ↔ Linux (JSON line-delimited sur UART)

**Linux → MCU** (commande de levée) :
```json
{"cmd": "lift", "step": 12, "frames": [1, 0, 1, 1]}
```

**Linux → MCU** (mode maintenance individuel) :
```json
{"cmd": "manual", "frame": 2, "state": 1}
```

**Linux → MCU** (tout abaisser) :
```json
{"cmd": "all_down"}
```

**MCU → Linux** (événement bouton) :
```json
{"evt": "button", "ts": 123456}
```

**MCU → Linux** (acquittement / état) :
```json
{"evt": "state", "step": 12, "frames": [1, 0, 1, 1]}
```

**MCU → Linux** (erreur sécurité) :
```json
{"evt": "error", "code": "too_many_frames", "requested": 4}
```

#### Sécurités embarquées (MCU)

- **Limite stricte** : refus de toute commande levant plus de 3 cadres
- **Watchdog** : si pas de heartbeat Linux pendant N secondes → tout abaisser
- **Anti-rebond** bouton : 50 ms de debounce logiciel
- **Course progressive** : montée/descente lissée sur ~300 ms pour éviter
  les à-coups mécaniques

#### Frontend
- Interface graphique web (HTML/CSS/JS, framework léger)
- Grille interactive éditeur de motifs
- Mode production avec ligne courante surlignée
- Mode maintenance avec contrôles individuels par cadr