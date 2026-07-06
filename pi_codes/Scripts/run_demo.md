# Self-Adaptive For Digital Twins Demo Board (Raspberry Pi + ESP)

This project runs a Raspberry Pi agent for sensors, push buttons, and ESP actuator commands.

## Files

- `agent.py`:
  - Main runtime code.
  - Reads sensors (VEML7700, SI7021, SGP30, PIR).
  - Handles push-button toggles.
  - Sends sensor data + heartbeat to API.
  - Polls pending commands.
  - Pushes actuator command packets to ESP endpoint.

- `test_1.py`:
  - Hardware test script for sensors and push buttons.
  - Prints sensor values and button actions locally.
  - Use this for quick validation before starting service.

- `esp_send.py`:
  - ESP actuator test script.
  - Sends random command packets to test LEDs, strips, buzzer, tube, and fan path.

- `requirements.txt`:
  - Python dependency list for this project.

## Prerequisites

- Raspberry Pi OS/Linux
- Python
- I2C enabled on Pi
- Connected hardware:
  - VEML7700
  - SI7021
  - SGP30
  - PIR + push buttons
  - ESP receiver at configured IP/port in `agent.py`

## Setup

### 1. Create virtual environment

```bash
python -m venv .venv
```

### 2. Activate virtual environment

```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Verify active interpreter

```bash
python --version
which python
```

## Service workflow (important)

If your system service is running, stop it before manual testing. Otherwise, you can get GPIO/I2C conflicts.

### Check service status

```bash
sudo systemctl status demo-agent.service
```

### Stop service before manual run

```bash
sudo systemctl stop demo-agent.service
```

### Start service again after testing

```bash
sudo systemctl start demo-agent.service
```

### Optional: restart service after code/config changes

```bash
sudo systemctl restart demo-agent.service
```

### Optional: service logs

```bash
sudo journalctl -u demo-agent.service -f
```

## Recommended run order

1. Activate venv.
2. Stop `demo-agent.service`.
3. Run `test.py` to verify sensors/buttons.
4. Run `esp_send.py` to verify ESP actuator path.
5. Run `agent.py` for full integration test.
6. Start `demo-agent.service` again for background operation.

## Manual run commands

### Sensor + button test

```bash
source .venv/bin/activate
python test.py
```

### ESP actuator test

```bash
source .venv/bin/activate
python esp_send.py
```

### Main agent run

```bash
source .venv/bin/activate
python agent.py
```

## Notes

- Update API base URL, node ID, ESP IP, and intervals in `agent.py` as needed.
- If I2C sensor reads fail, verify wiring and that I2C is enabled (`sudo raspi-config`).
- Run scripts with a user that has GPIO/I2C permissions (or use `sudo` where required by your setup).

