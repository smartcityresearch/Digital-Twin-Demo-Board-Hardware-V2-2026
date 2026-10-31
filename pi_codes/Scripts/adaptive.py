"""
Self-Adaptive Digital Twin Demo Agent
======================================
Runs on the Raspberry Pi. Reads real sensors, posts telemetry + heartbeat to
the backend, polls for commands, and drives the ESP actuator board.

DEMO MODE: the 7 physical buttons no longer enable/disable sensors directly.
Instead, each button INJECTS A FAULT. A single press kicks off an automatic,
non-blocking sequence: the system tries each of that fault's 3 strategies
exactly once (no repeats — attempt 1 is always the single highest-probability
strategy, the other two follow in random order), then performs one final,
separate resolution step. That resolution step is honest about how things
ended: if the last strategy tried was benign, it's a clear cyan "RESOLVED"
signature; if the last strategy tried was severe (an emergency/critical
fallback), it's narrated and shown as "contained, flagged for operator" —
it never claims success the system didn't actually reach. Every attempt
also drives the fan (escalating 80/150/220) and a buzzer beep pattern
(beep count = attempt number, or a rapid alarm burst for severe strategies)
so fan and buzzer are consistently part of the demo, not occasional extras.
"""

import json
import random
import socket
import time
from datetime import datetime, timezone

import requests
import board
import busio
import RPi.GPIO as GPIO

import adafruit_veml7700
import adafruit_si7021


# ================= CONFIG =================
API_BASE = "https://smartcitylivinglab.iiit.ac.in/smartcitydigitaltwin-api/demo-board"
NODE_ID = 1

ESP_IP = "10.2.203.211"
ESP_PORT = 9001
ESP_URL = f"http://{ESP_IP}:{ESP_PORT}/data"

SENSOR_INTERVAL_SECONDS = 45
HEARTBEAT_INTERVAL_SECONDS = 15
COMMAND_POLL_SECONDS = 5
ESP_SEND_INTERVAL = 5

STEP_DELAY_SECONDS = 2.5  # gap between automatic attempts within one sequence
# Each fault has exactly 3 strategies, so a sequence is always 3 attempts
# (one per strategy, no repeats) + 1 final resolution step = 4 total steps.


# ================= GPIO =================
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

PIR_PIN = 4
CO2_PWM_PIN = 5

# Button -> fault name (demo mapping, not enable/disable anymore)
buttons = {
    12: "Time",
    16: "Sensors",
    20: "Wi-Fi",
    21: "Power",
    6: "Lux",
    13: "Temp",
    19: "CO2",
}

GPIO.setup(PIR_PIN, GPIO.IN)
GPIO.setup(CO2_PWM_PIN, GPIO.IN)

for pin in buttons:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

last_state = {pin: 1 for pin in buttons}
last_pressed_time = {pin: 0 for pin in buttons}
DEBOUNCE_TIME = 0.2


# ================= I2C =================
i2c = busio.I2C(board.SCL, board.SDA)
veml = adafruit_veml7700.VEML7700(i2c)
si7021 = adafruit_si7021.SI7021(i2c)


# ================= FAULT / ADAPTATION STATE =================
# active_sequences[fault_name] = {"attempt": int, "next_time": float}
# presence in this dict means a fault sequence is currently auto-running
active_sequences = {}

# whether the underlying reading should currently be suppressed to
# simulate the failure (only meaningful for CO2 / Temp / Lux / Sensors)
sensor_faulted = {"CO2": False, "Temp": False, "Lux": False}

wifi_faulted = False
power_faulted = False
time_faulted = False

# dynamic intervals (Time fault temporarily increases these)
sensor_interval = SENSOR_INTERVAL_SECONDS
cmd_poll_interval = COMMAND_POLL_SECONDS

adaptation_policies = {
    "CO2": [
        ("restart_sensor", 0.50),
        ("degraded_mode", 0.30),
        ("occupancy_mode", 0.20),
    ],
    "Temp": [
        ("restart_sensor", 0.60),
        ("cached_value", 0.25),
        ("safe_fan_mode", 0.15),
    ],
    "Lux": [
        ("restart_sensor", 0.50),
        ("default_lighting", 0.35),
        ("cached_value", 0.15),
    ],
    "Sensors": [
        ("restart_all", 0.50),
        ("critical_degraded", 0.30),
        ("emergency_fallback", 0.20),
    ],
    "Wi-Fi": [
        ("reconnect", 0.40),
        ("buffer_locally", 0.35),
        ("autonomous_mode", 0.25),
    ],
    "Power": [
        ("disable_fan", 0.40),
        ("disable_tube", 0.30),
        ("minimal_operation", 0.30),
    ],
    "Time": [
        ("increase_intervals", 0.50),
        ("disable_noncritical", 0.30),
        ("edge_only_mode", 0.20),
    ],
}

