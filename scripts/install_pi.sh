#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
ENV_FILE="/etc/default/emotion-pi"
SERVICE_USER="${SUDO_USER:-${USER}}"
SERVICE_GROUP="${SERVICE_USER}"

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

ensure_env_key() {
  local key="$1"
  local value="$2"
  if sudo grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null; then
    return
  fi
  echo "${key}=${value}" | sudo tee -a "${ENV_FILE}" >/dev/null
}

"${APT_SUDO[@]}" apt-get update

packages=(
  python3-venv
  python3-pip
  python3-dev
  python3-opencv
  python3-yaml
  python3-sentencepiece
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
  python3-spidev
  libopenblas-dev
  libjpeg-dev
  libtiff6
  libopenjp2-7
  libgl1
  fonts-noto-cjk
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
if [[ -f "${ROOT_DIR}/scripts/fetch_identity_models.py" ]]; then
  env "${PIP_ENV[@]}" python "${ROOT_DIR}/scripts/fetch_identity_models.py" || echo "[install] skip identity model download"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  sudo tee "${ENV_FILE}" >/dev/null <<'EOF'
PI_RUNTIME_CONFIG=config/pi_zero2w.headless.json
ENGINE_CONFIG_PATH=config/engine_config.json
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
NUMEXPR_NUM_THREADS=1
ARK_API_KEY=
DASHSCOPE_API_KEY=
AUTH_SECRET_KEY=change-this-secret
AUTH_CORS_ORIGINS=*
AUTH_DB_PATH=/var/lib/emotion-pi/auth.db
EOF
fi
ensure_env_key "PI_RUNTIME_CONFIG" "config/pi_zero2w.headless.json"
ensure_env_key "ENGINE_CONFIG_PATH" "config/engine_config.json"
ensure_env_key "OMP_NUM_THREADS" "1"
ensure_env_key "OPENBLAS_NUM_THREADS" "1"
ensure_env_key "NUMEXPR_NUM_THREADS" "1"

sudo install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" /var/lib/emotion-pi
sudo chown -R "${SERVICE_USER}:${SERVICE_GROUP}" /var/lib/emotion-pi
sudo usermod -a -G audio,video,i2c,gpio "${SERVICE_USER}" || true

sed -e "s#__PROJECT_ROOT__#${ROOT_DIR}#g" -e "s#__SERVICE_USER__#${SERVICE_USER}#g" "${ROOT_DIR}/systemd/emotion-pi.service" | sudo tee /etc/systemd/system/emotion-pi.service >/dev/null
sed -e "s#__PROJECT_ROOT__#${ROOT_DIR}#g" -e "s#__SERVICE_USER__#${SERVICE_USER}#g" "${ROOT_DIR}/systemd/emotion-backend.service" | sudo tee /etc/systemd/system/emotion-backend.service >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable emotion-pi.service

echo "[install] completed"
echo "[install] review ${ENV_FILE} for API keys, then start services:"
echo "  sudo systemctl start emotion-pi.service"
echo "  sudo systemctl start emotion-backend.service"
