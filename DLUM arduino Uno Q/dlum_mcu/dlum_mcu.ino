#include <Servo.h>
#include <ArduinoJson.h>
#include <ArduinoGraphics.h>      // doit être avant Arduino_LED_Matrix pour la text API
#include <Arduino_LED_Matrix.h>

// Support up to 8 cadres. activeFrameCount runtime-configurable from backend.
constexpr uint8_t MAX_FRAMES = 8;
uint8_t FRAME_COUNT = 4; // current active count, can be changed via "set_frame_count"
constexpr uint8_t SERVO_PINS[MAX_FRAMES] = {9, 10, 11, 12, 5, 6, 8, 3};
constexpr uint8_t BUTTON_PIN = 2;

// Servos étendus 0..270°. Ranges PWM 500-2500us classiques pour 270° servos.
constexpr int SERVO_PULSE_MIN = 500;
constexpr int SERVO_PULSE_MAX = 2500;
constexpr int SERVO_RANGE_DEG = 270;

// Per-motor calibration. Angles in degrees [0..270].
// Defaults : 30° down, 130° up (~100° d'amplitude utile).
int posDown[MAX_FRAMES] = {30, 30, 30, 30, 30, 30, 30, 30};
int posUp[MAX_FRAMES]   = {130, 130, 130, 130, 130, 130, 130, 130};
bool servoAttached[MAX_FRAMES] = {false, false, false, false, false, false, false, false};
uint32_t servoIdleSince[MAX_FRAMES] = {0, 0, 0, 0, 0, 0, 0, 0};

constexpr uint16_t MOVE_DURATION_MS = 300;
constexpr uint16_t MOVE_STEP_MS     = 15;
// Mode "repos" contrôlé manuellement (cmd "set_rest"). Quand restMode=true,
// tous les servos sont détachés (PWM coupé) → silence, pas de saccade, pas de
// conso. Quand on repasse à false, ils sont ré-attachés.
bool restMode = false;
constexpr uint16_t DEBOUNCE_MS      = 300;  // tolère pédales/contacts mécaniques bruyants
constexpr uint32_t HEARTBEAT_TIMEOUT_MS = 5000;

// Auto-demo disabled by default — cadres restent BAS au boot et ne bougent
// QUE sur commande explicite via Serial1. Activable manuellement via
// {"cmd":"demo","on":1} si besoin pour un test hardware.
constexpr uint32_t DEMO_STEP_MS = 2000;
// Demo patterns définis pour les 4 premiers cadres ; les positions au-delà
// (cadres 5-8) restent à 0 quand on tourne en démo avec un FRAME_COUNT > 4.
const uint8_t DEMO_PATTERN[][MAX_FRAMES] = {
  {1, 0, 1, 0, 0, 0, 0, 0},
  {0, 1, 0, 1, 0, 0, 0, 0},
  {1, 1, 0, 0, 0, 0, 0, 0},
  {0, 0, 1, 1, 0, 0, 0, 0},
  {1, 0, 0, 1, 0, 0, 0, 0},
  {0, 1, 1, 0, 0, 0, 0, 0},
};
constexpr uint8_t DEMO_PATTERN_COUNT = sizeof(DEMO_PATTERN) / sizeof(DEMO_PATTERN[0]);
bool demoEnabled = false;

Servo servos[MAX_FRAMES];

// On-board 12×8 LED matrix : déclaration; impl placée plus bas après les variables d'état.
ArduinoLEDMatrix ledMatrix;
bool ledDirty = true;
uint32_t lastLedTick = 0;
uint32_t ledBootHoldUntil = 0;
void renderLedMatrix();
void emitError(const char* code, int requested = -1);
inline void markLedDirty() { ledDirty = true; }

uint8_t  currentTarget[MAX_FRAMES] = {0, 0, 0, 0, 0, 0, 0, 0};
int      currentAngle[MAX_FRAMES]  = {30, 30, 30, 30, 30, 30, 30, 30};
uint16_t liftHoldMs = 0;   // configurable hold after each lift command
uint32_t holdUntilMs = 0;  // millis() deadline; while active, lift is blocked

