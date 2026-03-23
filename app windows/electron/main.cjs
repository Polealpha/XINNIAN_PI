const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn, spawnSync } = require("child_process");
const { app, BrowserWindow, shell, ipcMain, Tray, Menu, nativeImage, screen, Notification } = require("electron");
const { DeviceSyncManager } = require("./deviceSync.cjs");

let mainWindow = null;
let tray = null;
let isQuitting = false;
let floatWindow = null;
let chatWindow = null;
let floatDragState = null;
let backendProc = null;
let openClawGatewayProc = null;
const LOCAL_BACKEND_URL = "http://127.0.0.1:8000";
const LOCAL_OPENCLAW_GATEWAY_PORT = 18890;
const deviceSyncManager = new DeviceSyncManager({
  onStatus: (payload) => {
    for (const win of BrowserWindow.getAllWindows()) {
      if (!win.isDestroyed()) {
        win.webContents.send("bridge-status", payload);
      }
    }
  },
});

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const resolveRuntimeRoot = () => {
  if (process.env.EMOTION_BRIDGE_ROOT) {
    return process.env.EMOTION_BRIDGE_ROOT;
  }
  if (process.env.NODE_ENV !== "production" && !process.resourcesPath.includes("app.asar")) {
    return path.resolve(__dirname, "..", "..");
  }
  return path.join(process.resourcesPath, "bridge-runtime");
};

const resolveOpenClawRepo = (runtimeRoot) => {
  if (process.env.OPENCLAW_REPO_PATH) {
    return process.env.OPENCLAW_REPO_PATH;
  }
  return path.resolve(runtimeRoot, "..", "openclaw");
};

const resolveOpenClawWorkspace = (runtimeRoot) => {
  return path.join(runtimeRoot, "assistant_data", "openclaw_workspace");
};

const resolveOpenClawStateDir = (runtimeRoot) => {
  return path.join(runtimeRoot, "assistant_data", "openclaw_state");
};

const resolveOpenClawCodexHome = (runtimeRoot) => {
  if (process.env.OPENCLAW_CODEX_HOME) {
    return process.env.OPENCLAW_CODEX_HOME;
  }
  if (process.env.LOCALAPPDATA) {
    return path.join(process.env.LOCALAPPDATA, "EmoResonance", "codex_home");
  }
  return path.join(runtimeRoot, "assistant_data", "codex_home");
};

const ensureOpenClawWorkspace = (workspaceDir) => {
  fs.mkdirSync(workspaceDir, { recursive: true });
  fs.mkdirSync(path.join(workspaceDir, "memory"), { recursive: true });
  const defaults = {
    "SOUL.md": `# SOUL.md\n\n你是“共感智能”桌面端与机器人共享的陪伴助手内核。\n\n## 当前定位\n- 为桌面端、手机端和树莓派机器人服务\n- 通过 backend 调用电脑工具与机器人动作\n- 不泄露 bootstrap、内部文件、旧微信助手上下文\n- 中文为主，语气自然、克制、可靠\n\n## 输出规则\n- 先给结果，再补必要解释\n- 用户要求精确回复时，只回复指定文本\n- 不要自述“正在读取 workspace”之类内部过程\n`,
    "USER.md": `# USER.md\n\n- Name: 待激活后确认\n- Timezone: Asia/Shanghai\n- Product: 共感智能机器人\n- Notes: 登录后会建立身份卡、人格画像、主人建档与长期陪伴记忆\n`,
    "HEARTBEAT.md": `# HEARTBEAT.md\n\n- Surface: desktop + robot\n- Goal: 稳定对话、调用电脑工具、驱动机器人动作、写入长期记忆\n`,
    "TOOLS.md": `# TOOLS.md\n\n可用工具由 backend 显式提供：\n- desktop.launch_app\n- desktop.open_url\n- desktop.web_search\n- desktop.play_music\n- desktop.todo_create\n- desktop.write_note\n- robot.get_status\n- robot.speak\n- robot.pan_tilt\n- robot.start_owner_enrollment\n- robot.get_preview\n`,
  };
  for (const [name, content] of Object.entries(defaults)) {
    const target = path.join(workspaceDir, name);
    if (!fs.existsSync(target)) {
      fs.writeFileSync(target, content, "utf8");
    }
  }
};

