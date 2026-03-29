const os = require("os");
const path = require("path");
const fs = require("fs");
const { spawn, spawnSync, execFile } = require("child_process");
const { app } = require("electron");

const DEFAULT_API_BASE = "http://39.97.33.236:8000";
const POLL_INTERVAL_MS = 15000;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const safeFetchJson = async (url, init) => {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(`${init?.method || "GET"} ${url} failed: ${response.status}`);
  }
  return response.json();
};

const resolveRuntimeRoot = () => {
  if (process.env.EMOTION_BRIDGE_ROOT) {
    return process.env.EMOTION_BRIDGE_ROOT;
  }
  if (!app.isPackaged) {
    return path.resolve(__dirname, "..", "..");
  }
  return path.join(process.resourcesPath, "bridge-runtime");
};

const commandExists = (command) => {
  try {
    const probe = process.platform === "win32" ? ["cmd", ["/c", "where", command]] : ["which", [command]];
    const result = spawnSync(probe[0], probe[1], { stdio: "ignore" });
    return result.status === 0;
  } catch {
    return false;
  }
};

const resolvePythonCommand = (runtimeRoot) => {
  if (process.env.EMOTION_BRIDGE_PYTHON) {
    return { command: process.env.EMOTION_BRIDGE_PYTHON, args: [] };
  }
  const venvPython = process.platform === "win32"
    ? path.join(runtimeRoot, ".venv", "Scripts", "python.exe")
    : path.join(runtimeRoot, ".venv", "bin", "python");
  if (fs.existsSync(venvPython)) {
    return { command: venvPython, args: [] };
  }
  if (process.platform === "win32" && commandExists("py")) {
    return { command: "py", args: ["-3"] };
  }
  if (commandExists("python")) {
    return { command: "python", args: [] };
  }
  if (commandExists("python3")) {
    return { command: "python3", args: [] };
  }
  return null;
};

const getLocalIpv4 = () => {
  const interfaces = os.networkInterfaces();
  for (const list of Object.values(interfaces)) {
    for (const item of list || []) {
      if (item && item.family === "IPv4" && !item.internal) {
        return item.address;
      }
    }
  }
  return "";
};

const getWindowsWifiSsid = () =>
  new Promise((resolve) => {
    if (process.platform !== "win32") {
      resolve("");
      return;
    }
    execFile(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        "$out = netsh wlan show interfaces | Out-String; " +
          "$m = [regex]::Match($out, '(?m)^\\s*SSID\\s*:\\s*(.+)$'); " +
          "if ($m.Success) { $m.Groups[1].Value.Trim() }",
      ],
      { windowsHide: true, timeout: 4000 },
      (_err, stdout) => resolve(String(stdout || "").trim())
    );
  });

class DeviceSyncManager {
  constructor(options = {}) {
    this.onStatus = typeof options.onStatus === "function" ? options.onStatus : () => {};
    this.runtimeRoot = resolveRuntimeRoot();
    this.session = null;
    this.pollTimer = null;
    this.running = false;
    this.bridgeProc = null;
    this.bridgeDeviceIp = "";
    this.bridgeStdout = "";
    this.bridgeStderr = "";
  }

  async setSession(session) {
    this.session = {
      apiBase: String(session?.apiBase || DEFAULT_API_BASE).replace(/\/+$/, ""),
      token: String(session?.token || "").trim(),
      clientId: String(session?.clientId || `desktop-${os.hostname()}`).trim(),
      deviceId: String(session?.deviceId || "").trim(),
    };
    if (!this.session.token) {
      return;
    }
    await this._tick();
    this._startPolling();
  }

  async clearSession() {
    const previous = this.session;
    this.session = null;
    this._stopPolling();
    if (previous?.token) {
      try {
        await this._sendClientHeartbeat(previous, false);
      } catch {}
    }
    this._stopBridge();
  }

  dispose() {
    this._stopPolling();
    this._stopBridge();
    this.session = null;
  }

  _startPolling() {
    this._stopPolling();
    this.pollTimer = setInterval(() => {
      this._tick().catch((err) => {
        this.onStatus({ ok: false, error: String(err?.message || err || "tick failed") });
      });
    }, POLL_INTERVAL_MS);
  }

