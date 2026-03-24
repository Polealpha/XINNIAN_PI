#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
No-injection personal WeChat bridge:
- Receive by polling Windows Notification DB
- Reply by desktop WeChat keyboard automation
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv

from reply_engine import ModelConfig, ReplyEngine, normalize_text
from wechat_os_send import send_text as send_via_desktop_wechat


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = APP_DIR / "config.notify.json"
DEFAULT_ENV_PATH = APP_DIR / ".env.wecom"
DEFAULT_NOTIFY_DB = Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Notifications" / "wpndatabase.db"
SENDER_CONTENT_SEPARATORS = ("：", ":", "Ŗē")


@dataclass
class NotifyConfig:
    target_contact_name: str
    target_aliases: List[str]
    poll_interval_sec: float
    startup_tail_only: bool
    notification_db_path: str
    debug: bool
    system_prompt: str
    openai_model: str
    temperature: float
    max_tokens: int
    reply_prefix: str
    fallback_reply_when_no_key: bool


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


def _split_csv(value: str) -> List[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def load_config(path: Path) -> NotifyConfig:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}

    target = str(data.get("target_contact_name", "夜半沉思")).strip() or "夜半沉思"
    aliases = data.get("target_aliases", [target])
    if not isinstance(aliases, list):
        aliases = [target]

    return NotifyConfig(
        target_contact_name=target,
        target_aliases=[str(x).strip() for x in aliases if str(x).strip()],
        poll_interval_sec=float(data.get("poll_interval_sec", 1.5)),
        startup_tail_only=bool(data.get("startup_tail_only", True)),
        notification_db_path=str(data.get("notification_db_path", str(DEFAULT_NOTIFY_DB))).strip(),
        debug=bool(data.get("debug", False)),
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
    )


def build_model_config(cfg: NotifyConfig, env_file: Path) -> ModelConfig:
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


def _decode_payload(payload: bytes) -> str:
    if not payload:
        return ""
    for enc in ("utf-8", "utf-16-le", "utf-16", "gbk"):
        try:
            return payload.decode(enc, errors="ignore")
        except Exception:
            continue
    return ""


def _extract_text_lines(payload_xml: str) -> List[str]:
    if not payload_xml.strip().startswith("<"):
        return []
    try:
        root = ET.fromstring(payload_xml)
    except Exception:
        return []
    lines: List[str] = []
    for node in root.findall(".//text"):
        text = normalize_text(node.text or "", 300)
        if text:
            lines.append(text)
    return lines


def _guess_sender_and_content(lines: List[str]) -> Tuple[str, str]:
    if not lines:
        return "", ""
    if len(lines) == 1:
        one = lines[0]
        for sep in SENDER_CONTENT_SEPARATORS:
            if sep in one:
                left, right = one.split(sep, 1)
                return normalize_text(left, 80), normalize_text(right, 300)
        return "", normalize_text(one, 300)
    return normalize_text(lines[0], 80), normalize_text(lines[1], 300)


def _match_target(sender: str, content: str, aliases: List[str]) -> bool:
    if not aliases:
        return False
    s = normalize_text(sender, 100)
    c = normalize_text(content, 300)
    for alias in aliases:
        if not alias:
            continue
        if alias == s:
            return True
        if s.startswith(alias):
            return True
        for sep in SENDER_CONTENT_SEPARATORS:
            if c.startswith(alias + sep):
                return True
    return False


