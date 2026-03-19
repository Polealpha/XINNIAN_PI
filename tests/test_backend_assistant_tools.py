from __future__ import annotations

import sqlite3

import pytest

from backend.assistant_service import AssistantService


MOVE_TEXT = "\u8ba9\u673a\u5668\u4eba\u52a8\u4e00\u52a8"
REMINDER_TEXT = "\u63d0\u9192\u621110\u5206\u949f\u540e\u559d\u6c34"
MUSIC_TEXT = "\u542c\u6b4c \u5468\u6770\u4f26 \u7a3b\u9999"
SEARCH_TEXT = "\u641c\u7d22 \u6811\u8393\u6d3e zero 2w \u97f3\u9891\u5ef6\u8fdf\u4f18\u5316"
ROBOT_MOVE_TEXT = "\u8ba9\u673a\u5668\u4eba\u52a8\u4e00\u52a8\u5e76\u62ac\u5934"
PAUSE_TEXT = "\u6682\u505c\u64ad\u653e"
SETUP_REPLY = "\u6211\u5148\u6574\u7406\u5f53\u524d\u4f1a\u8bdd\u9700\u8981\u7684\u4e0a\u4e0b\u6587\uff0c\u518d\u770b\u770b\u5de5\u4f5c\u533a\u91cc\u7684\u8bf4\u660e\u6587\u4ef6\u3002"
GOOD_AGENT_REPLY = "\u5df2\u5f00\u59cb\u6267\u884c\uff0c\u9a6c\u4e0a\u7ed9\u4f60\u7ed3\u679c\u3002"


@pytest.fixture()
def assistant_service(tmp_path, monkeypatch):
    service = AssistantService()
    service.store.root = tmp_path
    service.store.data_root = tmp_path / "assistant_data"
    service.store.data_root.mkdir(parents=True, exist_ok=True)
    launched_urls = []
    launched_apps = []
    launched_music = []
    media_controls = []
    monkeypatch.setattr(service, "_launch_url", lambda url: launched_urls.append(url))
    monkeypatch.setattr(service, "_launch_app", lambda alias: launched_apps.append(alias))
    monkeypatch.setattr(
        service,
        "_launch_music_app",
        lambda query: launched_music.append(query) or {
            "app": "cloudmusic",
            "query": query,
            "attempted_search": True,
            "detail": f"Launched CloudMusic and attempted in-app search for {query}",
        },
    )
    monkeypatch.setattr(service, "_try_cloudmusic_search", lambda query, pid: True)
    monkeypatch.setattr(
        service,
        "_send_media_control",
        lambda action: media_controls.append(action) or {"action": action, "detail": f"Sent media control: {action}"},
    )
    service._launched_urls = launched_urls
    service._launched_apps = launched_apps
    service._launched_music = launched_music
    service._media_controls = media_controls
    return service


def test_runtime_status_reports_missing_openclaw_state(assistant_service):
    status = assistant_service.runtime_status()
    assert "gateway_ready" in status
    assert "desktop.play_music" in status["desktop_tools"]


@pytest.mark.asyncio
async def test_explicit_tools_cover_reminder_music_web_and_robot(monkeypatch, assistant_service):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            device_id TEXT,
            device_ip TEXT,
            updated_at INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO devices (user_id, device_id, device_ip, updated_at) VALUES (1, 'pi-zero', '127.0.0.1:8090', 1)"
    )
    posts = []

    async def fake_robot_post(conn, user_id, path, payload, device_id=None):
        posts.append((path, payload))
        return {"ok": True}

    async def fake_robot_get_status(conn, user_id, device_id=None):
        return {"mode": "normal"}

    monkeypatch.setattr(assistant_service, "_robot_post", fake_robot_post)
    monkeypatch.setattr(assistant_service, "_robot_get_status", fake_robot_get_status)

    results = await assistant_service._run_explicit_tools(conn, 1, REMINDER_TEXT)
    assert any(item.name == "desktop.todo_create" for item in results)

    results = await assistant_service._run_explicit_tools(conn, 1, MUSIC_TEXT)
    assert any(item.name == "desktop.play_music" for item in results)
    assert assistant_service._launched_music == ["\u5468\u6770\u4f26 \u7a3b\u9999"]

    results = await assistant_service._run_explicit_tools(conn, 1, SEARCH_TEXT)
    assert any(item.name == "desktop.web_search" for item in results)

    results = await assistant_service._run_explicit_tools(conn, 1, ROBOT_MOVE_TEXT)
    assert any(item.name == "robot.pan_tilt" for item in results)
    assert all(item.name != "robot.speak" for item in results)
    assert posts

    results = await assistant_service._run_explicit_tools(conn, 1, PAUSE_TEXT)
    assert any(item.name == "desktop.music_pause" for item in results)
    assert assistant_service._media_controls == ["pause"]


@pytest.mark.asyncio
async def test_send_message_short_circuits_direct_control_requests(monkeypatch, assistant_service):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE chat_messages (user_id INTEGER, session_key TEXT, timestamp_ms INTEGER)")

    async def fake_robot_post(conn, user_id, path, payload, device_id=None):
        return {"ok": True, "pan": payload.get("pan", 0), "tilt": payload.get("tilt", 0)}

    async def should_not_call_gateway(session_key: str, text: str) -> str:
        raise AssertionError("gateway should not be called for direct control requests")

    monkeypatch.setattr(assistant_service, "_robot_post", fake_robot_post)
    monkeypatch.setattr(assistant_service.gateway, "send_message", should_not_call_gateway)

    payload = await assistant_service.send_message(conn, user_id=1, text=MOVE_TEXT, surface="desktop")
    assert "\u6211\u5df2\u7ecf\u8ba9\u673a\u5668\u4eba\u52a8\u4e86\u4e00\u4e0b" in payload["text"]
    assert any(item["name"] == "robot.pan_tilt" for item in payload["tool_results"])