uint16_t remainingHoldMs() {
  if (holdUntilMs == 0) return 0;
  int32_t diff = (int32_t)(holdUntilMs - millis());
  if (diff <= 0) return 0;
  if (diff > 65535) return 65535;
  return (uint16_t)diff;
}

void writeServoAngle(uint8_t i, int angleDeg) {
  if (angleDeg < 0) angleDeg = 0;
  if (angleDeg > SERVO_RANGE_DEG) angleDeg = SERVO_RANGE_DEG;
  long us = (long)SERVO_PULSE_MIN +
            ((long)(SERVO_PULSE_MAX - SERVO_PULSE_MIN) * angleDeg) / SERVO_RANGE_DEG;
  servos[i].writeMicroseconds((int)us);
  currentAngle[i] = angleDeg;
}
uint32_t lastMoveTick = 0;
uint16_t currentStep  = 0;

// LED matrix : either rendered from cadres state (default) or from
// a backend-pushed 8x12 bitmap (when ledOverride==true).
uint16_t ledRows[8] = {0};
bool ledOverride = false;

void renderLedMatrix() {
  if (millis() < ledBootHoldUntil) return;

  // La matrice s'attend à canvasWidth=13. Si on envoie 12 cols, chaque rangée
  // est décalée par rapport à la suivante. On utilise donc frame[8][13] avec
  // col 12 = unused/padding.
  uint8_t frame[8][13] = {{0}};
  if (ledOverride) {
    for (uint8_t r = 0; r < 8; r++) {
      uint16_t bits = ledRows[r];
      for (uint8_t c = 0; c < 12; c++) {
        frame[r][c] = (bits >> c) & 1u;
      }
    }
  } else {
    uint8_t colsPerCadre = 12 / FRAME_COUNT;
    if (colsPerCadre < 1) colsPerCadre = 1;
    for (uint8_t c = 0; c < FRAME_COUNT; c++) {
      if (currentTarget[c]) {
        for (uint8_t row = 0; row < 7; row++) {
          for (uint8_t k = 0; k < colsPerCadre; k++) {
            uint8_t col = c * colsPerCadre + k;
            if (col < 12) frame[row][col] = 1;
          }
        }
      }
    }
    uint8_t pct = currentStep % 12;
    for (uint8_t col = 0; col < pct && col < 12; col++) {
      frame[7][col] = 1;
    }
  }
  ledMatrix.renderBitmap(frame, 8, 13);
}

void handleLedSet(JsonDocument& doc) {
  JsonArray rows = doc["rows"].as<JsonArray>();
  if (rows.isNull() || rows.size() != 8) { emitError("bad_led_rows"); return; }
  for (uint8_t i = 0; i < 8; i++) {
    ledRows[i] = (uint16_t)(rows[i].as<int>() & 0x0FFF);
  }
  ledOverride = true;
  markLedDirty();
}

void handleLedClear() {
  ledOverride = false;
  markLedDirty();
}

void handleSetFrameCount(JsonDocument& doc) {
  int n = doc["count"].as<int>();
  if (n < 2 || n > MAX_FRAMES) { emitError("bad_frame_count"); return; }
  // Attach any new servos (lazy attach so we don't drive PWM on unused pins)
  for (uint8_t i = FRAME_COUNT; i < (uint8_t)n; i++) {
    if (!servoAttached[i]) {
      servos[i].attach(SERVO_PINS[i], SERVO_PULSE_MIN, SERVO_PULSE_MAX);
      servoAttached[i] = true;
    }
    writeServoAngle(i, posDown[i]);
    currentTarget[i] = 0;
  }
  // Detach any servos no longer needed (free their PWM resource)
  for (uint8_t i = (uint8_t)n; i < FRAME_COUNT; i++) {
    if (servoAttached[i]) {
      servos[i].detach();
      servoAttached[i] = false;
    }
    currentTarget[i] = 0;
  }
  FRAME_COUNT = (uint8_t)n;
  markLedDirty();
  emitState();
}

