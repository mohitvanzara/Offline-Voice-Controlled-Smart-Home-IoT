import paho.mqtt.client as mqtt
import vosk
import json
import os

vosk.SetLogLevel(-1)

# ─── Settings ────────────────────────────────────────────
MQTT_BROKER  = "localhost"
MQTT_PORT    = 1883
TOPIC_AUDIO  = "audio/stream"
TOPIC_TEXT   = "cmd/text"
MODEL_PATH   = "/home/mohit-pi/DE-Project/vosk-model-small-en-us-0.15"
SAMPLE_RATE  = 16000

# ─── Vocab List ──────────────────────────────────────────
# Sirf yahi words recognize honge — faster & more accurate
VOCAB = [
    "hey esp", "hey pi", "hey room",
    "light on", "light off",
    "turn on light", "turn off light",
    "motor on", "motor off",
    "turn on motor", "turn off motor",
    "buzzer on", "buzzer off",
    "turn on buzzer", "turn off buzzer",
    "all off", "everything off",
    "[unk]"
]

# ─── Load Vosk Model ─────────────────────────────────────
print("[Vosk] Loading model...")
if not os.path.exists(MODEL_PATH):
    print(f"[ERROR] Model not found: {MODEL_PATH}")
    exit(1)

model      = vosk.Model(MODEL_PATH)
recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE, json.dumps(VOCAB))
print("[Vosk] Model loaded with vocab list!")
print(f"[Vosk] Listening for: {', '.join(VOCAB[:-1])}\n")

# ─── Wake Word State ─────────────────────────────────────
WAKE_WORDS = ["hey esp", "hey pi", "hey room"]

# ─── MQTT Client ─────────────────────────────────────────
client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[MQTT] Connected to broker!")
        client.subscribe(TOPIC_AUDIO)
        print(f"[MQTT] Subscribed to: {TOPIC_AUDIO}")
        print("[SYSTEM] Waiting for wake word...\n")
    else:
        print(f"[MQTT] Connection failed rc={rc}")

def on_message(client, userdata, msg):
    audio_data = msg.payload

    if recognizer.AcceptWaveform(audio_data):
        result = json.loads(recognizer.Result())
        text   = result.get("text", "").strip()

        if not text or text == "[unk]":
            return

        print(f"[Vosk] Heard: '{text}'")

        # Check if wake word
        is_wake = any(w in text for w in WAKE_WORDS)
        if is_wake:
            print("[WAKE] Wake word detected! Sending to ESP32...")
            print("[SYSTEM] Waiting for command...\n")

        # Send all recognized text to ESP32
        # ESP32 handles wake word + command logic
        client.publish(TOPIC_TEXT, text)
        print(f"[MQTT] Sent: '{text}'\n")

    else:
        partial = json.loads(recognizer.PartialResult())
        p_text  = partial.get("partial", "").strip()
        if p_text:
            print(f"[Vosk] Partial: {p_text}", end="\r")

def on_disconnect(client, userdata, rc):
    print(f"\n[MQTT] Disconnected rc={rc}")

# ─── Start ───────────────────────────────────────────────
client.on_connect    = on_connect
client.on_message    = on_message
client.on_disconnect = on_disconnect

print(f"[MQTT] Connecting to {MQTT_BROKER}:{MQTT_PORT}...")
client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

print("[SYSTEM] Running... Press Ctrl+C to stop.")
try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\n[SYSTEM] Stopped.")
    client.disconnect()