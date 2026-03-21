# Raspberry Pi Zero 2 W Hardware Wiring

This document describes the recommended hardware layout for the Pi-first robot build.

## Baseline bring-up order

1. Pi Zero 2 W only, no external hardware.
2. Add network and verify `emotion-pi.service`.
3. Add microphone.
4. Add speaker.
5. Add camera.
6. Add the two head servos.
7. If needed later, switch those two channels from direct GPIO to PCA9685.

## Recommended connections

### 1. Power

- Pi Zero 2 W power: stable 5V / 2.5A supply on the Pi power input.
- Servo power: separate regulated 5V supply.
- Grounds must be common between Pi, PCA9685 and servo power supply.
- Do not rely on the Pi 5V rail to drive multiple servos.

### 2. Camera

- Preferred: Raspberry Pi camera over CSI.
- Pi Zero 2 W uses the smaller CSI connector, so a Zero-compatible camera cable is required.
- Software path: `picamera2` / `libcamera`.
- Config file after camera is attached: `config/pi_zero2w.json`.

### 3. Microphone

- Preferred Pi v1: I2S microphone, because the original ESP32-S3 build was also on an I2S audio path.
- Recommended modules:
  - `INMP441` if you want the lightest BOM
  - `ICS-43434` if you want a cleaner digital MEMS option
- Recommended Pi wiring for an I2S microphone:
  - `GPIO18 / PCM_CLK` -> mic `SCK`
  - `GPIO19 / PCM_FS` -> mic `WS/LRCL`
  - `GPIO20 / PCM_DIN` -> mic `SD`
  - `3V3` -> mic `VDD`
  - `GND` -> mic `GND`
- If you want the fastest bring-up instead of the cleanest embedded path, a USB microphone is still acceptable.
- Default capture command expects ALSA `default` device:
  `arecord -q -D default -f S16_LE -r 16000 -c 1 -t raw`

### 4. Speaker

- Preferred Pi v1: I2S DAC / amp, not cloud TTS and not browser audio.
- Recommended modules:
  - `MAX98357A` for a simple mono I2S amp path
  - `WM8960` audio HAT if you want a more integrated codec route
- Recommended `MAX98357A` wiring:
  - `GPIO18 / PCM_CLK` -> `BCLK`
  - `GPIO19 / PCM_FS` -> `LRC`
  - `GPIO21 / PCM_DOUT` -> `DIN`
  - `5V` -> `VIN`
  - `GND` -> `GND`
  - speaker -> `SPK+ / SPK-`
- Default playback path uses:
  `aplay -q`

### 4.1 Original ESP audio direction reference

The old ESP32-S3 version in `emotion engine/XINNIAN` clearly used an I2S microphone + I2S amp path rather than pure USB audio:

- microphone side in `src/main.cpp`
  - `I2S_BCLK_PIN = 41`
  - `I2S_WS_PIN = 42`
  - `I2S_SD_PIN = 40`
- amplifier side in `platformio.ini`
  - `AMP_BCLK_PIN = 19`
  - `AMP_LRCLK_PIN = 20`
  - `AMP_DIN_PIN = 14`

The exact module vendor name is not written clearly in the old firmware files, so the Pi rewrite standardizes on the same I2S architecture and recommends the concrete modules above.

### 5. Status LED

- Suggested GPIO: BCM17, physical pin 11.
- Wiring:
  - GPIO17 -> 220 ohm resistor -> LED anode
  - LED cathode -> GND
- Example config field:
  `"status_led_gpio": 17`

### 6. Dual GPIO head servos

Recommended v1 layout for the two-axis head:

- Pan servo signal: BCM12, physical pin 32
- Tilt servo signal: BCM13, physical pin 33
- Servo V+ from an external 5V rail
- Servo GND tied to Pi GND

Example direct-GPIO config pattern:

```json
"hardware": {
  "driver": "gpio",
  "pan_servo": {
    "enabled": true,
    "gpio_pin": 12
  },
  "tilt_servo": {
    "enabled": true,
    "gpio_pin": 13
  }
}
```

### 7. PCA9685 fallback option

- Pi physical pin 1 (3V3) -> PCA9685 VCC
- Pi physical pin 3 (GPIO2 / SDA) -> PCA9685 SDA
- Pi physical pin 5 (GPIO3 / SCL) -> PCA9685 SCL
- Pi physical pin 6 (GND) -> PCA9685 GND
- External 5V servo supply -> PCA9685 V+ and GND
- Keep OE tied low unless you need explicit hardware disable.
- Default I2C address: `0x40`
- Example fallback config: `config/pi_zero2w.pca9685.example.json`

### 8. Pan and tilt servo via PCA9685

