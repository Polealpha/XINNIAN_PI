#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="/etc/default/emotion-pi"

echo "[install] project root: ${ROOT_DIR}"

APT_SUDO=(sudo)
PIP_ENV=()

if [[ -n "${http_proxy:-}" || -n "${https_proxy:-}" ]]; then
  echo "[install] using proxy http_proxy=${http_proxy:-<unset>} https_proxy=${https_proxy:-<unset>}"
  APT_SUDO=(sudo env "http_proxy=${http_proxy:-}" "https_proxy=${https_proxy:-}" "HTTP_PROXY=${HTTP_PROXY:-${http_proxy:-}}" "HTTPS_PROXY=${HTTPS_PROXY:-${https_proxy:-}}")
  PIP_ENV=("http_proxy=${http_proxy:-}" "https_proxy=${https_proxy:-}" "HTTP_PROXY=${HTTP_PROXY:-${http_proxy:-}}" "HTTPS_PROXY=${HTTPS_PROXY:-${https_proxy:-}}")
fi

pkg_has_candidate() {
  local candidate
  candidate="$(LC_ALL=C apt-cache policy "$1" | awk '/Candidate:/ {print $2; exit}')"
  [[ -n "${candidate}" && "${candidate}" != "(none)" ]]
}

"${APT_SUDO[@]}" apt-get update

packages=(
  python3-venv
  python3-pip
  python3-dev
  python3-opencv
  python3-yaml
  python3-picamera2
  python3-libcamera
  libcamera-apps
  ffmpeg
  espeak-ng
  alsa-utils
  portaudio19-dev
  libsndfile1
  i2c-tools
  python3-gpiozero
  python3-smbus2
  libopenblas-dev
  libjpeg-dev
  libtiff6
  libopenjp2-7
  libgl1
)

optional_packages=(
  libatlas-base-dev
  libglib2.0-0
)

install_list=()
for pkg in "${packages[@]}"; do
  if pkg_has_candidate "${pkg}"; then
    install_list+=("${pkg}")
  else
    echo "[install] skip unavailable package: ${pkg}"
  fi
done

for pkg in "${optional_packages[@]}"; do
  if pkg_has_candidate "${pkg}"; then
    install_list+=("${pkg}")
  else
    echo "[install] optional package not available: ${pkg}"
  fi
done

"${APT_SUDO[@]}" apt-get install -y "${install_list[@]}"

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv --system-site-packages "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
env "${PIP_ENV[@]}" python -m pip install --upgrade pip wheel setuptools
env "${PIP_ENV[@]}" python -m pip install -r "${ROOT_DIR}/requirements-pi.txt"
if [[ -f "${ROOT_DIR}/requirements-pi-optional.txt" ]]; then
  echo "[install] optional python packages are kept separate; install manually when enabling cloud providers or PCA9685 extras."
fi

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
