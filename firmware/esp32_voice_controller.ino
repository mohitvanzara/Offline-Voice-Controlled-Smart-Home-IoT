#include <WiFi.h>
#include <PubSubClient.h>
#include <driver/i2s.h>

// ─── WiFi Settings ───────────────────────────────────────
const char* WIFI_SSID     = "xxxx";
const char* WIFI_PASSWORD = "xxxx";

// ─── MQTT Settings ───────────────────────────────────────
const char* MQTT_BROKER   = "rpi_ip";
const int   MQTT_PORT     = 1883;
const char* TOPIC_AUDIO   = "audio/stream";
const char* TOPIC_CMD     = "cmd/text";
const char* TOPIC_STATUS  = "device/status";

// ─── I2S / INMP441 Pins ──────────────────────────────────
#define I2S_SCK   14
#define I2S_WS    15
#define I2S_SD    32

// ─── Device GPIO Pins ────────────────────────────────────
#define PIN_LED     4    // Wake word indicator LED
#define PIN_LIGHT   26   // Light relay
#define PIN_MOTOR   27   // Motor relay
#define PIN_BUZZER  25   // Buzzer

// ─── Audio Settings ──────────────────────────────────────
#define SAMPLE_RATE   16000
#define BUFFER_SIZE   1024

WiFiClient   espClient;
PubSubClient mqtt(espClient);
int16_t audioBuffer[BUFFER_SIZE / 2];

bool wakeWordActive = false;
unsigned long wakeWordTime = 0;
#define WAKE_TIMEOUT  5000  // 5 seconds listen window

bool lightState  = false;
bool motorState  = false;
bool buzzerState = false;

// ─── LED Helpers ─────────────────────────────────────────
void setLED(bool state) {
  digitalWrite(PIN_LED, state ? HIGH : LOW);
}

void blinkLED(int times, int delayMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_LED, HIGH); delay(delayMs);
    digitalWrite(PIN_LED, LOW);  delay(delayMs);
  }
}

// ─── I2S Setup ───────────────────────────────────────────
void setupI2S() {
  i2s_config_t i2s_config = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 8,
    .dma_buf_len          = 64,
    .use_apll             = false,
    .tx_desc_auto_clear   = false,
    .fixed_mclk           = 0
  };
  i2s_pin_config_t pin_config = {
    .bck_io_num   = I2S_SCK,
    .ws_io_num    = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num  = I2S_SD
  };
  i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pin_config);
  i2s_start(I2S_NUM_0);
  Serial.println("[I2S] Initialized");
}