- Connect the servo signal wire to PCA9685 channel 0 for the provided example config.
- Connect the tilt servo signal wire to PCA9685 channel 1.
- Servo V+ goes to the external servo 5V rail, not Pi 3V3.
- Servo GND must be common with Pi GND.
- Reference config: `config/pi_zero2w.pca9685.example.json`

### 9. Physical buttons

Recommended first button layout:

- Power toggle button: BCM5, physical pin 29
- Shutdown button: BCM6, physical pin 31
- Settings button: BCM23, physical pin 16
- All three buttons share GND

Recommended wiring style:

- One side of the momentary button -> target GPIO
- The other side -> GND
- Keep the software `pull_up` setting enabled

Current software behavior:

- Power toggle button:
  - toggles the local Pi UI `screen_awake` state
  - emits `PowerToggleRequested`
- Shutdown button:
  - emits `ShutdownRequested`
  - if `buttons.allow_system_power_commands=true`, the Pi may execute `sudo shutdown -h now`
- Settings button:
  - switches the Pi UI from `expression` to `settings`
  - emits `SettingsPageOpened`
  - the desktop app listens to the same event and automatically opens its Settings tab

Current config block:

```json
"buttons": {
  "enabled": true,
  "allow_system_power_commands": false,
  "power_toggle": { "enabled": true, "gpio_pin": 5, "pull_up": true },
  "shutdown": { "enabled": true, "gpio_pin": 6, "pull_up": true },
  "settings": { "enabled": true, "gpio_pin": 23, "pull_up": true }
},
"ui": {
  "default_page": "expression",
  "settings_auto_return_sec": 0
}
```

### 10. Settings flow

The current end-to-end settings loop is:

1. Press the physical `settings` button on the Pi.
2. Pi runtime switches local UI state to `settings`.
3. Pi runtime emits `SettingsPageOpened`.
4. Backend forwards that event over the event stream.
5. Desktop app automatically jumps to the Settings tab.
6. User edits settings with mouse on desktop.
7. Desktop saves through `/api/device/settings`.
8. Backend persists the settings and queues `settings_apply`.
9. Pi pulls `settings_apply`, applies the new settings live, and updates local UI/status.
10. When the desktop user clicks close, backend queues `settings_page_close`, and the Pi UI returns to `expression`.

## Raspberry Pi software setup before connecting motion hardware

- Enable I2C in `raspi-config`.
- Enable I2S / audio overlays if you are using `INMP441`, `MAX98357A`, `WM8960` or similar modules.
- Confirm camera stack with `libcamera-hello --list-cameras`.
- Confirm audio devices with `arecord -l` and `aplay -l`.
- Confirm PCA9685 visibility with `i2cdetect -y 1`.
- Confirm onboarding support with `nmcli device status`.

## Local voice runtime target

- TTS is now planned as local-only on Pi:
  - preferred: `Piper`
  - fallback: `pyttsx3`
- ASR is now planned as local-only on Pi:
  - preferred: `sherpa-onnx`
  - fallback: bundled `vosk`
- Runtime control endpoints:
  - `GET /voice/status`
  - `POST /voice/session/start`
  - `POST /voice/session/stop`
  - `POST /voice/tts/warmup`

## Suggested config progression

- No hardware yet:
  `PI_RUNTIME_CONFIG=config/pi_zero2w.headless.json`
- Camera + microphone attached:
  `PI_RUNTIME_CONFIG=config/pi_zero2w.json`
- Camera + microphone + dual GPIO pan/tilt:
  duplicate `config/pi_zero2w.json`, switch `"hardware.driver"` to `"gpio"`, then fill pan/tilt GPIO pins
- Camera + microphone + PCA9685 pan/tilt:
  `PI_RUNTIME_CONFIG=config/pi_zero2w.pca9685.example.json`

## Expression display path

- The original ESP expression catalog has been migrated to the Pi runtime as a parametric eye-expression surface.
- Current default display backend:
  - `ui.display_driver = "web"`
  - local rendered face page: `GET /ui`
  - raw expression frame: `GET /expression/frame.svg`
- This keeps the original expression logic and animation model while avoiding hard-coding a specific Pi display controller before the exact panel model is finalized.
- When you later settle on the physical panel, the next step is only to map this already-migrated surface onto that panel's final display backend.

## First-time owner enrollment

1. Boot the Pi with no saved Wi-Fi and connect to the onboarding hotspot.
2. Call the local onboarding API to join the home Wi-Fi.
3. Sign in through the backend and call `/api/device/claim`.
4. Start enrollment on the Pi with the returned `claim_token`.
5. Keep the owner centered in front of the camera until 8 to 12 samples are captured.
6. The Pi saves the local owner embedding and syncs only enrollment metadata back to the backend.