# Strategies severe enough to keep the buzzer on continuously
SEVERE_SOLUTIONS = {"emergency_fallback", "critical_degraded", "minimal_operation"}

# Strategies where fan=0 IS the point (don't override these for visual flair)
INTENTIONAL_FAN_OFF_SOLUTIONS = {"disable_fan"}

# Fan speed floor per attempt number, applied whenever a strategy's own fan
# value is 0 and it isn't one of the INTENTIONAL_FAN_OFF_SOLUTIONS above —
# keeps the fan visibly doing *something* on every attempt, not just 2 of them
FAN_ESCALATION = {1: 80, 2: 150, 3: 220}
FAN_MAX = 255
FAN_RESOLVED_DEFAULT = 220  # fan level once a fault settles, if strategy left it at 0

BEEP_ON = 0.15
BEEP_OFF = 0.15

# Tube colors (for reference / narration)
COLOR_BLUE = [0, 0, 255]      # restart attempt
COLOR_YELLOW = [255, 255, 0]  # degraded mode
COLOR_GREEN = [0, 255, 0]     # local / occupancy / autonomous mode
COLOR_RED = [255, 0, 0]       # critical / emergency
COLOR_PURPLE = [128, 0, 255]  # safe mode
COLOR_CYAN = [0, 255, 255]    # recovery successful
COLOR_WHITE = [255, 255, 255]
COLOR_OFF = [0, 0, 0]

# Faults where the fan must stay off no matter what — overrides the
# fan-escalation floor and the resolution/severe fan boosts entirely.
NO_FAN_FAULTS = {"Lux"}


# ================= CO2 PWM =================
def read_co2_ppm(timeout=2.0):
    try:
        start = time.time()
        while GPIO.input(CO2_PWM_PIN) == 0:
            if time.time() - start > timeout:
                return None
        t1 = time.perf_counter()
        while GPIO.input(CO2_PWM_PIN) == 1:
            pass
        t2 = time.perf_counter()
        while GPIO.input(CO2_PWM_PIN) == 0:
            pass
        t3 = time.perf_counter()
        high_ms = (t2 - t1) * 1000
        period_ms = (t3 - t1) * 1000
        if period_ms <= 4:
            return None
        ppm = 10000 * (high_ms - 2) / (period_ms - 4)
        ppm = max(0, min(10000, ppm))
        return round(ppm)
    except Exception:
        return None


# ================= PIR WINDOW =================
pir_history = []
PIR_WINDOW = 30


def get_pir_majority():
    global pir_history
    now = time.time()
    val = 1 if GPIO.input(PIR_PIN) else 0

    pir_history.append((now, val))
    pir_history = [(t, v) for (t, v) in pir_history if now - t <= PIR_WINDOW]

    ones = sum(v for (_, v) in pir_history)
    zeros = len(pir_history) - ones
    return 1 if ones > zeros else 0


# ================= HELPERS =================
def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "0.0.0.0"


def fmt(val):
    return "NaN" if val is None else round(val, 2)


# ================= ESP =================
esp_queue = []
last_esp_send = 0


def send_esp_command(cmd, immediate=False):
    """immediate=True bypasses the periodic queue so fault reactions feel instant."""
    try:
        payload = {"cmd": cmd}
        r = requests.post(ESP_URL, json=payload, timeout=2)
        tag = "IMMEDIATE" if immediate else "QUEUED"
        print(f"ESP[{tag}]:", cmd, "|", r.status_code)
    except Exception as e:
        print("ESP Error:", e)


def build_normal_esp_command(readings):
    """The routine, non-fault ESP state reflecting current sensor readings."""
    strip1 = 1 if readings["gas"] else 0
    led1 = 0 if sensor_faulted["CO2"] else 1

    strip2 = 1 if readings["temperature"] else 0
    led2 = 0 if sensor_faulted["Temp"] else 1

    strip3 = 1 if readings["lux"] else 0
    led3 = 0 if sensor_faulted["Lux"] else 1

    strip4 = 1 if readings["pir"] else 0
    led4 = 1

    fan = 0
    buzzer = 0
    if power_faulted:
        fan = 0
        buzzer = 0

    return [
        strip1, led1,
        strip2, led2,
        strip3, led3,
        strip4, led4,
        buzzer,
        0,
        COLOR_OFF,
        fan,
    ]


