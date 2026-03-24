#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Personal WeChat bridge based on wcferry (old WeChat architecture).

Note:
- This route requires desktop WeChat compatibility with wcferry.
- If your machine is on newer Weixin 4.x, doctor will fail early with clear reason.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
import winreg
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

from dotenv import load_dotenv

try:
    from wcferry import Wcf, WxMsg
except Exception:
    Wcf = None
    WxMsg = None

from reply_engine import ModelConfig, ReplyEngine, normalize_text


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_ENV_PATH = APP_DIR / ".env.wecom"


@dataclass
class BridgeConfig:
    target_contact_name: str
    target_contact_wxid: str
    system_prompt: str
    openai_model: str
    temperature: float
    max_tokens: int
    reply_prefix: str
    fallback_reply_when_no_key: bool
    debug: bool


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _to_float(value: str, default: float) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def load_config(path: Path) -> BridgeConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config: {path}. Copy config.example.json to config.json first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return BridgeConfig(
        target_contact_name=str(data.get("target_contact_name", "夜半沉思")).strip(),
        target_contact_wxid=str(data.get("target_contact_wxid", "")).strip(),
        system_prompt=str(
            data.get(
                "system_prompt",
                "你是微信里的私人AI助手。用中文回复，简洁自然，聚焦可执行建议。",
            )
        ).strip(),
        openai_model=str(data.get("openai_model", "gpt-4o-mini")).strip(),
        temperature=float(data.get("temperature", 0.6)),
        max_tokens=int(data.get("max_tokens", 300)),
        reply_prefix=str(data.get("reply_prefix", "")).strip(),
        fallback_reply_when_no_key=bool(data.get("fallback_reply_when_no_key", True)),
        debug=bool(data.get("debug", False)),
    )


def build_model_config(cfg: BridgeConfig, env_file: Path) -> ModelConfig:
    load_dotenv(env_file, override=False)
    return ModelConfig(
        system_prompt=cfg.system_prompt,
        openai_model=os.getenv("OPENAI_MODEL", cfg.openai_model).strip() or cfg.openai_model,
        temperature=_to_float(os.getenv("OPENAI_TEMPERATURE", str(cfg.temperature)), cfg.temperature),
        max_tokens=_to_int(os.getenv("OPENAI_MAX_TOKENS", str(cfg.max_tokens)), cfg.max_tokens),
        reply_prefix=os.getenv("OPENAI_REPLY_PREFIX", cfg.reply_prefix).strip(),
        fallback_when_no_key=_to_bool(
            os.getenv("OPENAI_FALLBACK_WHEN_NO_KEY", str(cfg.fallback_reply_when_no_key)),
            cfg.fallback_reply_when_no_key,
        ),
        openclaw_enabled=_to_bool(os.getenv("OPENCLAW_ENABLED", "true"), True),
        openclaw_state_dir=os.getenv("OPENCLAW_STATE_DIR", str(Path.home() / ".openclaw")).strip(),
        openclaw_url=os.getenv("OPENCLAW_URL", "").strip(),
        openclaw_origin=os.getenv("OPENCLAW_ORIGIN", "").strip(),
        openclaw_session_key=os.getenv("OPENCLAW_SESSION_KEY", "agent:main:main").strip() or "agent:main:main",
        openclaw_timeout_ms=_to_int(os.getenv("OPENCLAW_TIMEOUT_MS", "15000"), 15000),
        openclaw_client_id=os.getenv("OPENCLAW_CLIENT_ID", "openclaw-control-ui").strip() or "openclaw-control-ui",
        openclaw_client_mode=os.getenv("OPENCLAW_CLIENT_MODE", "webchat").strip() or "webchat",
        codex_cli_enabled=_to_bool(os.getenv("CODEX_CLI_ENABLED", "true"), True),
        codex_cli_timeout_ms=_to_int(os.getenv("CODEX_CLI_TIMEOUT_MS", "90000"), 90000),
        codex_cli_command=os.getenv("CODEX_CLI_COMMAND", "codex").strip() or "codex",
        codex_cli_workdir=os.getenv("CODEX_CLI_WORKDIR", "").strip(),
    )


def _read_reg(root: int, key_path: str, name: str) -> str:
    try:
        with winreg.OpenKey(root, key_path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value).strip()
    except Exception:
        return ""


