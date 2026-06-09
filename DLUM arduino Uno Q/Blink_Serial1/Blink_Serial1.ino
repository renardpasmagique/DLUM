void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial1.begin(115200);
  Serial1.println("Blink on Serial1 boot");
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  Serial1.println("UP");
  delay(500);
  digitalWrite(LED_BUILTIN, LOW);
  Serial1.println("DOWN");
  delay(500);
}