# ================= ADAPTATION ENGINE =================
def top_solution(fault_name):
    """The single highest-probability strategy — used for attempt 1 so the
    'most likely' response is what visitors reliably see first."""
    return max(adaptation_policies[fault_name], key=lambda s: s[1])[0]


def esp_cmd_for_solution(fault_name, solution):
    """Returns (esp_command, narration) for a chosen strategy."""

    if fault_name == "CO2":
        if solution == "restart_sensor":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_BLUE, 0],
                     "Attempting to restart the CO2 subsystem.")
        if solution == "degraded_mode":
            return ([0, 0, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_YELLOW, 0],
                     "Operating without CO2 sensing (degraded mode).")
        if solution == "occupancy_mode":
            return ([0, 0, 0, 0, 0, 0, 1, 1, 0, 1, COLOR_GREEN, 100],
                     "Switching to occupancy-driven ventilation.")

    if fault_name == "Temp":
        if solution == "restart_sensor":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_BLUE, 0],
                     "Attempting to restart the temperature sensor.")
        if solution == "cached_value":
            return ([1, 1, 0, 0, 1, 1, 1, 1, 0, 1, COLOR_PURPLE, 0],
                     "Falling back to the last known temperature value.")
        if solution == "safe_fan_mode":
            return ([1, 1, 0, 0, 1, 1, 1, 1, 0, 1, [255, 128, 0], 100],
                     "Activating safe fan mode as a precaution.")

    if fault_name == "Lux":
        if solution == "restart_sensor":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_BLUE, 0],
                     "Attempting to restart the lux sensor.")
        if solution == "default_lighting":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_WHITE, 0],
                     "Falling back to default lighting policy (all sensors lit, white).")
        if solution == "cached_value":
            return ([1, 1, 1, 1, 0, 0, 1, 1, 0, 1, COLOR_PURPLE, 0],
                     "Using the last cached lux reading.")

    if fault_name == "Sensors":
        if solution == "restart_all":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_BLUE, 0],
                     "Attempting to restart all environmental sensors.")
        if solution == "critical_degraded":
            return ([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, COLOR_YELLOW, 0],
                     "Multiple sensors down: entering critical degraded mode.")
        if solution == "emergency_fallback":
            return ([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, COLOR_RED, 255],
                     "Emergency fallback: PIR-only operation, alerting operator.")

    if fault_name == "Wi-Fi":
        if solution == "reconnect":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_BLUE, 0],
                     "Attempting to reconnect to the network.")
        if solution == "buffer_locally":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_YELLOW, 0],
                     "Cloud unavailable: buffering data locally.")
        if solution == "autonomous_mode":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_GREEN, 0],
                     "Operating in disconnected, autonomous mode.")

    if fault_name == "Power":
        if solution == "disable_fan":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_PURPLE, 0],
                     "Power constrained: disabling fan.")
        if solution == "disable_tube":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 0, COLOR_OFF, 0],
                     "Power constrained: disabling tube lighting.")
        if solution == "minimal_operation":
            return ([1, 0, 0, 0, 0, 0, 1, 1, 0, 1, COLOR_PURPLE, 0],
                     "Entering minimal-operation power-saving mode.")

    if fault_name == "Time":
        if solution == "increase_intervals":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_YELLOW, 0],
                     "Scheduler overloaded: increasing polling intervals.")
        if solution == "disable_noncritical":
            return ([1, 1, 0, 0, 0, 0, 1, 1, 0, 1, COLOR_YELLOW, 0],
                     "Disabling non-critical sensing to reduce load.")
        if solution == "edge_only_mode":
            return ([1, 1, 1, 1, 1, 1, 1, 1, 0, 1, COLOR_GREEN, 0],
                     "Switching to edge-only mode (no cloud round trips).")

    # fallback, should not happen
    return ([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, COLOR_OFF, 0], "Unknown adaptation.")


def apply_side_effects(fault_name, solution, resolved):
    """Update global fault flags/intervals based on the chosen strategy."""
    global wifi_faulted, power_faulted, time_faulted
    global sensor_interval, cmd_poll_interval

    if fault_name in sensor_faulted:
        sensor_faulted[fault_name] = not resolved

    if fault_name == "Sensors":
        for k in sensor_faulted:
            sensor_faulted[k] = not resolved

    if fault_name == "Wi-Fi":
        wifi_faulted = not resolved

    if fault_name == "Power":
        power_faulted = not resolved

    if fault_name == "Time":
        time_faulted = not resolved
        if not resolved and solution == "increase_intervals":
            sensor_interval = SENSOR_INTERVAL_SECONDS * 2
            cmd_poll_interval = COMMAND_POLL_SECONDS * 2
        if resolved:
            sensor_interval = SENSOR_INTERVAL_SECONDS
            cmd_poll_interval = COMMAND_POLL_SECONDS


