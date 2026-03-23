from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.openclaw_gateway import OpenClawGatewayClient, OpenClawGatewayConfig


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self._closed = asyncio.Event()

    async def read(self, _size: int) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        await self._closed.wait()
        return b""

    def close(self) -> None:
        self._closed.set()


class _FakeProcess:
    def __init__(self, stdout_chunks: list[bytes], stderr_chunks: list[bytes] | None = None) -> None:
        self.stdout = _FakeStream(stdout_chunks)
        self.stderr = _FakeStream(stderr_chunks or [])
        self.returncode = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15
        self.stdout.close()
        self.stderr.close()

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self.stdout.close()
        self.stderr.close()

    async def wait(self) -> int:
        while self.returncode is None:
            await asyncio.sleep(0)
        return int(self.returncode)


def _build_client(repo_path: str) -> OpenClawGatewayClient:
    return OpenClawGatewayClient(
        OpenClawGatewayConfig(
            state_dir="",
            workspace_dir=repo_path,
            codex_home=repo_path,
            repo_path=repo_path,
            url="ws://127.0.0.1:18789",
            origin="http://127.0.0.1:18789",
            timeout_ms=5000,
            client_id="test-client",
            client_mode="desktop",
        )
    )


@pytest.mark.asyncio
async def test_send_message_via_agent_returns_after_payload_without_waiting_for_clean_exit(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "run-node.mjs").write_text("// stub launcher\n", encoding="utf-8")

    process = _FakeProcess(
        [
            b'{"event":"agent.started"}\n',
            b'{"result":{"payloads":[{"text":"OPENCLAW_OK"}]}}\n',
        ]
    )

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    client = _build_client(str(repo_root))
    result = await client._send_message_via_agent(
        {"state_dir": str(tmp_path)},
        "desktop-1",
        "hello",
        timeout_ms=5000,
    )

    assert result == "OPENCLAW_OK"
    assert process.terminated is True
    assert process.killed is False


def test_extract_agent_payload_text_uses_latest_payload_line(tmp_path):
    client = _build_client(str(tmp_path))
    output = "\n".join(
        [
            '{"event":"agent.started"}',
            '{"result":{"payloads":[]}}',
            '{"result":{"payloads":[{"text":"FINAL_REPLY"}]}}',
        ]
    )

    assert client._extract_agent_payload_text(output) == "FINAL_REPLY"


def test_build_codex_home_config_keeps_only_minimal_trusted_paths(tmp_path):
    workspace_dir = tmp_path / "workspace"
    repo_dir = tmp_path / "repo"
    client = OpenClawGatewayClient(
        OpenClawGatewayConfig(
            state_dir="",
            workspace_dir=str(workspace_dir),
            codex_home=str(tmp_path / "codex-home"),
            repo_path=str(repo_dir),
            url="ws://127.0.0.1:18789",
            origin="http://127.0.0.1:18789",
            timeout_ms=5000,
            client_id="test-client",
            client_mode="desktop",
        )
    )

    config = client._build_codex_home_config()
    assert 'model = "gpt-5.4"' in config
    assert 'personality = "pragmatic"' in config
    assert "[projects." not in config
    assert "mcp_servers" not in config
