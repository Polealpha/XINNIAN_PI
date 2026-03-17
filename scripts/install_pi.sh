#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="/etc/default/emotion-pi"

echo "[install] project root: ${ROOT_DIR}"

sudo apt-get update
sudo apt-get install -y \
  python3-venv \
  python3-pip \
  python3-dev \
  python3-picamera2 \
  python3-libcamera \
  libcamera-apps \
  ffmpeg \
  alsa-utils \
  portaudio19-dev \
  libsndfile1 \
  i2c-tools \
  python3-gpiozero \
  python3-smbus2 \
  libatlas-base-dev \
  libopenblas-dev \
  libjpeg-dev \
  libtiff6 \
  libopenjp2-7 \
  libglib2.0-0 \
  libgl1

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r "${ROOT_DIR}/requirements-pi.txt"

if [[ ! -f "${ENV_FILE}" ]]; then
  sudo tee "${ENV_FILE}" >/dev/null <<'EOF'
ARK_API_KEY=
DASHSCOPE_API_KEY=
AUTH_SECRET_KEY=change-this-secret
AUTH_CORS_ORIGINS=*
AUTH_DB_PATH=/var/lib/emotion-pi/auth.db
EOF
fi

sudo install -d /var/lib/emotion-pi

sed "s#__PROJECT_ROOT__#${ROOT_DIR}#g" "${ROOT_DIR}/systemd/emotion-pi.service" | sudo tee /etc/systemd/system/emotion-pi.service >/dev/null
sed "s#__PROJECT_ROOT__#${ROOT_DIR}#g" "${ROOT_DIR}/systemd/emotion-backend.service" | sudo tee /etc/systemd/system/emotion-backend.service >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable emotion-pi.service

echo "[install] completed"
echo "[install] review ${ENV_FILE} for API keys, then start services:"
echo "  sudo systemctl start emotion-pi.service"
echo "  sudo systemctl start emotion-backend.service"