def choose_shuffled_order(fault_name):
    """Builds this sequence's attempt order: attempt 1 is always the
    deterministic top-probability strategy; the remaining strategies follow
    in random order with NO repeats, so every attempt in a run shows the
    audience something genuinely different."""
    top = top_solution(fault_name)
    rest = [s[0] for s in adaptation_policies[fault_name] if s[0] != top]
    random.shuffle(rest)
    return [top] + rest


def _beep(cmd, count, on_time=BEEP_ON, off_time=BEEP_OFF):
    """Fires `count` short buzzer pulses (all other fields held from cmd)."""
    on = list(cmd); on[8] = 1
    off = list(cmd); off[8] = 0
    for _ in range(count):
        send_esp_command(on, immediate=True)
        time.sleep(on_time)
        send_esp_command(off, immediate=True)
        time.sleep(off_time)


def send_attempt_effect(fault_name, cmd, step, solution):
    """Sends one (non-final) attempt: fan floor escalates with step number,
    buzzer beeps `step` times, severe strategies get a rapid alarm burst
    with the buzzer left on. This never decides resolution — that's handled
    as a completely separate step so it can never contradict what's shown
    here."""
    cmd = list(cmd)

    if cmd[11] == 0 and solution not in INTENTIONAL_FAN_OFF_SOLUTIONS:
        cmd[11] = FAN_ESCALATION.get(step, FAN_MAX)

    if solution in SEVERE_SOLUTIONS:
        cmd[11] = FAN_MAX
        if fault_name in NO_FAN_FAULTS:
            cmd[11] = 0
        _beep(cmd, count=5, on_time=0.1, off_time=0.1)
        cmd[8] = 1
        send_esp_command(cmd, immediate=True)
        return

    if fault_name in NO_FAN_FAULTS:
        cmd[11] = 0

    _beep(cmd, count=step)
    cmd[8] = 0
    send_esp_command(cmd, immediate=True)


def send_resolution_effect(fault_name, last_solution):
    """The final step of every sequence. Always visually/audibly distinct
    from a mid-sequence attempt, and its meaning depends honestly on how
    the sequence ended:
      - last strategy was benign  -> triumphant cyan flourish, 'RESOLVED'
      - last strategy was severe  -> buzzer quiets to a slow double-beep,
        board stays in its elevated state, narrated as 'contained, flagged
        for operator' — never claims success it didn't achieve.
    Either way the fault is cleared from active_sequences and telemetry
    resumes, so the demo doesn't get stuck."""
    cmd, _ = esp_cmd_for_solution(fault_name, last_solution)
    cmd = list(cmd)

    if last_solution in SEVERE_SOLUTIONS:
        print(f"    -> Fault '{fault_name}' CONTAINED (elevated) after last "
              f"trying '{last_solution}'. Still flagged for operator attention.")
        cmd[8] = 0  # stop the continuous siren
        if fault_name in NO_FAN_FAULTS:
            cmd[11] = 0
        send_esp_command(cmd, immediate=True)
        _beep(cmd, count=2, on_time=0.3, off_time=0.3)  # slow "still watching" beep
    else:
        print(f"    -> Fault '{fault_name}' RESOLVED — settled on '{last_solution}'.")
        cmd[9] = 1
        cmd[10] = COLOR_CYAN
        cmd[11] = 0 if fault_name in NO_FAN_FAULTS else FAN_MAX
        _beep(cmd, count=3, on_time=0.12, off_time=0.12)
        on = list(cmd); on[8] = 1
        send_esp_command(on, immediate=True)
        time.sleep(0.4)
        cmd[8] = 0
        if fault_name not in NO_FAN_FAULTS:
            cmd[11] = FAN_RESOLVED_DEFAULT if cmd[11] == 0 else cmd[11]
        send_esp_command(cmd, immediate=True)


def run_fault_step(fault_name):
    """Executes exactly one step of a fault's sequence: either the next
    strategy attempt, or — once every strategy has been tried once — the
    single, separate resolution step."""
    seq = active_sequences[fault_name]
    order = seq["order"]
    step = seq["step"] + 1
    total_steps = len(order) + 1  # +1 for the resolution step

    if step <= len(order):
        solution = order[step - 1]
        print(f"\n*** FAULT: {fault_name} | Attempt {step}/{total_steps} "
              f"| Strategy: {solution} ***")
        cmd, narration = esp_cmd_for_solution(fault_name, solution)
        print(f"    -> {narration}")

        send_attempt_effect(fault_name, cmd, step, solution)
        apply_side_effects(fault_name, solution, resolved=False)

        seq["step"] = step
        seq["last_solution"] = solution
        seq["next_time"] = time.time() + STEP_DELAY_SECONDS
    else:
        print(f"\n*** FAULT: {fault_name} | Resolution ***")
        last_solution = seq["last_solution"]
        send_resolution_effect(fault_name, last_solution)
        apply_side_effects(fault_name, last_solution, resolved=True)
        del active_sequences[fault_name]


