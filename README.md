# Self-Adaptive Digital Twin Demo Board

This repository contains the Raspberry Pi, ESP, and XR pieces used for the demo board.

## Main folders

- `Board_pinout` - wiring reference for the Raspberry Pi and ESP board connections.
- `esp_code/esp_code.ino` - ESP code used for the demo board actuators.
- `pi_codes/pi_setup/` - Pi setup scripts for switching between minimal mode and full mode.
- `pi_codes/Scripts/` - Python scripts for running and testing the Pi side of the demo.
- `pi_codes/XR_DT/` - files for linking the XR demo with this digital twin.

## Pi scripts

The main Pi scripts are in `pi_codes/Scripts/`:

- `agent.py` - main runtime script for sensor reading, button handling, API updates, and ESP control.
- `test_1.py` - local test script for sensors and push buttons.
- `esp_send.py` - test script for sending actuator commands to the ESP path.
- `requirements.txt` - Python dependencies for the Pi scripts.
- `run_demo.md` - Readme filw which tell how to run the scripts for starting the demo board.

## Pi setup

The `pi_codes/pi_setup/` folder is for making the Pi setup minimal or full, depending on how much background service usage you want.

- `mode_switch.sh` - switch between minimal mode and full mode.
- `PI_SETUP.md` - setup notes and usage for the mode switch script.

## XR integration

The `pi_codes/XR_DT/` folder contains the XR-related server and support files used to link XR with this digital twin.

## Basic run order

1. Check the pinout in `Board_pinout`.
2. Use the ESP code from `esp_code/`.
3. Set up the Pi with `pi_codes/pi_setup/` if you want minimal mode.
4. Install dependencies from `pi_codes/Scripts/requirements.txt`.
5. Run `test_1.py` and `esp_send.py` to verify hardware.
6. Run `agent.py` for the full demo workflow.