// Bouton externe : machine d'état polled (anti-rebond robuste).
// Un appui n'est validé qu'après 50ms ininterrompus à LOW. Un nouvel appui
// ne peut être validé que 500ms après le précédent.
constexpr uint16_t BUTTON_STABLE_MS = 80;
constexpr uint16_t BUTTON_LOCKOUT_MS = 1500;  // 1 appui par 1.5s max
enum ButtonState { BTN_IDLE, BTN_PRESSING, BTN_PRESSED };
ButtonState buttonState = BTN_IDLE;
uint32_t buttonStateSince = 0;
uint32_t buttonLastAcceptedMs = 0;
bool buttonPressedFlag = false;

uint32_t lastHeartbeatMs = 0;
uint32_t lastSerialActivityMs = 0;
uint32_t lastDemoStepMs = 0;
uint8_t  demoIndex = 0;

// Polled button state machine (no ISR). Appelé à chaque tour de loop().
void pollButton() {
  uint32_t now = millis();
  bool low = (digitalRead(BUTTON_PIN) == LOW);
  switch (buttonState) {
    case BTN_IDLE:
      if (low) {
        buttonState = BTN_PRESSING;
        buttonStateSince = now;
      }
      break;
    case BTN_PRESSING:
      if (!low) {
        // bruit, retour idle
        buttonState = BTN_IDLE;
      } else if (now - buttonStateSince >= BUTTON_STABLE_MS) {
        // appui validé (LOW stable depuis BUTTON_STABLE_MS)
        if (now - buttonLastAcceptedMs >= BUTTON_LOCKOUT_MS) {
          buttonPressedFlag = true;
          buttonLastAcceptedMs = now;
        }
        buttonState = BTN_PRESSED;
      }
      break;
    case BTN_PRESSED:
      if (!low) {
        // relâche : on doit attendre que la ligne soit HIGH stable avant
        // de retourner en IDLE — anti-rebond sur la fermeture du contact
        buttonState = BTN_IDLE;
      }
      break;
  }
}

void ensureServoAttached(uint8_t i) {
  // Ré-attache un servo détaché. Repart de son dernier currentAngle pour
  // éviter un saut brusque (le servo se rappelle de sa position).
  if (!servoAttached[i] && i < FRAME_COUNT) {
    servos[i].attach(SERVO_PINS[i], SERVO_PULSE_MIN, SERVO_PULSE_MAX);
    servoAttached[i] = true;
    writeServoAngle(i, currentAngle[i]);
  }
}

void applyTargets(const uint8_t targets[]) {
  for (uint8_t i = 0; i < FRAME_COUNT; i++) {
    currentTarget[i] = targets[i] ? 1 : 0;
    // Si on veut lever ce cadre, ré-attacher le servo s'il était détaché
    if (currentTarget[i]) ensureServoAttached(i);
    // Reset du compteur d'idle (tout changement de target compte comme activité)
    servoIdleSince[i] = 0;
  }
}

void stepServosToward() {
  if (restMode) return;  // mode repos : aucun mouvement, servos détachés

  uint32_t now = millis();
  if (now - lastMoveTick < MOVE_STEP_MS) return;
  lastMoveTick = now;

  for (uint8_t i = 0; i < FRAME_COUNT; i++) {
    int target = currentTarget[i] ? posUp[i] : posDown[i];
    int diff = target - currentAngle[i];
    if (diff == 0) continue;
    // Assurer qu'il est attaché
    ensureServoAttached(i);
    int span = posUp[i] - posDown[i];
    if (span < 0) span = -span;
    if (span < 1) span = 1;
    int stepSize = (span * MOVE_STEP_MS) / MOVE_DURATION_MS;
    if (stepSize < 1) stepSize = 1;
    int next;
    if (diff > 0) next = (diff <= stepSize) ? target : currentAngle[i] + stepSize;
    else          next = (-diff <= stepSize) ? target : currentAngle[i] - stepSize;
    writeServoAngle(i, next);
  }
}