def detect_wechat_install() -> Dict[str, str]:
    install_path = ""
    # wcferry sdk searches Software\\Tencent\\WeChat\\InstallPath first.
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        install_path = _read_reg(root, r"Software\Tencent\WeChat", "InstallPath")
        if install_path:
            break
    if not install_path:
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            install_path = _read_reg(root, r"Software\Tencent\Weixin", "InstallPath")
            if install_path:
                break

    install_dir = Path(install_path) if install_path else None
    wechat_exe = install_dir / "WeChat.exe" if install_dir else None
    weixin_exe = install_dir / "Weixin.exe" if install_dir else None

    latest_subver = ""
    if install_dir and install_dir.exists():
        try:
            candidates = [p.name for p in install_dir.iterdir() if p.is_dir()]
            candidates.sort(reverse=True)
            if candidates:
                latest_subver = candidates[0]
        except Exception:
            latest_subver = ""

    return {
        "install_path": install_path,
        "wechat_exe_exists": str(bool(wechat_exe and wechat_exe.exists())).lower(),
        "weixin_exe_exists": str(bool(weixin_exe and weixin_exe.exists())).lower(),
        "latest_subver": latest_subver,
    }


def precheck_local_wcf() -> Tuple[bool, str]:
    if Wcf is None:
        return False, "wcferry import failed. Run: .venv39\\Scripts\\python -m pip install -r wechat_embed\\requirements.txt"

    info = detect_wechat_install()
    path = info.get("install_path", "")
    has_wechat_exe = info.get("wechat_exe_exists") == "true"
    has_weixin_exe = info.get("weixin_exe_exists") == "true"
    subver = info.get("latest_subver", "")

    if not path:
        return False, "未找到微信安装路径（注册表 Software\\Tencent\\WeChat / Weixin）。"

    # Newer personal WeChat 4.x usually has Weixin.exe + Weixin.dll, no WeChat.exe.
    if has_weixin_exe and not has_wechat_exe:
        if subver.startswith("4."):
            return (
                False,
                f"当前是个人微信 {subver}（Weixin 4.x）。wcferry 本地注入链路通常不兼容；已避免强行初始化。",
            )
        return False, "检测到 Weixin.exe 但没有 WeChat.exe，wcferry 初始化大概率失败。"

    if not has_wechat_exe:
        return False, "安装目录里未发现 WeChat.exe。"

    return True, f"precheck_ok install={path}"


def build_contact_index(wcf: Wcf) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]]]:
    contacts = wcf.get_contacts()
    name_to_wxid: Dict[str, str] = {}
    wxid_to_contact: Dict[str, Dict[str, str]] = {}
    for c in contacts:
        wxid = str(c.get("wxid", "")).strip()
        if not wxid:
            continue
        wxid_to_contact[wxid] = c
        for key in ("remark", "name", "code", "wxid"):
            value = str(c.get(key, "")).strip()
            if value and value not in name_to_wxid:
                name_to_wxid[value] = wxid
    return name_to_wxid, wxid_to_contact


def resolve_target_wxid(wcf: Wcf, cfg: BridgeConfig, to_value: Optional[str]) -> str:
    target = (to_value or cfg.target_contact_wxid or cfg.target_contact_name or "").strip()
    if not target:
        raise ValueError("No target contact configured.")
    if target.startswith("wxid_") or target.endswith("@chatroom"):
        return target
    name_to_wxid, _ = build_contact_index(wcf)
    wxid = name_to_wxid.get(target)
    if wxid:
        return wxid
    raise ValueError(f"Target '{target}' not found in contacts. Run: contacts")


def wait_for_login(wcf: Wcf, timeout_sec: int = 30) -> bool:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            if wcf.is_login():
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def cmd_contacts(wcf: Wcf) -> int:
    contacts = wcf.get_contacts()
    print(f"contacts={len(contacts)}")
    for c in contacts:
        name = c.get("name", "")
        remark = c.get("remark", "")
        code = c.get("code", "")
        wxid = c.get("wxid", "")
        print(f"name={name} | remark={remark} | code={code} | wxid={wxid}")
    return 0


def cmd_send(wcf: Wcf, cfg: BridgeConfig, text: str, to_value: Optional[str]) -> int:
    target_wxid = resolve_target_wxid(wcf, cfg, to_value)
    payload = normalize_text(text, 1200)
    if not payload:
        raise ValueError("Empty message is not allowed.")
    status = wcf.send_text(payload, target_wxid)
    print(f"send_status={status}, to={target_wxid}")
    return 0 if status == 0 else 1


