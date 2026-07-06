# Pinout Reference (ESP32 & Raspberry Pi)

## ESP32 Pinout

### LED Pins (Strips)

| Function | LED Pin | Strip Pin |
|----------|---------|-----------|
| CO2      | 4       | 14        |
| PIR      | 17      | 27        |
| Lux      | 5       | 26        |
| Temp     | 16      | 25        |

### Actuators

| Actuator | Pin |
|----------|-----|
| Light    | 19  |
| Buzzer   | 18  |
| Fan      | 33  |

---

## Raspberry Pi Pinout

### Sensor Push Buttons

| Button      | GPIO Pin |
|-------------|----------|
| CO2 Button  | 19       |  
| Temp Button | 13       |
| Lux Button  | 6        |
| PIR         | Manual switch |

### Sensor Pins (Lux, Co2, Temp)

| Signal | GPIO Pin |
|--------|----------|
| SDA    | 2        |
| SCL    | 3        |
| PIR    | 4        |
| Co2    | 5        |

### Scenario Push Buttons

| Button   | GPIO Pin |
|----------|----------|
| Time     | 12       |
| Wi-Fi    | 20       |
| Sensors  | 16       |
| Power    | 21       |

---

> **Tip:** Keep this file as a backup for hardware wiring and quick reference for ESP32 and Raspberry Pi connections.