const ensureOpenClawCodexHome = (runtimeRoot, workspaceDir, openClawRepo) => {
  const codexHome = resolveOpenClawCodexHome(runtimeRoot);
  const sourceCodexHome = path.join(os.homedir(), ".codex");
  fs.mkdirSync(codexHome, { recursive: true });
  fs.mkdirSync(path.join(codexHome, "tmp"), { recursive: true });
  for (const name of ["auth.json", "cap_sid"]) {
    const src = path.join(sourceCodexHome, name);
    const dest = path.join(codexHome, name);
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, dest);
    }
  }
  for (const stale of ["state_5.sqlite", "state_5.sqlite-journal", "state_5.sqlite-shm", "state_5.sqlite-wal"]) {
    const target = path.join(codexHome, stale);
    try {
      if (fs.existsSync(target) && fs.statSync(target).size === 0) {
        fs.rmSync(target, { force: true });
      }
    } catch {}
  }
  const escapeTomlPath = (value) => String(value || "").replace(/\\/g, "\\\\");
  const config = [
    'model = "gpt-5.4"',
    'model_reasoning_effort = "high"',
    'personality = "pragmatic"',
    "",
    `[projects.'${escapeTomlPath(workspaceDir)}']`,
    'trust_level = "trusted"',
    "",
    `[projects.'${escapeTomlPath(openClawRepo)}']`,
    'trust_level = "trusted"',
    "",
    "[windows]",
    'sandbox = "unelevated"',
    "",
  ].join("\n");
  fs.writeFileSync(path.join(codexHome, "config.toml"), config, "utf8");
  return codexHome;
};