  _stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  async _sendClientHeartbeat(session, isActive) {
    const [ssid, clientIp] = await Promise.all([getWindowsWifiSsid(), Promise.resolve(getLocalIpv4())]);
    return safeFetchJson(`${session.apiBase}/api/client/session/heartbeat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify({
        client_type: "desktop",
        client_id: session.clientId,
        current_ssid: ssid || undefined,
        client_ip: clientIp || undefined,
        device_id: session.deviceId || undefined,
        is_active: isActive,
      }),
    });
  }

  async _fetchDeviceStatus(session) {
    const params = new URLSearchParams();
    if (session.deviceId) params.set("device_id", session.deviceId);
    const query = params.toString();
    return safeFetchJson(`${session.apiBase}/api/device/status${query ? `?${query}` : ""}`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${session.token}`,
      },
    });
  }

  async _tick() {
    const session = this.session;
    if (!session?.token) return;
    const heartbeat = await this._sendClientHeartbeat(session, true).catch((err) => ({
      ok: false,
      error: String(err?.message || err || "heartbeat failed"),
    }));
    const status = await this._fetchDeviceStatus(session);
    if (status?.device_id && !session.deviceId) {
      this.session.deviceId = String(status.device_id);
    }
    if (status?.online && status?.device_ip) {
      this._ensureBridge(String(status.device_ip), session.apiBase);
    } else {
      this._stopBridge();
    }
    this.onStatus({
      ok: true,
      heartbeat,
      deviceStatus: status,
      bridgeDeviceIp: this.bridgeDeviceIp || null,
      bridgeRunning: Boolean(this.bridgeProc),
    });
  }

  _bridgeScriptPath() {
    return path.join(this.runtimeRoot, "scripts", "bridge_device_to_backend.py");
  }

  _ensureBridge(deviceIp, apiBase) {
    if (this.bridgeProc && this.bridgeDeviceIp === deviceIp) {
      return;
    }
    this._stopBridge();
    const python = resolvePythonCommand(this.runtimeRoot);
    if (!python) {
      this.onStatus({ ok: false, error: "No Python runtime available for bridge helper" });
      return;
    }
    const scriptPath = this._bridgeScriptPath();
    if (!fs.existsSync(scriptPath)) {
      this.onStatus({ ok: false, error: `Bridge helper missing: ${scriptPath}` });
      return;
    }
    const args = [
      ...python.args,
      scriptPath,
      "--device-ip",
      deviceIp,
      "--backend-url",
      apiBase,
    ];
    this.bridgeProc = spawn(python.command, args, {
      cwd: this.runtimeRoot,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.bridgeDeviceIp = deviceIp;
    this.bridgeStdout = "";
    this.bridgeStderr = "";
    this.bridgeProc.stdout?.on("data", (chunk) => {
      this.bridgeStdout = `${this.bridgeStdout}${chunk}`.slice(-4000);
    });
    this.bridgeProc.stderr?.on("data", (chunk) => {
      this.bridgeStderr = `${this.bridgeStderr}${chunk}`.slice(-4000);
    });
    this.bridgeProc.on("exit", (code, signal) => {
      const sameProc = this.bridgeProc;
      this.bridgeProc = null;
      const wasFor = this.bridgeDeviceIp;
      this.bridgeDeviceIp = "";
      this.onStatus({
        ok: code === 0,
        bridgeRunning: false,
        bridgeDeviceIp: null,
        bridgeExit: { code, signal, deviceIp: wasFor },
        bridgeStdout: this.bridgeStdout,
        bridgeStderr: this.bridgeStderr,
      });
      if (sameProc) {
        this.bridgeStdout = "";
        this.bridgeStderr = "";
      }
    });
  }

  _stopBridge() {
    if (!this.bridgeProc) {
      this.bridgeDeviceIp = "";
      return;
    }
    try {
      this.bridgeProc.kill();
    } catch {}
    this.bridgeProc = null;
    this.bridgeDeviceIp = "";
  }
}

module.exports = {
  DeviceSyncManager,
  DEFAULT_API_BASE,
};
