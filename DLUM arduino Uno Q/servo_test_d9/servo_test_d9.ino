#include <Servo.h>

Servo servo;

constexpr uint8_t PIN = 9;
constexpr uint8_t POS_DOWN = 30;
constexpr uint8_t POS_UP   = 130;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  servo.attach(PIN);
  servo.write(POS_DOWN);
  delay(500);
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  servo.write(POS_UP);
  delay(1500);
  digitalWrite(LED_BUILTIN, LOW);
  servo.write(POS_DOWN);
  delay(1500);
}