const ensureOpenClawState = (stateDir) => {
  const sourceState = path.join(os.homedir(), ".openclaw");
  fs.mkdirSync(stateDir, { recursive: true });
  fs.mkdirSync(path.join(stateDir, "identity"), { recursive: true });
  fs.mkdirSync(path.join(stateDir, "logs"), { recursive: true });
  const copyIfMissing = (src, dest) => {
    if (!fs.existsSync(dest) && fs.existsSync(src)) {
      fs.copyFileSync(src, dest);
    }
  };
  copyIfMissing(path.join(sourceState, "identity", "device.json"), path.join(stateDir, "identity", "device.json"));
  copyIfMissing(
    path.join(sourceState, "identity", "device-auth.json"),
    path.join(stateDir, "identity", "device-auth.json")
  );
  const targetConfig = path.join(stateDir, "openclaw.json");
  if (!fs.existsSync(targetConfig) && fs.existsSync(path.join(sourceState, "openclaw.json"))) {
    const cfg = JSON.parse(fs.readFileSync(path.join(sourceState, "openclaw.json"), "utf8"));
    cfg.gateway = cfg.gateway || {};
    cfg.gateway.mode = "local";
    cfg.gateway.port = LOCAL_OPENCLAW_GATEWAY_PORT;
    cfg.gateway.auth = cfg.gateway.auth || {};
    cfg.gateway.auth.mode = "token";
    cfg.gateway.auth.token = "chonggou-openclaw-bridge";
    cfg.agents = cfg.agents || {};
    cfg.agents.defaults = cfg.agents.defaults || {};
    cfg.agents.defaults.model = cfg.agents.defaults.model || {};
    cfg.agents.defaults.model.primary = "codex-cli/gpt-5.4";
    fs.writeFileSync(targetConfig, JSON.stringify(cfg, null, 2), "utf8");
  }
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
  const bundledPython = process.platform === "win32"
    ? path.join(runtimeRoot, "python", "python.exe")
    : path.join(runtimeRoot, "python", "bin", "python3");
  if (fs.existsSync(bundledPython)) {
    return { command: bundledPython, args: [] };
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

const isLocalBackendHealthy = async () => {
  try {
    const response = await fetch(`${LOCAL_BACKEND_URL}/api/runtime/version`);
    return response.ok;
  } catch {
    return false;
  }
};

const startLocalBackend = () => {
  if (backendProc) return;
  const runtimeRoot = resolveRuntimeRoot();
  const openClawRepo = resolveOpenClawRepo(runtimeRoot);
  const codexHome = ensureOpenClawCodexHome(
    runtimeRoot,
    resolveOpenClawWorkspace(runtimeRoot),
    openClawRepo
  );
  const backendEntry = path.join(runtimeRoot, "backend", "main.py");
  if (!fs.existsSync(backendEntry)) {
    console.error(`[main] backend bundle missing: ${backendEntry}`);
    return;
  }
  const python = resolvePythonCommand(runtimeRoot);
  if (!python) {
    console.error("[main] no Python runtime available for local backend");
    return;
  }
  backendProc = spawn(
    python.command,
    [...python.args, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd: runtimeRoot,
      env: {
        ...process.env,
        PYTHONPATH: runtimeRoot,
        OPENCLAW_WORKSPACE_DIR: resolveOpenClawWorkspace(runtimeRoot),
        OPENCLAW_STATE_DIR: resolveOpenClawStateDir(runtimeRoot),
        OPENCLAW_GATEWAY_URL: `ws://127.0.0.1:${LOCAL_OPENCLAW_GATEWAY_PORT}`,
        OPENCLAW_GATEWAY_ORIGIN: `http://127.0.0.1:${LOCAL_OPENCLAW_GATEWAY_PORT}`,
        OPENCLAW_CODEX_HOME: process.env.OPENCLAW_CODEX_HOME || codexHome,
        CODEX_HOME: process.env.CODEX_HOME || codexHome,
        TMP: path.join(codexHome, "tmp"),
        TEMP: path.join(codexHome, "tmp"),
        TMPDIR: path.join(codexHome, "tmp"),
        ALLOW_UNVERIFIED_LOCAL_DESKTOP_TOKENS: "1",
        DEFAULT_ROBOT_DEVICE_IP: process.env.DEFAULT_ROBOT_DEVICE_IP || "192.168.137.50",
      },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    }
  );
  backendProc.stdout?.on("data", (chunk) => {
    const textOut = String(chunk || "").trim();
    if (textOut) console.log(`[local-backend] ${textOut}`);
  });
  backendProc.stderr?.on("data", (chunk) => {
    const textErr = String(chunk || "").trim();
    if (textErr) console.error(`[local-backend] ${textErr}`);
  });
  backendProc.on("exit", (code, signal) => {
    console.error(`[main] local backend exited code=${code} signal=${signal}`);
    backendProc = null;
  });
};

const startLocalOpenClawGateway = () => {
  if (openClawGatewayProc) return;
  const runtimeRoot = resolveRuntimeRoot();
  const openClawRepo = resolveOpenClawRepo(runtimeRoot);
  const gatewayEntry = path.join(openClawRepo, "openclaw.mjs");
  if (!fs.existsSync(gatewayEntry)) {
    console.error(`[main] OpenClaw repo missing: ${gatewayEntry}`);
    return;
  }
  const workspaceDir = resolveOpenClawWorkspace(runtimeRoot);
  const stateDir = resolveOpenClawStateDir(runtimeRoot);
  const codexHome = ensureOpenClawCodexHome(runtimeRoot, workspaceDir, openClawRepo);
  ensureOpenClawWorkspace(workspaceDir);
  ensureOpenClawState(stateDir);
  openClawGatewayProc = spawn(
    "node",
    [
      gatewayEntry,
      "gateway",
      "run",
      "--auth",
      "token",
      "--token",
      "chonggou-openclaw-bridge",
      "--port",
      String(LOCAL_OPENCLAW_GATEWAY_PORT),
      "--bind",
      "loopback",
      "--ws-log",
      "compact",
    ],
    {
      cwd: workspaceDir,
      env: {
        ...process.env,
        OPENCLAW_STATE_DIR: process.env.OPENCLAW_STATE_DIR || stateDir,
        OPENCLAW_CODEX_HOME: process.env.OPENCLAW_CODEX_HOME || codexHome,
        CODEX_HOME: process.env.CODEX_HOME || codexHome,
        TMP: path.join(codexHome, "tmp"),
        TEMP: path.join(codexHome, "tmp"),
        TMPDIR: path.join(codexHome, "tmp"),
      },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    }
  );
  openClawGatewayProc.stdout?.on("data", (chunk) => {
    const textOut = String(chunk || "").trim();
    if (textOut) console.log(`[openclaw-gateway] ${textOut}`);
  });
  openClawGatewayProc.stderr?.on("data", (chunk) => {
    const textErr = String(chunk || "").trim();
    if (textErr) console.error(`[openclaw-gateway] ${textErr}`);
  });
  openClawGatewayProc.on("exit", (code, signal) => {
    console.error(`[main] openclaw gateway exited code=${code} signal=${signal}`);
    openClawGatewayProc = null;
  });
};

const ensureLocalBackend = async () => {
  if (await isLocalBackendHealthy()) return true;
  startLocalOpenClawGateway();
  startLocalBackend();
  for (let i = 0; i < 20; i += 1) {
    await delay(500);
    if (await isLocalBackendHealthy()) return true;
  }
  return false;
};

const stopLocalBackend = () => {
  if (!backendProc) return;
  try {
    backendProc.kill();
  } catch {}
  backendProc = null;
};

const stopLocalOpenClawGateway = () => {
  if (!openClawGatewayProc) return;
  try {
    openClawGatewayProc.kill();
  } catch {}
  openClawGatewayProc = null;
};

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.focus();
    }
    if (floatWindow && !floatWindow.isVisible()) {
      floatWindow.show();
    }
  });
}