def cmd_run(wcf: Wcf, cfg: BridgeConfig, engine: ReplyEngine) -> int:
    target_wxid = resolve_target_wxid(wcf, cfg, None)
    seen_ids: Deque[int] = deque(maxlen=2000)
    keep_running = True

    def _stop(*_args) -> None:
        nonlocal keep_running
        keep_running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    ok = wcf.enable_receiving_msg()
    if not ok:
        raise RuntimeError("Failed to enable receiving message stream.")

    print(f"[run] target_wxid={target_wxid}")
    print("[run] waiting messages...")

    while keep_running:
        try:
            msg: WxMsg = wcf.get_msg(block=True)
        except Exception:
            time.sleep(0.1)
            continue

        if msg.id in seen_ids:
            continue
        seen_ids.append(msg.id)

        if msg.from_self() or msg.from_group() or not msg.is_text():
            continue
        if msg.sender != target_wxid:
            continue

        incoming = normalize_text(msg.content, 1200)
        if cfg.debug:
            print(f"[recv] from={msg.sender}, id={msg.id}, text={incoming}")
        if not incoming:
            continue

        try:
            reply = engine.generate(msg.sender, incoming)
        except Exception as exc:
            reply = f"（自动回复异常）{exc}"

        reply = normalize_text(reply, 1200)
        if not reply:
            continue

        status = wcf.send_text(reply, msg.sender)
        if cfg.debug:
            print(f"[send] status={status}, text={reply}")

    wcf.disable_recv_msg()
    return 0


def cmd_doctor(cfg: BridgeConfig, env_path: Path) -> int:
    print("doctor.start")
    ok, reason = precheck_local_wcf()
    print(f"precheck_ok={ok}")
    print(f"precheck_reason={reason}")
    print(f"wechat_install={detect_wechat_install()}")

    load_dotenv(env_path, override=False)
    print(f"openai_key={'set' if bool(os.getenv('OPENAI_API_KEY')) else 'missing'}")
    print(f"openclaw_enabled={_to_bool(os.getenv('OPENCLAW_ENABLED', 'true'), True)}")
    print(f"codex_cli_enabled={_to_bool(os.getenv('CODEX_CLI_ENABLED', 'true'), True)}")

    if not ok:
        print("doctor.done=blocked")
        return 2

    # Warning: Wcf constructor may exit process if sdk init fails.
    wcf = Wcf(debug=cfg.debug, block=False)
    print(f"is_login={wcf.is_login()}")
    print(f"user_info={wcf.get_user_info()}")
    try:
        target_wxid = resolve_target_wxid(wcf, cfg, None)
        print(f"target_wxid={target_wxid}")
    except Exception as exc:
        print(f"target_error={exc}")
    print("doctor.done=ok")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Single-contact personal WeChat bridge")
    p.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.json")
    p.add_argument("--env-file", default=str(DEFAULT_ENV_PATH), help="Path to env file")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("contacts", help="List contacts")
    p_send = sub.add_parser("send", help="Send one message")
    p_send.add_argument("--text", required=True, help="Message text")
    p_send.add_argument("--to", default="", help="wxid or contact name (optional)")
    sub.add_parser("run", help="Run auto reply loop")
    sub.add_parser("doctor", help="Check environment and compatibility")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(Path(args.config))
    env_path = Path(args.env_file)

    if args.command == "doctor":
        return cmd_doctor(cfg, env_path)

    ok, reason = precheck_local_wcf()
    if not ok:
        raise RuntimeError(
            f"{reason}\n"
            "建议：使用 wechat_notify_bridge.py（不降级、不注入）作为自动回复接入。"
        )

    model_cfg = build_model_config(cfg, env_path)
    logger = logging.getLogger("wechat_bridge")
    logging.basicConfig(level=logging.DEBUG if cfg.debug else logging.INFO)
    engine = ReplyEngine(model_cfg, logger)

    wcf = Wcf(debug=cfg.debug, block=False)
    if args.command == "contacts":
        if not wait_for_login(wcf, timeout_sec=20):
            raise RuntimeError("WeChat login not detected within 20s.")
        return cmd_contacts(wcf)
    if args.command == "send":
        if not wait_for_login(wcf, timeout_sec=20):
            raise RuntimeError("WeChat login not detected within 20s.")
        return cmd_send(wcf, cfg, args.text, args.to or None)
    if args.command == "run":
        if not wait_for_login(wcf, timeout_sec=30):
            raise RuntimeError("WeChat login not detected within 30s.")
        return cmd_run(wcf, cfg, engine)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
