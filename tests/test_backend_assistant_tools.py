from __future__ import annotations

import sqlite3

import pytest

from backend.assistant_service import AssistantService


@pytest.fixture()
def assistant_service(tmp_path, monkeypatch):
    service = AssistantService()
    service.store.root = tmp_path
    service.store.data_root = tmp_path / "assistant_data"
    service.store.data_root.mkdir(parents=True, exist_ok=True)
    launched_urls = []
    launched_apps = []
    monkeypatch.setattr(service, "_launch_url", lambda url: launched_urls.append(url))
    monkeypatch.setattr(service, "_launch_app", lambda alias: launched_apps.append(alias))
    service._launched_urls = launched_urls
    service._launched_apps = launched_apps
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

    monkeypatch.setattr(
        assistant_service,
        "_robot_post",
        fake_robot_post,
    )
    monkeypatch.setattr(
        assistant_service,
        "_robot_get_status",
        fake_robot_get_status,
    )

    results = await assistant_service._run_explicit_tools(conn, 1, "提醒我 10分钟后喝水")
    assert any(item.name == "desktop.todo_create" for item in results)

    results = await assistant_service._run_explicit_tools(conn, 1, "我想听 周杰伦 稻香")
    assert any(item.name == "desktop.play_music" for item in results)
    assert assistant_service._launched_urls

    results = await assistant_service._run_explicit_tools(conn, 1, "搜索 树莓派 zero 2w 音频延迟优化")
    assert any(item.name == "desktop.web_search" for item in results)

    results = await assistant_service._run_explicit_tools(conn, 1, "让机器人动一动并抬头")
    assert any(item.name == "robot.pan_tilt" for item in results)
    assert posts