const defaultTitleBar = {
  color: "#070b14",
  symbolColor: "#cbd5f5",
  height: 36,
};

const applyTitleBarTheme = (win, theme = {}) => {
  if (!win || typeof win.setTitleBarOverlay !== "function") return;
  const color = typeof theme.color === "string" ? theme.color : defaultTitleBar.color;
  const symbolColor =
    typeof theme.symbolColor === "string" ? theme.symbolColor : defaultTitleBar.symbolColor;
  const height = typeof theme.height === "number" ? theme.height : defaultTitleBar.height;
  try {
    win.setTitleBarOverlay({ color, symbolColor, height });
  } catch (_err) {
    // Ignore when titleBarOverlay is not enabled on this window.
  }
};

const escapeHtml = (text) =>
  String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const showWindowFatal = (win, title, message) => {
  if (!win || win.isDestroyed()) return;
  const html = `<!doctype html><html><head><meta charset="utf-8"/><title>Error</title></head><body style="margin:0;background:#070b14;color:#e2e8f0;font-family:Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;padding:20px;box-sizing:border-box;"><div style="max-width:760px;width:100%;border:1px solid rgba(148,163,184,.35);border-radius:14px;background:rgba(15,23,42,.85);padding:18px;"><h2 style="margin:0 0 10px 0;font-size:18px;">${escapeHtml(
    title
  )}</h2><div style="font-size:13px;line-height:1.6;color:#94a3b8;margin-bottom:10px;">应用未能正常加载。请重启软件；如果持续失败，请把此信息反馈给开发。</div><pre style="margin:0;padding:12px;border-radius:8px;background:rgba(2,6,23,.8);color:#f8fafc;white-space:pre-wrap;word-break:break-word;font-size:12px;">${escapeHtml(
    message
  )}</pre></div></body></html>`;
  win
    .loadURL(`data:text/html;charset=UTF-8,${encodeURIComponent(html)}`)
    .catch((err) => console.error("failed to load fallback html:", err));
};