@pytest.mark.asyncio
async def test_send_message_uses_gateway_in_agent_mode(monkeypatch, assistant_service):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE chat_messages (user_id INTEGER, session_key TEXT, timestamp_ms INTEGER)")

    async def fake_robot_post(conn, user_id, path, payload, device_id=None):
        return {"ok": True, "pan": payload.get("pan", 0), "tilt": payload.get("tilt", 0)}

    seen = {}

    async def fake_gateway(session_key: str, text: str) -> str:
        seen["session_key"] = session_key
        seen["text"] = text
        return "AGENT_MODE_OK"

    monkeypatch.setattr(assistant_service, "_robot_post", fake_robot_post)
    monkeypatch.setattr(assistant_service.gateway, "send_message", fake_gateway)

    payload = await assistant_service.send_message(
        conn,
        user_id=1,
        text=MOVE_TEXT,
        surface="desktop",
        metadata={"assistant_mode": "agent", "assistant_native_control": True},
    )

    assert payload["text"] == "AGENT_MODE_OK"
    assert any(item["name"] == "robot.pan_tilt" for item in payload["tool_results"])
    assert seen["session_key"] == "desktop:1"
    assert "[assistant_mode=agent]" in seen["text"]
    assert "[assistant_native_control=true]" in seen["text"]


@pytest.mark.asyncio
async def test_agent_mode_keeps_desktop_apps_unlaunched_on_good_reply(monkeypatch, assistant_service):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE chat_messages (user_id INTEGER, session_key TEXT, timestamp_ms INTEGER)")

    seen = {}

    async def fake_gateway(session_key: str, text: str) -> str:
        seen["session_key"] = session_key
        seen["text"] = text
        return GOOD_AGENT_REPLY

    monkeypatch.setattr(assistant_service.gateway, "send_message", fake_gateway)

    payload = await assistant_service.send_message(
        conn,
        user_id=1,
        text=MUSIC_TEXT,
        surface="desktop",
        metadata={"assistant_mode": "agent", "assistant_native_control": True},
    )

    assert payload["text"] == GOOD_AGENT_REPLY
    assert payload["tool_results"] == []
    assert assistant_service._launched_music == []
    assert assistant_service._launched_urls == []
    assert "[assistant_mode=agent]" in seen["text"]


@pytest.mark.asyncio
async def test_agent_mode_falls_back_when_reply_looks_like_setup(monkeypatch, assistant_service):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE chat_messages (user_id INTEGER, session_key TEXT, timestamp_ms INTEGER)")

    async def fake_gateway(session_key: str, text: str) -> str:
        return SETUP_REPLY

    monkeypatch.setattr(assistant_service.gateway, "send_message", fake_gateway)

    payload = await assistant_service.send_message(
        conn,
        user_id=1,
        text=MUSIC_TEXT,
        surface="desktop",
        metadata={"assistant_mode": "agent", "assistant_native_control": True},
    )

    assert "\u5df2\u4e3a\u4f60\u62c9\u8d77\u7f51\u6613\u4e91\u97f3\u4e50" in payload["text"]
    assert any(item["name"] == "desktop.play_music" for item in payload["tool_results"])
    assert assistant_service._launched_music == ["\u5468\u6770\u4f26 \u7a3b\u9999"]


@pytest.mark.asyncio
async def test_agent_mode_falls_back_when_native_execution_is_blocked(monkeypatch, assistant_service):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE chat_messages (user_id INTEGER, session_key TEXT, timestamp_ms INTEGER)")

    async def fake_gateway(session_key: str, text: str) -> str:
        return "\u5df2\u5f00\u59cb\u6267\u884c\uff0c\u4f46\u6d4f\u89c8\u5668\u6253\u5f00\u52a8\u4f5c\u521a\u88ab\u53d6\u6d88\u4e86\uff0c\u6240\u4ee5\u767e\u5ea6\u76ee\u524d\u8fd8\u6ca1\u6253\u5f00\u3002"

    monkeypatch.setattr(assistant_service.gateway, "send_message", fake_gateway)

    payload = await assistant_service.send_message(
        conn,
        user_id=1,
        text="\u6253\u5f00\u767e\u5ea6",
        surface="desktop",
        metadata={"assistant_mode": "agent", "assistant_native_control": True},
    )

    assert any(item["name"] == "desktop.open_url" for item in payload["tool_results"])
    assert assistant_service._launched_urls == ["https://www.baidu.com/s?wd=%E7%99%BE%E5%BA%A6"]


def test_trim_desktop_target_drops_followup_clause(assistant_service):
    trimmed = assistant_service._trim_desktop_target("\u767e\u5ea6 \u5e76 \u7b80\u5355\u544a\u8bc9\u6211\u4f60\u5df2\u7ecf\u5f00\u59cb\u6267\u884c")
    assert trimmed == "\u767e\u5ea6"