class NotificationSource:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def max_id(self) -> int:
        with self._conn() as con:
            cur = con.cursor()
            cur.execute("SELECT COALESCE(MAX(Id), 0) FROM Notification")
            row = cur.fetchone()
            return int(row[0] or 0)

    def fetch_since(self, last_id: int, limit: int = 200) -> List[Tuple[int, str, int, bytes]]:
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT n.Id, COALESCE(h.PrimaryId, ''), n.ArrivalTime, n.Payload
                FROM Notification n
                LEFT JOIN NotificationHandler h ON n.HandlerId = h.RecordId
                WHERE n.Id > ?
                ORDER BY n.Id ASC
                LIMIT ?
                """,
                (last_id, limit),
            )
            return list(cur.fetchall())

    def recent(self, limit: int = 20) -> List[Tuple[int, str, int, bytes]]:
        with self._conn() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT n.Id, COALESCE(h.PrimaryId, ''), n.ArrivalTime, n.Payload
                FROM Notification n
                LEFT JOIN NotificationHandler h ON n.HandlerId = h.RecordId
                ORDER BY n.Id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = list(cur.fetchall())
            rows.reverse()
            return rows


def cmd_doctor(cfg: NotifyConfig, env_path: Path) -> int:
    db = Path(cfg.notification_db_path)
    print("doctor.start")
    print(f"db_path={db}")
    print(f"db_exists={db.exists()}")
    print(f"target={cfg.target_contact_name}")
    print(f"aliases={cfg.target_aliases}")
    load_dotenv(env_path, override=False)
    print(f"openai_key={'set' if bool(os.getenv('OPENAI_API_KEY')) else 'missing'}")
    print(f"openclaw_enabled={_to_bool(os.getenv('OPENCLAW_ENABLED', 'true'), True)}")
    print(f"codex_cli_enabled={_to_bool(os.getenv('CODEX_CLI_ENABLED', 'true'), True)}")

    if not db.exists():
        print("doctor.done=missing_notification_db")
        return 2

    src = NotificationSource(db)
    try:
        max_id = src.max_id()
        print(f"notification_max_id={max_id}")
        rows = src.recent(limit=15)
    except Exception as exc:
        print(f"doctor.done=db_error:{exc}")
        return 2

    print(f"recent_rows={len(rows)}")
    for row_id, primary_id, _arrival, payload in rows[-8:]:
        lines = _extract_text_lines(_decode_payload(payload))
        sender, content = _guess_sender_and_content(lines)
        matched = _match_target(sender, content, cfg.target_aliases)
        if lines:
            print(
                f"id={row_id} app={primary_id} sender={sender} content={content} matched={matched}"
            )
    print("doctor.done=ok")
    return 0


def cmd_send(cfg: NotifyConfig, text: str) -> int:
    payload = normalize_text(text, 1200)
    if not payload:
        raise ValueError("Empty message is not allowed.")
    send_via_desktop_wechat(cfg.target_contact_name, payload)
    print("send_status=ok")
    return 0


def cmd_run(cfg: NotifyConfig, env_path: Path) -> int:
    logging.basicConfig(level=logging.DEBUG if cfg.debug else logging.INFO)
    logger = logging.getLogger("wechat_notify_bridge")
    engine = ReplyEngine(build_model_config(cfg, env_path), logger)

    db = Path(cfg.notification_db_path)
    if not db.exists():
        raise FileNotFoundError(f"Notification DB not found: {db}")
    src = NotificationSource(db)

    keep_running = True
    last_id = src.max_id() if cfg.startup_tail_only else 0
    seen_messages = set()

    def _stop(*_args) -> None:
        nonlocal keep_running
        keep_running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(f"[run] target={cfg.target_contact_name}")
    print(f"[run] aliases={cfg.target_aliases}")
    print(f"[run] db={db}")
    print(f"[run] start_last_id={last_id}")

    while keep_running:
        try:
            rows = src.fetch_since(last_id)
        except Exception as exc:
            logger.warning("fetch notifications failed: %s", exc)
            time.sleep(max(0.6, cfg.poll_interval_sec))
            continue

        for row_id, primary_id, _arrival, payload in rows:
            if row_id > last_id:
                last_id = row_id
            xml_text = _decode_payload(payload)
            lines = _extract_text_lines(xml_text)
            sender, content = _guess_sender_and_content(lines)
            if not _match_target(sender, content, cfg.target_aliases):
                continue
            incoming = normalize_text(content, 600)
            if not incoming:
                continue

            dedupe_key = f"{sender}|{incoming}"
            if dedupe_key in seen_messages:
                continue
            if len(seen_messages) > 200:
                seen_messages.clear()
            seen_messages.add(dedupe_key)

            if cfg.debug:
                logger.info("matched notification id=%s app=%s text=%s", row_id, primary_id, incoming)

            try:
                reply = engine.generate(cfg.target_contact_name, incoming)
            except Exception as exc:
                reply = f"（自动回复异常）{exc}"
            reply = normalize_text(reply, 1200)
            if not reply:
                continue

            try:
                send_via_desktop_wechat(cfg.target_contact_name, reply)
                logger.info("replied id=%s", row_id)
            except Exception as exc:
                logger.warning("send reply failed id=%s err=%s", row_id, exc)

        time.sleep(max(0.5, cfg.poll_interval_sec))

    return 0


def parse_args() -> argparse.Namespace:
    raw_args = sys.argv[1:]
    config_file = str(DEFAULT_CONFIG_PATH)
    env_file = str(DEFAULT_ENV_PATH)

    if "--config" in raw_args:
        idx = raw_args.index("--config")
        if idx + 1 >= len(raw_args):
            raise ValueError("Missing value for --config")
        config_file = raw_args[idx + 1]
        del raw_args[idx: idx + 2]

    if "--env-file" in raw_args:
        idx = raw_args.index("--env-file")
        if idx + 1 >= len(raw_args):
            raise ValueError("Missing value for --env-file")
        env_file = raw_args[idx + 1]
        del raw_args[idx: idx + 2]

    p = argparse.ArgumentParser(description="Personal WeChat no-injection bridge")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check environment and show recent notifications")
    p_send = sub.add_parser("send", help="Send one message to target contact")
    p_send.add_argument("--text", required=True, help="Message text")
    sub.add_parser("run", help="Run loop: receive from notifications and auto reply")
    args = p.parse_args(raw_args)
    args.config = config_file
    args.env_file = env_file
    return args


def main() -> int:
    args = parse_args()
    cfg = load_config(Path(args.config))
    env_path = Path(args.env_file)
    if args.command == "doctor":
        return cmd_doctor(cfg, env_path)
    if args.command == "send":
        return cmd_send(cfg, args.text)
    if args.command == "run":
        return cmd_run(cfg, env_path)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