const attachWindowDiagnostics = (win, name) => {
  if (!win || win.isDestroyed()) return;
  win.webContents.on("did-fail-load", (_event, code, desc, validatedURL) => {
    const msg = `[${name}] did-fail-load code=${code} desc=${desc} url=${validatedURL}`;
    console.error(msg);
    showWindowFatal(win, "页面加载失败", msg);
  });
  win.webContents.on("render-process-gone", (_event, details) => {
    const msg = `[${name}] render-process-gone reason=${details?.reason} code=${details?.exitCode}`;
    console.error(msg);
    showWindowFatal(win, "渲染进程已退出", msg);
  });
  win.webContents.on("unresponsive", () => {
    const msg = `[${name}] renderer unresponsive`;
    console.error(msg);
    showWindowFatal(win, "页面无响应", msg);
  });
  win.webContents.on("console-message", (_event, level, message, line, sourceId) => {
    if (level >= 2) {
      console.error(`[renderer:${name}] ${sourceId}:${line} ${message}`);
    }
  });
};

const createWindow = () => {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 640,
    backgroundColor: "#0F172A",
    icon: path.join(__dirname, "..", "assets", "app-icon.png"),
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: defaultTitleBar.color,
      symbolColor: defaultTitleBar.symbolColor,
      height: defaultTitleBar.height,
    },
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  attachWindowDiagnostics(win, "main");

  const devUrl = process.env.ELECTRON_DEV_URL;
  if (devUrl) {
    win.loadURL(devUrl).catch((err) => {
      const msg = `failed to load dev url ${devUrl}\n${err?.stack || err}`;
      console.error(msg);
      showWindowFatal(win, "开发模式加载失败", msg);
    });
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    const indexPath = path.join(__dirname, "..", "dist", "index.html");
    win.loadFile(indexPath).catch((err) => {
      const msg = `failed to load index file ${indexPath}\n${err?.stack || err}`;
      console.error(msg);
      showWindowFatal(win, "桌面页面加载失败", msg);
    });
  }

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  win.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    win.hide();
    if (tray) {
      tray.setToolTip("EmoResonance (running)");
    }
  });

  return win;
};

const loadWindowWithQuery = (win, query) => {
  const devUrl = process.env.ELECTRON_DEV_URL;
  if (devUrl) {
    return win.loadURL(`${devUrl}?${query}`);
  }
  const indexPath = path.join(__dirname, "..", "dist", "index.html");
  return win.loadFile(indexPath, { query: { [query.split("=")[0]]: query.split("=")[1] } });
};

const positionChatWindow = () => {
  if (!floatWindow || !chatWindow) return;
  const floatBounds = floatWindow.getBounds();
  const display = screen.getDisplayNearestPoint({ x: floatBounds.x, y: floatBounds.y });
  const workArea = display.workArea;
  const chatBounds = chatWindow.getBounds();
  const padding = 12;
  let x = floatBounds.x - chatBounds.width - padding;
  if (x < workArea.x) {
    x = floatBounds.x + floatBounds.width + padding;
  }
  let y = floatBounds.y + floatBounds.height - chatBounds.height;
  if (y < workArea.y + padding) y = workArea.y + padding;
  if (y + chatBounds.height > workArea.y + workArea.height - padding) {
    y = workArea.y + workArea.height - chatBounds.height - padding;
  }
  chatWindow.setPosition(Math.round(x), Math.round(y), false);
};

const createChatWindow = () => {
  const win = new BrowserWindow({
    width: 460,
    height: 560,
    resizable: false,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    backgroundColor: "#00000000",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  attachWindowDiagnostics(win, "float-chat");
  loadWindowWithQuery(win, "float=chat").catch((err) => {
    const msg = `failed to load float chat window\n${err?.stack || err}`;
    console.error(msg);
    showWindowFatal(win, "悬浮对话加载失败", msg);
  });
  win.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    win.hide();
  });
  return win;
};