def start_fault_sequence(fault_name):
    """Called when a fault button is pressed. Kicks off (or restarts) an
    automatic sequence that tries every strategy exactly once, then resolves
    — no repeated presses, and no repeated strategies within a run."""
    active_sequences[fault_name] = {
        "order": choose_shuffled_order(fault_name),
        "step": 0,
        "last_solution": None,
        "next_time": 0,
    }
    run_fault_step(fault_name)  # fire attempt 1 immediately


def process_fault_sequences():
    """Advances any in-progress fault sequences whose next step is due.
    Non-blocking: called every main-loop tick alongside sensor/heartbeat polling."""
    now = time.time()
    for fault_name in list(active_sequences.keys()):
        if now >= active_sequences[fault_name]["next_time"]:
            run_fault_step(fault_name)


# ================= SENSOR =================
def read_sensors():
    lux = None if sensor_faulted["Lux"] else veml.light
    temp = None if sensor_faulted["Temp"] else si7021.temperature
    gas = None if sensor_faulted["CO2"] else read_co2_ppm()
    pir = get_pir_majority()

    return {"temperature": temp, "lux": lux, "gas": gas, "pir": pir}


# ================= BUTTON =================
def handle_buttons():
    now = time.time()

    for pin, name in buttons.items():
        state = GPIO.input(pin)

        if last_state[pin] == 1 and state == 0:
            if now - last_pressed_time[pin] > DEBOUNCE_TIME:
                start_fault_sequence(name)
                last_pressed_time[pin] = now

        last_state[pin] = state


# ================= API =================
def post_sensor_data():
    global esp_queue

    readings = read_sensors()

    print("\n===== SENSOR DATA =====")
    for k, v in readings.items():
        print(f"{k}: {fmt(v)}")
    print("=======================\n")

    payload = {
        "node_id": NODE_ID,
        "sensor_type": "environmental",
        "readings": readings,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metadata": {"source": "raspberry_pi_agent"},
    }

    if wifi_faulted:
        print("POST skipped: Wi-Fi fault active, buffering locally.")
    else:
        try:
            r = requests.post(f"{API_BASE}/receive-sensor-data", json=payload, timeout=5)
            print("POST:", r.status_code)
        except Exception as e:
            print("POST Error:", e)

    esp_queue.append(build_normal_esp_command(readings))


def post_heartbeat():
    if wifi_faulted:
        print("Heartbeat skipped: Wi-Fi fault active.")
        return

    payload = {
        "node_id": NODE_ID,
        "ip_address": get_local_ip(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    try:
        r = requests.post(f"{API_BASE}/node-heartbeat", json=payload, timeout=5)
        print("Heartbeat:", r.status_code)
    except Exception:
        pass


def poll_commands():
    if wifi_faulted:
        return
    try:
        r = requests.get(f"{API_BASE}/commands/{NODE_ID}?status=pending", timeout=5)
        data = r.json()
        for cmd in data.get("commands", []):
            requests.post(
                f"{API_BASE}/commands/{cmd['id']}/ack",
                json={"status": "executed", "response_message": "OK"},
                timeout=5,
            )
            print("ACK:", cmd["id"])
    except Exception:
        pass


# ================= MAIN =================
def main():
    global last_esp_send

    print("Self-adaptive demo agent started")

    next_sensor = 0
    next_hb = 0
    next_cmd = 0

    while True:
        now = time.time()

        try:
            handle_buttons()
            process_fault_sequences()

            if now >= next_sensor:
                post_sensor_data()
                next_sensor = now + sensor_interval

            if now >= next_hb:
                post_heartbeat()
                next_hb = now + HEARTBEAT_INTERVAL_SECONDS

            if now >= next_cmd:
                poll_commands()
                next_cmd = now + cmd_poll_interval

            if now - last_esp_send >= ESP_SEND_INTERVAL:
                if len(esp_queue) > 0:
                    cmd = esp_queue.pop(0)
                    send_esp_command(cmd)
                    last_esp_send = now

        except Exception as e:
            print("Error:", e)

        time.sleep(0.1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        GPIO.cleanup()
