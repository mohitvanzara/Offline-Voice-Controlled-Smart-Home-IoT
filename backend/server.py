from flask import Flask, request, jsonify, send_from_directory
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity
)
from flask_socketio import SocketIO, emit
import sqlite3
import hashlib
import os
import json
import paho.mqtt.client as mqtt
import threading

# ─── App Setup ───────────────────────────────────────────
app    = Flask(__name__)
app.config["JWT_SECRET_KEY"]        = "your-secret-key-change-this"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False  # No expiry for prototype

jwt      = JWTManager(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ─── Database ────────────────────────────────────────────
DB_PATH = "smart_home.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c    = conn.cursor()

    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # Devices table
    c.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT UNIQUE NOT NULL,
            gpio_pin INTEGER NOT NULL,
            status   TEXT DEFAULT 'off'
        )
    """)

    # Commands table
    c.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            phrase    TEXT UNIQUE NOT NULL,
            device_id INTEGER NOT NULL,
            action    TEXT NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        )
    """)

    # Default admin user (password: admin123)
    pw_hash = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)",
              ("admin", pw_hash))

    # Default devices
    default_devices = [
        ("light",  26, "off"),
        ("motor",  27, "off"),
        ("buzzer", 25, "off"),
    ]
    for name, pin, status in default_devices:
        c.execute("INSERT OR IGNORE INTO devices (name, gpio_pin, status) VALUES (?,?,?)",
                  (name, pin, status))

    # Default commands
    conn.commit()
    devices = c.execute("SELECT id, name FROM devices").fetchall()
    dev_map = {d["name"]: d["id"] for d in devices}

    default_commands = [
        ("light on",        dev_map.get("light",  1), "on"),
        ("light off",       dev_map.get("light",  1), "off"),
        ("turn on light",   dev_map.get("light",  1), "on"),
        ("turn off light",  dev_map.get("light",  1), "off"),
        ("motor on",        dev_map.get("motor",  2), "on"),
        ("motor off",       dev_map.get("motor",  2), "off"),
        ("turn on motor",   dev_map.get("motor",  2), "on"),
        ("turn off motor",  dev_map.get("motor",  2), "off"),
        ("buzzer on",       dev_map.get("buzzer", 3), "on"),
        ("buzzer off",      dev_map.get("buzzer", 3), "off"),
        ("turn on buzzer",  dev_map.get("buzzer", 3), "on"),
        ("turn off buzzer", dev_map.get("buzzer", 3), "off"),
    ]
    for phrase, dev_id, action in default_commands:
        c.execute("INSERT OR IGNORE INTO commands (phrase, device_id, action) VALUES (?,?,?)",
                  (phrase, dev_id, action))

    conn.commit()
    conn.close()
    print("[DB] Database initialized!")

# ─── MQTT Setup ──────────────────────────────────────────
MQTT_BROKER  = "localhost"
MQTT_PORT    = 1883
TOPIC_STATUS = "device/status"
TOPIC_CMD    = "cmd/text"

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def on_mqtt_message(client, userdata, msg):
    payload = msg.payload.decode("utf-8")
    print(f"[MQTT] Received: {payload}")

    # Parse device status updates from ESP32
    # Format: "LIGHT:ON", "MOTOR:OFF", etc.
    if ":" in payload:
        parts  = payload.split(":")
        device = parts[0].lower()
        status = parts[1].lower()

        # Update DB
        conn = get_db()
        conn.execute("UPDATE devices SET status=? WHERE name=?", (status, device))
        conn.commit()
        conn.close()

        # Push real-time update to dashboard via SocketIO
        socketio.emit("device_update", {"device": device, "status": status})
        print(f"[DB] Updated {device} → {status}")

    elif payload == "AWAKE":
        socketio.emit("system_status", {"status": "awake"})
    elif payload == "SLEEP":
        socketio.emit("system_status", {"status": "sleep"})

def start_mqtt():
    mqtt_client.on_message = on_mqtt_message
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.subscribe(TOPIC_STATUS)
    mqtt_client.loop_forever()

# ════════════════════════════════════════════════════════
# AUTH ROUTES
# ════════════════════════════════════════════════════════
@app.route("/")
@app.route("/dashboard")
def serve_dashboard():
    return send_from_directory(".", "dashboard.html")


@app.route("/api/login", methods=["POST"])
def login():
    data     = request.get_json()
    username = data.get("username", "")
    password = data.get("password", "")
    pw_hash  = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (username, pw_hash)
    ).fetchone()
    conn.close()

    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(identity=username)
    return jsonify({"token": token, "username": username})