const createFloatWindow = () => {
  const win = new BrowserWindow({
    width: 64,
    height: 64,
    resizable: false,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    backgroundColor: "#00000000",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  attachWindowDiagnostics(win, "float-widget");
  loadWindowWithQuery(win, "float=widget").catch((err) => {
    const msg = `failed to load float widget window\n${err?.stack || err}`;
    console.error(msg);
    showWindowFatal(win, "悬浮窗加载失败", msg);
  });
  // Let clicks pass through except when explicitly enabled from renderer.
  win.setIgnoreMouseEvents(true, { forward: true });
  const primary = screen.getPrimaryDisplay();
  const { x, y, width, height } = primary.workArea;
  win.setPosition(Math.round(x + width - 88), Math.round(y + height - 132), false);
  win.webContents.on("context-menu", () => {
    const menu = Menu.buildFromTemplate([
      {
        label: "设置",
        click: () => openMainTab("CONTROL"),
      },
      {
        label: "关闭悬浮窗",
        click: () => {
          if (chatWindow) chatWindow.hide();
          win.hide();
        },
      },
      {
        label: "问题反馈",
        click: () => openMainTab("CHAT"),
      },
      { type: "separator" },
      {
        label: "退出",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]);
    menu.popup({ window: win });
  });
  win.on("closed", () => {
    floatWindow = null;
  });
  return win;
};

const openMainTab = (tab) => {
  if (!mainWindow || mainWindow.isDestroyed()) {
    mainWindow = createWindow();
  }
  mainWindow.show();
  mainWindow.focus();
  mainWindow.webContents.send("navigate-tab", tab);
};

const ensureChatWindow = () => {
  if (!chatWindow || chatWindow.isDestroyed()) {
    chatWindow = createChatWindow();
  }
  positionChatWindow();
  chatWindow.show();
  chatWindow.focus();
};

const toggleChatWindow = () => {
  if (!chatWindow || chatWindow.isDestroyed()) {
    ensureChatWindow();
    return;
  }
  if (chatWindow.isVisible()) {
    chatWindow.hide();
  } else {
    ensureChatWindow();
  }
};

const ensureTray = () => {
  if (tray) return tray;
  const trayIconPath = path.join(__dirname, "..", "assets", "app-icon.png");
  const icon = nativeImage.createFromPath(trayIconPath);
  tray = new Tray(icon);
  tray.setToolTip("EmoResonance");
  const contextMenu = Menu.buildFromTemplate([
    {
      label: "显示主窗口",
      click: () => {
        if (!mainWindow) return;
        mainWindow.show();
        mainWindow.focus();
      },
    },
    {
      label: "显示/隐藏悬浮窗",
      click: () => {
        if (!floatWindow || floatWindow.isDestroyed()) {
          floatWindow = createFloatWindow();
          return;
        }
        if (floatWindow.isVisible()) {
          floatWindow.hide();
          if (chatWindow) chatWindow.hide();
        } else {
          floatWindow.show();
        }
      },
    },
    {
      label: "退出",
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setContextMenu(contextMenu);
  tray.on("click", () => {
    if (!mainWindow) return;
    if (mainWindow.isVisible()) {
      mainWindow.focus();
    } else {
      mainWindow.show();
      mainWindow.focus();
    }
  });
  return tray;
};

app.whenReady().then(async () => {
  await ensureLocalBackend();
  mainWindow = createWindow();
  ensureTray();
  floatWindow = createFloatWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createWindow();
    }
  });
});

ipcMain.handle("backend-session:set", async (_event, payload) => {
  await deviceSyncManager.setSession(payload || {});
  return { ok: true };
});

ipcMain.handle("backend-session:clear", async () => {
  await deviceSyncManager.clearSession();
  return { ok: true };
});

ipcMain.on("set-titlebar-theme", (event, theme) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win || win !== mainWindow) return;
  applyTitleBarTheme(win, theme);
  if (theme && typeof theme.backgroundColor === "string") {
    win.setBackgroundColor(theme.backgroundColor);
  }
});

ipcMain.on("float-toggle-chat", () => {
  toggleChatWindow();
});

ipcMain.on("open-main-tab", (_event, tab) => {
  openMainTab(tab);
});

ipcMain.on("float-hide", () => {
  if (floatWindow) floatWindow.hide();
  if (chatWindow) chatWindow.hide();
});

ipcMain.on("float-show", () => {
  if (!floatWindow || floatWindow.isDestroyed()) {
    floatWindow = createFloatWindow();
  }
  floatWindow.show();
});

ipcMain.on("float-set-interactive", (_event, enabled) => {
  if (!floatWindow || floatWindow.isDestroyed()) return;
  const shouldEnable = Boolean(enabled);
  // When interactive, capture mouse. When not, pass through.
  floatWindow.setIgnoreMouseEvents(!shouldEnable, { forward: true });
});

ipcMain.on("float-drag-move", (_event, payload) => {
  if (!floatWindow || floatWindow.isDestroyed() || !floatDragState) return;
  const cursor = screen.getCursorScreenPoint();
  const display = screen.getDisplayNearestPoint(cursor);
  const workArea = display.workArea;
  const bounds = floatWindow.getBounds();
  const padding = 0;
  const offsetX = floatDragState.offsetX ?? 0;
  const offsetY = floatDragState.offsetY ?? 0;
  let nextX = Math.round(cursor.x - offsetX);
  let nextY = Math.round(cursor.y - offsetY);
  nextX = Math.max(workArea.x + padding, Math.min(nextX, workArea.x + workArea.width - bounds.width - padding));
  nextY = Math.max(workArea.y + padding, Math.min(nextY, workArea.y + workArea.height - bounds.height - padding));
  floatWindow.setPosition(nextX, nextY, false);
  if (chatWindow && chatWindow.isVisible()) {
    positionChatWindow();
  }
});

ipcMain.on("float-drag-end", () => {
  floatDragState = null;
  if (floatWindow && !floatWindow.isDestroyed()) {
    floatWindow.setIgnoreMouseEvents(true, { forward: true });
  }
  if (chatWindow && chatWindow.isVisible()) {
    positionChatWindow();
  }
});

ipcMain.on("float-drag-start", (_event, payload) => {
  if (!floatWindow || floatWindow.isDestroyed()) return;
  const cursor = screen.getCursorScreenPoint();
  const [winX, winY] = floatWindow.getPosition();
  const bounds = floatWindow.getBounds();
  const offsetX = Math.max(0, Math.min(bounds.width, cursor.x - winX));
  const offsetY = Math.max(0, Math.min(bounds.height, cursor.y - winY));
  floatDragState = {
    startX: cursor.x,
    startY: cursor.y,
    winX,
    winY,
    offsetX: Math.round(offsetX),
    offsetY: Math.round(offsetY),
  };
});

ipcMain.on("notify-system", (_event, payload) => {
  if (!payload || !Notification.isSupported()) return;
  const title = String(payload.title || "心念双灵");
  const body = String(payload.body || "");
  const silent = Boolean(payload.silent);
  const notification = new Notification({
    title,
    body,
    silent,
    icon: path.join(__dirname, "..", "assets", "app-icon.png"),
  });
  notification.show();
});

process.on("uncaughtException", (error) => {
  console.error("[main] uncaughtException:", error);
  showWindowFatal(mainWindow, "主进程异常", error?.stack || String(error));
});

process.on("unhandledRejection", (reason) => {
  const text =
    reason instanceof Error ? reason.stack || reason.message : JSON.stringify(reason, null, 2);
  console.error("[main] unhandledRejection:", reason);
  showWindowFatal(mainWindow, "主进程未处理异常", text);
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  deviceSyncManager.dispose();
  stopLocalBackend();
  stopLocalOpenClawGateway();
});