void emitJsonToHosts(StaticJsonDocument<192>& doc) {
  serializeJson(doc, Serial);
  Serial.println();
  serializeJson(doc, Serial1);
  Serial1.println();
}

void emitState() {
  StaticJsonDocument<160> doc;
  doc["evt"] = "state";
  doc["step"] = currentStep;
  doc["rest"] = restMode;
  JsonArray f = doc["frames"].to<JsonArray>();
  for (uint8_t i = 0; i < FRAME_COUNT; i++) f.add(currentTarget[i]);
  serializeJson(doc, Serial);
  Serial.println();
  serializeJson(doc, Serial1);
  Serial1.println();
}

void emitError(const char* code, int requested) {
  StaticJsonDocument<96> doc;
  doc["evt"] = "error";
  doc["code"] = code;
  if (requested >= 0) doc["requested"] = requested;
  serializeJson(doc, Serial);
  Serial.println();
  serializeJson(doc, Serial1);
  Serial1.println();
}

void emitButton() {
  StaticJsonDocument<64> doc;
  doc["evt"] = "button";
  doc["ts"] = millis();
  serializeJson(doc, Serial);
  Serial.println();
  serializeJson(doc, Serial1);
  Serial1.println();
}

void handleLift(JsonDocument& doc) {
  bool force = doc["force"].as<bool>();
  uint16_t remain = remainingHoldMs();
  if (!force && remain > 0) {
    emitError("hold_active", remain);
    return;
  }
  JsonArray frames = doc["frames"].as<JsonArray>();
  if (frames.isNull() || frames.size() != FRAME_COUNT) {
    emitError("bad_frames");
    return;
  }
  uint8_t targets[MAX_FRAMES] = {0};
  uint8_t raised = 0;
  for (uint8_t i = 0; i < FRAME_COUNT; i++) {
    targets[i] = frames[i].as<int>() ? 1 : 0;
    raised += targets[i];
  }
  // Safety: at least 1 raised, at most FRAME_COUNT-1 (never all up, never none).
  if (raised < 1 || raised > (FRAME_COUNT - 1)) {
    emitError("invalid_count", raised);
    return;
  }
  if (doc["step"].is<uint16_t>()) currentStep = doc["step"].as<uint16_t>();
  applyTargets(targets);
  holdUntilMs = millis() + liftHoldMs;
  markLedDirty();
  emitState();
}

void handleManual(JsonDocument& doc) {
  int frame = doc["frame"].as<int>();
  int state = doc["state"].as<int>();
  if (frame < 0 || frame >= FRAME_COUNT) {
    emitError("bad_frame_index");
    return;
  }
  uint8_t targets[MAX_FRAMES] = {0};
  uint8_t raised = 0;
  for (uint8_t i = 0; i < FRAME_COUNT; i++) {
    targets[i] = currentTarget[i];
  }
  targets[frame] = state ? 1 : 0;
  for (uint8_t i = 0; i < FRAME_COUNT; i++) raised += targets[i];
  if (raised > (FRAME_COUNT - 1)) {
    emitError("too_many_frames", raised);
    return;
  }
  applyTargets(targets);
  markLedDirty();
  emitState();
}

void handleAllDown() {
  for (uint8_t i = 0; i < FRAME_COUNT; i++) currentTarget[i] = 0;
  holdUntilMs = 0;
  markLedDirty();
  emitState();
}

void handleAllUp() {
  // Maintenance: bypass the 1-3 safety. Use only via Pilotage tab.
  for (uint8_t i = 0; i < FRAME_COUNT; i++) currentTarget[i] = 1;
  markLedDirty();
  emitState();
}

uint32_t pinTestRevertAt = 0;
uint8_t  pinTestPin = 0xFF;
uint8_t  pinTestPrevTarget = 0;