// ─── WiFi Connect ────────────────────────────────────────
void connectWiFi() {
  Serial.print("[WiFi] Connecting to ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.print("\n[WiFi] Connected! IP: ");
  Serial.println(WiFi.localIP());
}

// ─── Command Handler ─────────────────────────────────────
void handleCommand(String text) {
  text.toLowerCase();
  text.trim();
  Serial.print("[CMD] Received: ");
  Serial.println(text);

  // Wake word check
  if (text.indexOf("hey esp")  >= 0 ||
      text.indexOf("hey pi")   >= 0 ||
      text.indexOf("hey room") >= 0) {
    wakeWordActive = true;
    wakeWordTime   = millis();
    setLED(true);
    Serial.println("[WAKE] Activated! Listening for command...");
    mqtt.publish(TOPIC_STATUS, "AWAKE");
    return;
  }

  if (!wakeWordActive) {
    Serial.println("[CMD] Ignored - say wake word first");
    return;
  }

  bool matched = true;

  // Light
  if      (text.indexOf("light on")  >= 0 || text.indexOf("turn on light")  >= 0) {
    digitalWrite(PIN_LIGHT, HIGH); lightState = true;
    Serial.println("[CMD] Light ON");
    mqtt.publish(TOPIC_STATUS, "LIGHT:ON");

  } else if (text.indexOf("light off") >= 0 || text.indexOf("turn off light") >= 0) {
    digitalWrite(PIN_LIGHT, LOW); lightState = false;
    Serial.println("[CMD] Light OFF");
    mqtt.publish(TOPIC_STATUS, "LIGHT:OFF");

  // Motor
  } else if (text.indexOf("motor on")  >= 0 || text.indexOf("turn on motor")  >= 0) {
    digitalWrite(PIN_MOTOR, HIGH); motorState = true;
    Serial.println("[CMD] Motor ON");
    mqtt.publish(TOPIC_STATUS, "MOTOR:ON");

  } else if (text.indexOf("motor off") >= 0 || text.indexOf("turn off motor") >= 0) {
    digitalWrite(PIN_MOTOR, LOW); motorState = false;
    Serial.println("[CMD] Motor OFF");
    mqtt.publish(TOPIC_STATUS, "MOTOR:OFF");

  // Buzzer
  } else if (text.indexOf("buzzer on")  >= 0 || text.indexOf("turn on buzzer")  >= 0) {
    digitalWrite(PIN_BUZZER, HIGH); buzzerState = true;
    Serial.println("[CMD] Buzzer ON");
    mqtt.publish(TOPIC_STATUS, "BUZZER:ON");

  } else if (text.indexOf("buzzer off") >= 0 || text.indexOf("turn off buzzer") >= 0) {
    digitalWrite(PIN_BUZZER, LOW); buzzerState = false;
    Serial.println("[CMD] Buzzer OFF");
    mqtt.publish(TOPIC_STATUS, "BUZZER:OFF");

  // All off
  } else if (text.indexOf("all off") >= 0 || text.indexOf("everything off") >= 0) {
    digitalWrite(PIN_LIGHT,  LOW);
    digitalWrite(PIN_MOTOR,  LOW);
    digitalWrite(PIN_BUZZER, LOW);
    lightState = motorState = buzzerState = false;
    Serial.println("[CMD] All OFF");
    mqtt.publish(TOPIC_STATUS, "ALL:OFF");
    blinkLED(3, 150);

  } else {
    matched = false;
    Serial.println("[CMD] No match found");
  }

  if (matched) blinkLED(2, 100);

  // Reset after command
  wakeWordActive = false;
  setLED(false);
}

// ─── MQTT Callback ───────────────────────────────────────
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String text = "";
  for (unsigned int i = 0; i < length; i++) text += (char)payload[i];
  handleCommand(text);
}

// ─── MQTT Connect ────────────────────────────────────────
void connectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("[MQTT] Connecting...");
    if (mqtt.connect("ESP32_MIC")) {
      Serial.println(" Connected!");
      mqtt.subscribe(TOPIC_CMD);
    } else {
      Serial.print(" Failed rc=");
      Serial.print(mqtt.state());
      Serial.println(" Retrying in 3s...");
      delay(3000);
    }
  }
}

// ─── Setup ───────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(PIN_LED,    OUTPUT);
  pinMode(PIN_LIGHT,  OUTPUT);
  pinMode(PIN_MOTOR,  OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  digitalWrite(PIN_LED,    LOW);
  digitalWrite(PIN_LIGHT,  LOW);
  digitalWrite(PIN_MOTOR,  LOW);
  digitalWrite(PIN_BUZZER, LOW);

  Serial.println("=== ESP32 Voice Control Starting ===");
  connectWiFi();
  setupI2S();

  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  mqtt.setBufferSize(2048);
  connectMQTT();

  blinkLED(3, 200);  // Ready signal
  Serial.println("[SYSTEM] Ready! Say 'Hey ESP' / 'Hey Pi' / 'Hey Room'");
}

// ─── Loop ────────────────────────────────────────────────
void loop() {
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  // Wake word timeout check
  if (wakeWordActive && (millis() - wakeWordTime > WAKE_TIMEOUT)) {
    wakeWordActive = false;
    setLED(false);
    Serial.println("[WAKE] Timeout - back to sleep");
    mqtt.publish(TOPIC_STATUS, "SLEEP");
  }

  // Read and publish audio
  size_t bytesRead = 0;
  i2s_read(I2S_NUM_0, audioBuffer, BUFFER_SIZE, &bytesRead, portMAX_DELAY);
  if (bytesRead > 0) {
    mqtt.publish(TOPIC_AUDIO, (uint8_t*)audioBuffer, bytesRead, false);
  }
}
