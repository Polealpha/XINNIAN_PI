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

- Preferred: USB microphone with ALSA support.
- Alternative: I2S microphone only if you are comfortable with Pi overlay configuration.
- Default capture command expects ALSA `default` device:
  `arecord -q -D default -f S16_LE -r 16000 -c 1 -t raw`

### 4. Speaker

- Preferred: USB audio dongle or I2S DAC with ALSA playback.
- Default playback path uses:
  `aplay -q`

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

## Raspberry Pi software setup before connecting motion hardware

- Enable I2C in `raspi-config`.
- Confirm camera stack with `libcamera-hello --list-cameras`.
- Confirm audio devices with `arecord -l` and `aplay -l`.
- Confirm PCA9685 visibility with `i2cdetect -y 1`.
- Confirm onboarding support with `nmcli device status`.

## Suggested config progression

- No hardware yet:
  `PI_RUNTIME_CONFIG=config/pi_zero2w.headless.json`
- Camera + microphone attached:
  `PI_RUNTIME_CONFIG=config/pi_zero2w.json`
- Camera + microphone + dual GPIO pan/tilt:
  duplicate `config/pi_zero2w.json`, switch `"hardware.driver"` to `"gpio"`, then fill pan/tilt GPIO pins
- Camera + microphone + PCA9685 pan/tilt:
  `PI_RUNTIME_CONFIG=config/pi_zero2w.pca9685.example.json`

## First-time owner enrollment

1. Boot the Pi with no saved Wi-Fi and connect to the onboarding hotspot.
2. Call the local onboarding API to join the home Wi-Fi.
3. Sign in through the backend and call `/api/device/claim`.
4. Start enrollment on the Pi with the returned `claim_token`.
5. Keep the owner centered in front of the camera until 8 to 12 samples are captured.
6. The Pi saves the local owner embedding and syncs only enrollment metadata back to the backend.