void handlePinTest(JsonDocument& doc) {
  // Direct physical pin diagnostic: lift the servo on logical position
  // `pin` (0..3 = SERVO_PINS index) for ~1s, then revert to previous state.
  int pin = doc["pin"].as<int>();
  if (pin < 0 || pin >= FRAME_COUNT) {
    emitError("bad_pin_index");
    return;
  }
  pinTestPin = (uint8_t)pin;
  pinTestPrevTarget = currentTarget[pin];
  currentTarget[pin] = 1;
  pinTestRevertAt = millis() + 1200;
  markLedDirty();
  emitState();
}

void checkPinTestRevert() {
  if (pinTestPin == 0xFF) return;
  if (millis() >= pinTestRevertAt) {
    currentTarget[pinTestPin] = pinTestPrevTarget;
    pinTestPin = 0xFF;
    markLedDirty();
    emitState();
  }
}

void handleSetAngle(JsonDocument& doc) {
  // {"cmd":"set_angle","motor":i,"down":N,"up":N} — set per-motor angles
  int motor = doc["motor"].as<int>();
  if (motor < 0 || motor >= FRAME_COUNT) { emitError("bad_motor_index"); return; }
  if (doc["down"].is<int>()) {
    int d = doc["down"].as<int>();
    if (d < 0) d = 0; if (d > SERVO_RANGE_DEG) d = SERVO_RANGE_DEG;
    posDown[motor] = d;
  }
  if (doc["up"].is<int>()) {
    int u = doc["up"].as<int>();
    if (u < 0) u = 0; if (u > SERVO_RANGE_DEG) u = SERVO_RANGE_DEG;
    posUp[motor] = u;
  }
  // Re-apply current target so the servo moves to its new resting position
  int target = currentTarget[motor] ? posUp[motor] : posDown[motor];
  // We don't jump immediately, stepServosToward() handles smooth motion.
  emitState();
}

void handleLiveServo(JsonDocument& doc) {
  // {"cmd":"live_servo","motor":i,"angle":N} — directly set a servo to angle
  // for calibration test. Bypasses the up/down logic; user must re-issue
  // a command to bring it back into the normal flow.
  int motor = doc["motor"].as<int>();
  int angle = doc["angle"].as<int>();
  if (motor < 0 || motor >= FRAME_COUNT) { emitError("bad_motor_index"); return; }
  ensureServoAttached(motor);
  servoIdleSince[motor] = 0;  // évite un détachement immédiat post-calibration
  writeServoAngle(motor, angle);
}

void emitAngles() {
  StaticJsonDocument<192> doc;
  doc["evt"] = "angles";
  JsonArray d = doc["down"].to<JsonArray>();
  JsonArray u = doc["up"].to<JsonArray>();
  for (uint8_t i = 0; i < FRAME_COUNT; i++) { d.add(posDown[i]); u.add(posUp[i]); }
  serializeJson(doc, Serial);
  Serial.println();
  serializeJson(doc, Serial1);
  Serial1.println();
}