# ════════════════════════════════════════════════════════
# DEVICE ROUTES
# ════════════════════════════════════════════════════════

@app.route("/api/devices", methods=["GET"])
@jwt_required()
def get_devices():
    conn    = get_db()
    devices = conn.execute("SELECT * FROM devices").fetchall()
    conn.close()
    return jsonify([dict(d) for d in devices])

@app.route("/api/devices", methods=["POST"])
@jwt_required()
def add_device():
    data = request.get_json()
    name = data.get("name", "").lower().strip()
    pin  = data.get("gpio_pin")

    if not name or not pin:
        return jsonify({"error": "name and gpio_pin required"}), 400

    try:
        conn = get_db()
        conn.execute("INSERT INTO devices (name, gpio_pin, status) VALUES (?,?,?)",
                     (name, pin, "off"))
        conn.commit()
        conn.close()
        return jsonify({"message": f"Device '{name}' added on GPIO {pin}"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Device name already exists"}), 409

@app.route("/api/devices/<int:device_id>", methods=["DELETE"])
@jwt_required()
def delete_device(device_id):
    conn = get_db()
    conn.execute("DELETE FROM commands WHERE device_id=?", (device_id,))
    conn.execute("DELETE FROM devices WHERE id=?", (device_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Device deleted"})

@app.route("/api/devices/<int:device_id>/control", methods=["POST"])
@jwt_required()
def control_device(device_id):
    data   = request.get_json()
    action = data.get("action", "").lower()

    if action not in ["on", "off"]:
        return jsonify({"error": "action must be 'on' or 'off'"}), 400

    conn   = get_db()
    device = conn.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()

    if not device:
        conn.close()
        return jsonify({"error": "Device not found"}), 404

    conn.execute("UPDATE devices SET status=? WHERE id=?", (action, device_id))
    conn.commit()
    conn.close()

    # ESP32 ko seedha command bhejo — format: "motor on" ya "motor off"
    command = f"{device['name']} {action}"
    result  = mqtt_client.publish(TOPIC_CMD, command)
    print(f"[MQTT] Sending to ESP32: '{command}' | result: {result.rc}")

    socketio.emit("device_update", {"device": device["name"], "status": action})
    return jsonify({"message": f"{device['name']} turned {action}"})

# ════════════════════════════════════════════════════════
# COMMAND ROUTES
# ════════════════════════════════════════════════════════

@app.route("/api/commands", methods=["GET"])
@jwt_required()
def get_commands():
    conn     = get_db()
    commands = conn.execute("""
        SELECT c.id, c.phrase, c.action, d.name as device_name, d.gpio_pin
        FROM commands c
        JOIN devices d ON c.device_id = d.id
    """).fetchall()
    conn.close()
    return jsonify([dict(c) for c in commands])

@app.route("/api/commands", methods=["POST"])
@jwt_required()
def add_command():
    data      = request.get_json()
    phrase    = data.get("phrase", "").lower().strip()
    device_id = data.get("device_id")
    action    = data.get("action", "").lower()

    if not phrase or not device_id or action not in ["on", "off"]:
        return jsonify({"error": "phrase, device_id, and action required"}), 400

    try:
        conn = get_db()
        conn.execute("INSERT INTO commands (phrase, device_id, action) VALUES (?,?,?)",
                     (phrase, device_id, action))
        conn.commit()
        conn.close()
        return jsonify({"message": f"Command '{phrase}' added"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Phrase already exists"}), 409

@app.route("/api/commands/<int:cmd_id>", methods=["DELETE"])
@jwt_required()
def delete_command(cmd_id):
    conn = get_db()
    conn.execute("DELETE FROM commands WHERE id=?", (cmd_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "Command deleted"})

# ════════════════════════════════════════════════════════
# SOCKETIO EVENTS
# ════════════════════════════════════════════════════════

@socketio.on("connect")
def on_connect():
    print("[SocketIO] Client connected")
    # Send current device states on connect
    conn    = get_db()
    devices = conn.execute("SELECT * FROM devices").fetchall()
    conn.close()
    emit("all_devices", [dict(d) for d in devices])

@socketio.on("disconnect")
def on_disconnect():
    print("[SocketIO] Client disconnected")

# ─── Main ────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()

    # Start MQTT in background thread
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()
    print("[MQTT] Background thread started")

    print("[Flask] Starting server on http://0.0.0.0:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)

# server.py ke end mein change karo:
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading", ping_timeout=60, ping_interval=25)