void processCommand(const String& line) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, line);
  if (err) {
    emitError("bad_json");
    return;
  }
  lastHeartbeatMs = millis();
  const char* cmd = doc["cmd"];
  if (!cmd) {
    if (doc["ping"].as<bool>()) return;
    emitError("missing_cmd");
    return;
  }
  if (strcmp(cmd, "lift") == 0)        handleLift(doc);
  else if (strcmp(cmd, "manual") == 0) handleManual(doc);
  else if (strcmp(cmd, "all_down") == 0) handleAllDown();
  else if (strcmp(cmd, "all_up") == 0)   handleAllUp();
  else if (strcmp(cmd, "pin_test") == 0) handlePinTest(doc);
  else if (strcmp(cmd, "set_angle") == 0) handleSetAngle(doc);
  else if (strcmp(cmd, "live_servo") == 0) handleLiveServo(doc);
  else if (strcmp(cmd, "get_angles") == 0) emitAngles();
  else if (strcmp(cmd, "led_set") == 0) handleLedSet(doc);
  else if (strcmp(cmd, "led_clear") == 0) handleLedClear();
  else if (strcmp(cmd, "set_rest") == 0) {
    bool on = doc["on"].as<bool>();
    restMode = on;
    if (on) {
      // Détache tous les servos : silence, plus de saccade, plus de conso
      for (uint8_t i = 0; i < FRAME_COUNT; i++) {
        if (servoAttached[i]) {
          servos[i].detach();
          servoAttached[i] = false;
        }
      }
    } else {
      // Réveille : ré-attache et applique les targets courantes
      for (uint8_t i = 0; i < FRAME_COUNT; i++) {
        ensureServoAttached(i);
      }
    }
    markLedDirty();
    emitState();
  }
  else if (strcmp(cmd, "led_brand") == 0) {
    // Affiche "5426 DLUM" en scroll sur la matrice (marque de fabrique).
    ledOverride = false;
    ledMatrix.beginText(0, 1, 127, 0, 0);
    ledMatrix.print("  5426 DLUM  ");
    ledMatrix.endText(SCROLL_LEFT);
    markLedDirty();
  }
  else if (strcmp(cmd, "led_text") == 0) {
    // Texte arbitraire scrollé. {"cmd":"led_text","text":"HOTSPOT"}
    const char* text = doc["text"];
    if (text == nullptr) return;
    ledOverride = false;
    ledMatrix.beginText(0, 1, 127, 0, 0);
    ledMatrix.print("  ");
    ledMatrix.print(text);
    ledMatrix.print("  ");
    ledMatrix.endText(SCROLL_LEFT);
    markLedDirty();
  }
  else if (strcmp(cmd, "led_countdown") == 0) {
    // Décompte 3-2-1 : chaque chiffre affiché grand (5×5) et centré 1 s.
    // {"cmd":"led_countdown"}  — bloquant ~3 s (servos déjà en bas côté Pi).
    // Glyphes 5 cols × 5 rows, bit4 = colonne gauche.
    const uint8_t GLYPHS[3][5] = {
      {0b01110, 0b00001, 0b00110, 0b00001, 0b01110},  // 3
      {0b01110, 0b00001, 0b01110, 0b10000, 0b11111},  // 2
      {0b00100, 0b01100, 0b00100, 0b00100, 0b01110},  // 1
    };
    ledOverride = false;
    constexpr uint8_t START_COL = 3;  // (12-5)/2 = 3 → centré
    constexpr uint8_t START_ROW = 1;  // rows 1-5 sur 8
    for (uint8_t d = 0; d < 3; d++) {
      uint8_t frame[8][13] = {{0}};
      for (uint8_t gr = 0; gr < 5; gr++) {
        for (uint8_t gc = 0; gc < 5; gc++) {
          if ((GLYPHS[d][gr] >> (4 - gc)) & 1) {
            frame[START_ROW + gr][START_COL + gc] = 1;
          }
        }
      }
      ledMatrix.renderBitmap(frame, 8, 13);
      delay(1000);
    }
    markLedDirty();
  }
  else if (strcmp(cmd, "led_test") == 0) {
    uint8_t fullOn[8][13] = {{0}};
    for (uint8_t r = 0; r < 8; r++) for (uint8_t c = 0; c < 12; c++) fullOn[r][c] = 1;
    ledMatrix.renderBitmap(fullOn, 8, 13);
    delay(1500);
    markLedDirty();
  }
  else if (strcmp(cmd, "led_debug") == 0) {
    // Séquence de 4 phases : 1 LED allumée à chaque coin, 3 secondes chacune.
    // L'utilisateur observe quelle LED réelle s'allume pour identifier le mapping.
    ledOverride = false;
    uint8_t p[8][13];
    memset(p, 0, sizeof(p)); p[0][0] = 1;
    ledMatrix.renderBitmap(p, 8, 13); delay(3000);
    memset(p, 0, sizeof(p)); p[0][11] = 1;
    ledMatrix.renderBitmap(p, 8, 13); delay(3000);
    memset(p, 0, sizeof(p)); p[7][0] = 1;
    ledMatrix.renderBitmap(p, 8, 13); delay(3000);
    memset(p, 0, sizeof(p)); p[7][11] = 1;
    ledMatrix.renderBitmap(p, 8, 13); delay(3000);
    markLedDirty();
  }
  else if (strcmp(cmd, "set_frame_count") == 0) handleSetFrameCount(doc);
  else if (strcmp(cmd, "set_hold_ms") == 0) {
    int v = doc["value"].as<int>();
    if (v < 0) v = 0;
    if (v > 20000) v = 20000;
    liftHoldMs = (uint16_t)v;
  }
  else if (strcmp(cmd, "ping") == 0)   emitState();
  else if (strcmp(cmd, "demo") == 0) {
    demoEnabled = doc["on"].as<bool>();
    if (!demoEnabled) handleAllDown();
    emitState();
  }
  else emitError("unknown_cmd");
}

void readSerialLinesFrom(Stream& port, String& buffer) {
  while (port.available()) {
    char c = (char)port.read();
    lastSerialActivityMs = millis();
    if (c == '\n') {
      buffer.trim();
      if (buffer.length() > 0) processCommand(buffer);
      buffer = "";
    } else if (buffer.length() < 250) {
      buffer += c;
    }
  }
}

void readSerialLines() {
  static String bufferUsb;
  static String bufferUart;
  readSerialLinesFrom(Serial, bufferUsb);
  readSerialLinesFrom(Serial1, bufferUart);
}

void checkHeartbeat() {
  if (lastHeartbeatMs == 0) return;
  if (millis() - lastHeartbeatMs > HEARTBEAT_TIMEOUT_MS) {
    bool anyRaised = false;
    for (uint8_t i = 0; i < FRAME_COUNT; i++) if (currentTarget[i]) { anyRaised = true; break; }
    if (anyRaised) {
      handleAllDown();
      emitError("heartbeat_lost");
    }
    lastHeartbeatMs = millis();
  }
}

void runDemoIfIdle() {
  if (!demoEnabled) return;
  uint32_t now = millis();
  if (now - lastDemoStepMs < DEMO_STEP_MS) return;
  lastDemoStepMs = now;
  const uint8_t* pat = DEMO_PATTERN[demoIndex];
  for (uint8_t i = 0; i < FRAME_COUNT; i++) currentTarget[i] = pat[i];
  demoIndex = (demoIndex + 1) % DEMO_PATTERN_COUNT;
  digitalWrite(LED_BUILTIN, demoIndex & 1);
  markLedDirty();
}

void setup() {
  Serial.begin(115200);
  Serial1.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  // Pas d'interruption : on poll la ligne dans loop() avec une state machine
  // anti-rebond robuste (voir pollButton).
  for (uint8_t i = 0; i < FRAME_COUNT; i++) {
    servos[i].attach(SERVO_PINS[i], SERVO_PULSE_MIN, SERVO_PULSE_MAX);
    servoAttached[i] = true;
    writeServoAngle(i, posDown[i]);
  }
  ledMatrix.begin();
  ledMatrix.textFont(Font_5x7);
  ledMatrix.textScrollSpeed(60);
  // Self-test : toutes les LED allumées au boot
  {
    uint8_t fullOn[8][13] = {{0}};
    for (uint8_t r = 0; r < 8; r++)
      for (uint8_t c = 0; c < 12; c++)
        fullOn[r][c] = 1;
    ledMatrix.renderBitmap(fullOn, 8, 13);
    delay(800);
  }
  // Marque de fabrique : "5426" scrolle au boot
  ledMatrix.beginText(0, 1, 127, 0, 0);
  ledMatrix.print("  5426 DLUM  ");
  ledMatrix.endText(SCROLL_LEFT);
  ledBootHoldUntil = millis() + 5000;
  emitState();
}

void loop() {
  readSerialLines();
  pollButton();
  if (buttonPressedFlag) {
    buttonPressedFlag = false;
    emitButton();
  }
  runDemoIfIdle();
  checkPinTestRevert();
  stepServosToward();
  checkHeartbeat();
  if (ledDirty) {
    ledDirty = false;
    renderLedMatrix();
  }
}
