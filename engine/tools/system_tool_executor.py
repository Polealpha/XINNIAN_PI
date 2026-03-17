from __future__ import annotations

import os
import subprocess
import time
import webbrowser
import csv
import io
import json
import base64
from dataclasses import dataclass
from typing import List
from urllib.parse import quote_plus

import httpx
try:
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
except Exception:  # pragma: no cover
    Desktop = None  # type: ignore[assignment]
    send_keys = None  # type: ignore[assignment]
try:
    import win32clipboard
except Exception:  # pragma: no cover
    win32clipboard = None  # type: ignore[assignment]

from .local_tools import ToolResult, open_music_reply
from .tool_intent_router import ToolIntent


@dataclass
class SystemToolExecutor:
    enabled: bool = True
    mode: str = "allowlist_direct"
    allowlist_apps: List[str] = None  # type: ignore[assignment]
    allowlist_actions: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.allowlist_apps = [str(x).strip().lower() for x in (self.allowlist_apps or []) if str(x).strip()]
        self.allowlist_actions = [str(x).strip().lower() for x in (self.allowlist_actions or []) if str(x).strip()]
        if not self.allowlist_apps:
            self.allowlist_apps = ["netease_music", "browser", "notepad", "calculator"]
        if not self.allowlist_actions:
            self.allowlist_actions = ["open_app", "open_url", "music_search_play", "bilibili_search_play"]

    def execute(self, intent: ToolIntent) -> ToolResult:
        if not self.enabled:
            return ToolResult(ok=False, text="系统工具当前已关闭。", reason="system_tool_exec_disabled")
        if str(self.mode or "").strip().lower() != "allowlist_direct":
            return ToolResult(ok=False, text="系统工具模式不支持当前操作。", reason="system_tool_exec_mode_unsupported")

        action = str(intent.action or "").strip().lower()
        if action not in self.allowlist_actions:
            return ToolResult(ok=False, text="该系统操作不在白名单中。", reason="system_tool_exec_denied_action")

        try:
            if action == "open_app":
                app = str(intent.args.get("app", "")).strip().lower()
                return self._open_app(app)
            if action == "open_url":
                url = str(intent.args.get("url", "")).strip()
                if not url:
                    return ToolResult(ok=False, text="缺少可打开的链接。", reason="system_tool_exec_failed")
                webbrowser.open(url, new=2)
                return ToolResult(ok=True, text="已为你打开对应网页。", reason="system_tool_exec_ok")
            if action == "music_search_play":
                song = str(intent.args.get("song", "")).strip()
                return self._music_search_play(song)
            if action == "bilibili_search_play":
                query = str(intent.args.get("query", "")).strip()
                return self._bilibili_search_play(query)
            return ToolResult(ok=False, text="系统工具暂不支持该动作。", reason="system_tool_exec_failed")
        except Exception as exc:
            return ToolResult(ok=False, text="系统工具执行失败，请稍后再试。", reason=f"system_tool_exec_failed:{exc}")

    def _open_app(self, app: str) -> ToolResult:
        if app not in self.allowlist_apps:
            return ToolResult(ok=False, text="该应用不在白名单中。", reason="system_tool_exec_denied_app")

        if app == "netease_music":
            res = open_music_reply("")
            if res.ok:
                return ToolResult(ok=True, text="已打开网易云音乐。", reason="system_tool_exec_ok")
            return ToolResult(ok=False, text=res.text, reason="system_tool_exec_failed")

        if app == "browser":
            webbrowser.open("https://www.bing.com", new=2)
            return ToolResult(ok=True, text="已为你打开浏览器。", reason="system_tool_exec_ok")

        if app == "notepad":
            if os.name == "nt":
                subprocess.Popen(["notepad.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return ToolResult(ok=True, text="已为你打开记事本。", reason="system_tool_exec_ok")
            return ToolResult(ok=False, text="当前系统不支持打开记事本。", reason="system_tool_exec_failed")

        if app == "calculator":
            if os.name == "nt":
                subprocess.Popen(["calc.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return ToolResult(ok=True, text="已为你打开计算器。", reason="system_tool_exec_ok")
            return ToolResult(ok=False, text="当前系统不支持打开计算器。", reason="system_tool_exec_failed")

        return ToolResult(ok=False, text="未支持的应用。", reason="system_tool_exec_failed")

    def _music_search_play(self, song: str) -> ToolResult:
        song_name = str(song or "").strip()
        if not song_name:
            res = open_music_reply("")
            if res.ok:
                return ToolResult(ok=True, text="已打开网易云音乐。", reason="system_tool_exec_ok")
            return ToolResult(ok=False, text=res.text, reason="system_tool_exec_failed")

        app_ok = self._start_netease_app()
        if app_ok:
            time.sleep(1.3)
            best_title = ""
            before_track = self._read_primary_track_text()

            song_id, canonical_title = self._search_song_id(song_name)
            if song_id > 0:
                best_title = canonical_title or song_name
                if self._open_song_play_command(song_id):
                    switched = self._wait_track_switch(before_track=before_track, expect_song=best_title, timeout_sec=4.0)
                    if switched:
                        return ToolResult(
                            ok=True,
                            text=f"已在网易云中搜索并开始播放《{best_title}》。",
                            reason="system_tool_exec_ok",
                        )
                if self._open_song_by_id(song_id):
                    time.sleep(0.9)
                    step_ok, title, title_hit = self._trigger_play_hotkey(expect_song=best_title)
                    if step_ok and (title_hit or self._title_matches(title, best_title)):
                        switched = self._wait_track_switch(before_track=before_track, expect_song=best_title)
                        if switched:
                            return ToolResult(
                                ok=True,
                                text=f"已在网易云中打开并开始播放《{best_title}》。",
                                reason="system_tool_exec_ok",
                            )
                        return ToolResult(
                            ok=False,
                            text=f"已定位并触发《{best_title}》播放按键，但未确认切到该歌曲。",
                            reason="system_tool_exec_partial",
                        )

            uia_ok, uia_confirmed = self._netease_search_and_play_uia(song_name, before_track=before_track)
            if uia_ok and uia_confirmed:
                return ToolResult(
                    ok=True,
                    text=f"已在网易云中搜索并开始播放《{song_name}》。",
                    reason="system_tool_exec_ok",
                )
            if uia_ok:
                return ToolResult(
                    ok=False,
                    text=f"已在网易云中搜索并点击播放《{song_name}》，但未确认播放状态变化。",
                    reason="system_tool_exec_partial",
                )

            last_title = ""
            for settle_ms in (900, 1300, 1700):
                step_ok, title, title_hit = self._netease_search_and_play(song_name, settle_ms=settle_ms)
                last_title = title or last_title
                if step_ok and title_hit:
                    return ToolResult(
                        ok=True,
                        text=f"已在网易云中定位并触发《{song_name}》播放。",
                        reason="system_tool_exec_ok",
                    )
                if step_ok:
                    # Re-try with a longer settle window before declaring partial.
                    time.sleep(0.5)
            tail = f"（当前窗口：{last_title}）" if last_title else ""
            locate_note = f"已定位到《{best_title}》并" if best_title else ""
            return ToolResult(
                ok=False,
                text=f"已打开网易云，{locate_note}尝试播放《{song_name}》，但没确认到已开始播放{tail}。你可以说“重试播放《{song_name}》”。",
                reason="system_tool_exec_partial",
            )

        return ToolResult(
            ok=False,
            text=f"网易云客户端启动失败，未能自动播放《{song_name}》。",
            reason="system_tool_exec_failed",
        )

    def _bilibili_search_play(self, query: str) -> ToolResult:
        q = str(query or "").strip()
        if not q:
            webbrowser.open("https://www.bilibili.com", new=2)
            return ToolResult(ok=True, text="已为你打开 B 站网页版。", reason="system_tool_exec_ok")

        video_url = ""
        video_title = ""
        try:
            with httpx.Client(timeout=6.0, follow_redirects=True) as client:
                resp = client.get(
                    "https://api.bilibili.com/x/web-interface/search/type",
                    params={"search_type": "video", "keyword": q, "page": 1},
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://www.bilibili.com",
                    },
                )
                resp.raise_for_status()
                payload = resp.json() if resp.text else {}
                data = payload.get("data") if isinstance(payload, dict) else None
                result = data.get("result") if isinstance(data, dict) else None
                if isinstance(result, list) and result:
                    first = result[0] if isinstance(result[0], dict) else {}
                    bvid = str(first.get("bvid") or "").strip()
                    arcurl = str(first.get("arcurl") or "").strip()
                    title = str(first.get("title") or "").strip()
                    if bvid:
                        video_url = f"https://www.bilibili.com/video/{bvid}"
                    elif arcurl.startswith("http"):
                        video_url = arcurl
                    video_title = title
        except Exception:
            video_url = ""

        if video_url:
            webbrowser.open(video_url, new=2)
            clean_title = self._clean_bilibili_title(video_title) or q
            return ToolResult(
                ok=True,
                text=f"已在 B 站为你打开《{clean_title}》，你可以直接播放。",
                reason="system_tool_exec_ok",
            )

        fallback_url = f"https://search.bilibili.com/all?keyword={quote_plus(q)}"
        webbrowser.open(fallback_url, new=2)
        return ToolResult(
            ok=False,
            text=f"已为你打开 B 站搜索页并搜索“{q}”，请点选要播放的视频。",
            reason="system_tool_exec_partial",
        )

    def _clean_bilibili_title(self, raw: str) -> str:
        title = str(raw or "").strip()
        if not title:
            return ""
        title = title.replace("<em class=\"keyword\">", "").replace("</em>", "")
        title = title.replace("&amp;", "&")
        title = title.replace("&quot;", "\"")
        title = title.replace("&#39;", "'")
        return title.strip()

    def _start_netease_app(self) -> bool:
        if os.name != "nt":
            return False
        # Preferred protocol launch.
        try:
            os.startfile("orpheus://")  # type: ignore[attr-defined]
            return self._wait_cloudmusic_ready(timeout_sec=4.0)
        except Exception:
            pass

        candidates = [
            r"C:\Program Files (x86)\Netease\CloudMusic\cloudmusic.exe",
            r"C:\Program Files\Netease\CloudMusic\cloudmusic.exe",
        ]
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self._wait_cloudmusic_ready(timeout_sec=4.0)
            except Exception:
                continue
        return False

    def _netease_search_and_play(self, song_name: str, settle_ms: int = 900) -> tuple[bool, str, bool]:
        if os.name != "nt":
            return False, "", False
        # Use Windows UI automation via SendKeys:
        # activate app -> Ctrl+F -> paste song -> Enter -> select -> Enter -> play.
        safe_song = song_name.replace("'", "''")
        pid = self._find_cloudmusic_pid()
        activate = (
            f"$ok=$ws.AppActivate({pid});" if pid > 0 else "$ok=$ws.AppActivate('网易云音乐');"
        )
        script = (
            "$ErrorActionPreference='Stop';"
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$ws=New-Object -ComObject WScript.Shell;"
            f"{activate}"
            "if(-not $ok){$ok=$ws.AppActivate('CloudMusic')};"
            "if(-not $ok){$ok=$ws.AppActivate('网易云音乐')};"
            "if(-not $ok){exit 3};"
            "Start-Sleep -Milliseconds 220;"
            f"[System.Windows.Forms.Clipboard]::SetText('{safe_song}');"
            "Start-Sleep -Milliseconds 100;"
            "$ws.SendKeys('^f');"
            "Start-Sleep -Milliseconds 180;"
            "$ws.SendKeys('^a');"
            "Start-Sleep -Milliseconds 100;"
            "$ws.SendKeys('^v');"
            "Start-Sleep -Milliseconds 220;"
            "$ws.SendKeys('{ENTER}');"
            "Start-Sleep -Milliseconds 520;"
            "$ws.SendKeys('{DOWN}');"
            "Start-Sleep -Milliseconds 180;"
            "$ws.SendKeys('{ENTER}');"
            "Start-Sleep -Milliseconds 300;"
            "$ws.SendKeys('{ENTER}');"
            "Start-Sleep -Milliseconds 220;"
            "$ws.SendKeys(' ');"
            "Start-Sleep -Milliseconds 160;"
            "$ws.SendKeys('{MEDIA_PLAY_PAUSE}');"
            f"Start-Sleep -Milliseconds {max(500, int(settle_ms))};"
            "$title='';"
            "$pid2=(Get-Process -Name cloudmusic -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id);"
            "if($pid2){$title=(Get-Process -Id $pid2 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty MainWindowTitle)};"
            "Write-Output (ConvertTo-Json @{ok=$ok; title=$title} -Compress);"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode != 0:
                return False, "", False
            raw = str(proc.stdout or "").strip().splitlines()
            payload = raw[-1] if raw else ""
            title = ""
            if payload:
                try:
                    value = json.loads(payload)
                    title = str(value.get("title") or "").strip()
                except Exception:
                    title = payload
            title_hit = self._title_matches(title, song_name)
            return True, title, title_hit
        except Exception:
            return False, "", False

    def _search_song_id(self, song_name: str) -> tuple[int, str]:
        try:
            with httpx.Client(timeout=6.0, follow_redirects=True) as client:
                resp = client.get(
                    "https://music.163.com/api/cloudsearch/pc",
                    params={"s": song_name, "type": 1, "offset": 0, "limit": 5},
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"},
                )
                resp.raise_for_status()
                data = resp.json() if resp.text else {}
        except Exception:
            return -1, ""
        result = data.get("result") if isinstance(data, dict) else None
        songs = result.get("songs") if isinstance(result, dict) else None
        if not isinstance(songs, list) or not songs:
            return -1, ""
        for item in songs:
            if not isinstance(item, dict):
                continue
            sid = item.get("id")
            name = str(item.get("name") or "").strip()
            if sid is None:
                continue
            try:
                sid_int = int(sid)
            except Exception:
                continue
            if name and self._title_matches(name, song_name):
                return sid_int, name
        first = songs[0] if isinstance(songs[0], dict) else {}
        try:
            return int(first.get("id")), str(first.get("name") or "").strip()
        except Exception:
            return -1, ""

    def _open_song_by_id(self, song_id: int) -> bool:
        if os.name != "nt" or song_id <= 0:
            return False
        try:
            os.startfile(f"orpheus://song/{int(song_id)}")  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    def _open_song_play_command(self, song_id: int) -> bool:
        if os.name != "nt" or song_id <= 0:
            return False
        payload = {"type": "song", "id": str(int(song_id)), "cmd": "play"}
        try:
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            token = base64.b64encode(raw).decode("utf-8")
            os.startfile(f"orpheus://{token}")  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    def _trigger_play_hotkey(self, expect_song: str = "") -> tuple[bool, str, bool]:
        if os.name != "nt":
            return False, "", False
        pid = self._find_cloudmusic_pid()
        activate = f"$ok=$ws.AppActivate({pid});" if pid > 0 else "$ok=$ws.AppActivate('网易云音乐');"
        script = (
            "$ErrorActionPreference='Stop';"
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$ws=New-Object -ComObject WScript.Shell;"
            f"{activate}"
            "if(-not $ok){$ok=$ws.AppActivate('CloudMusic')};"
            "if(-not $ok){$ok=$ws.AppActivate('网易云音乐')};"
            "if(-not $ok){exit 3};"
            "Start-Sleep -Milliseconds 250;"
            "$ws.SendKeys(' ');"
            "Start-Sleep -Milliseconds 200;"
            "$ws.SendKeys('{MEDIA_PLAY_PAUSE}');"
            "Start-Sleep -Milliseconds 900;"
            "$title='';"
            "$pid2=(Get-Process -Name cloudmusic -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id);"
            "if($pid2){$title=(Get-Process -Id $pid2 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty MainWindowTitle)};"
            "Write-Output (ConvertTo-Json @{ok=$ok; title=$title} -Compress);"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if proc.returncode != 0:
                return False, "", False
            raw = str(proc.stdout or "").strip().splitlines()
            payload = raw[-1] if raw else ""
            title = ""
            if payload:
                try:
                    value = json.loads(payload)
                    title = str(value.get("title") or "").strip()
                except Exception:
                    title = payload
            return True, title, self._title_matches(title, expect_song)
        except Exception:
            return False, "", False

    def _title_matches(self, title: str, song_name: str) -> bool:
        t = str(title or "").strip().lower()
        s = str(song_name or "").strip().lower()
        if not t or not s:
            return False
        return s in t

    def _get_cloudmusic_main_window(self):
        if Desktop is None:
            return None
        pids = self._list_cloudmusic_pids()
        if not pids:
            return None
        desk = Desktop(backend="uia")
        for pid in pids:
            try:
                windows = desk.windows(process=pid)
            except Exception:
                continue
            for win in windows:
                title = str(win.window_text() or "").strip()
                cls = str(getattr(win.element_info, "class_name", "") or "")
                if cls == "OrpheusBrowserHost" or title:
                    return win
        return None

    def _list_cloudmusic_pids(self) -> List[int]:
        if os.name != "nt":
            return []
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq cloudmusic.exe", "/FO", "CSV", "/NH"],
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="ignore")
        except Exception:
            return []
        pids: List[int] = []
        for row in csv.reader(io.StringIO(str(out or "").strip())):
            if len(row) < 2:
                continue
            if not str(row[0] or "").lower().startswith("cloudmusic"):
                continue
            try:
                pids.append(int(str(row[1]).replace(",", "").strip()))
            except Exception:
                continue
        return pids

    def _read_primary_track_text(self) -> str:
        win = self._get_cloudmusic_main_window()
        if win is None:
            return ""
        try:
            edits = win.descendants(control_type="Edit")
        except Exception:
            return ""
        best = ""
        for ed in edits:
            text = str(ed.window_text() or "").strip()
            if not text:
                continue
            if len(text) > len(best):
                best = text
        return best

    def _wait_track_switch(self, before_track: str, expect_song: str, timeout_sec: float = 4.0) -> bool:
        end = time.time() + max(1.0, float(timeout_sec))
        before = str(before_track or "").strip().lower()
        expect = str(expect_song or "").strip().lower()
        while time.time() < end:
            now = str(self._read_primary_track_text() or "").strip().lower()
            if now and expect and expect in now:
                return True
            if now and before and now != before and expect and expect in now:
                return True
            time.sleep(0.35)
        return False

    def _netease_search_and_play_uia(self, song_name: str, before_track: str = "") -> tuple[bool, bool]:
        if Desktop is None or send_keys is None or os.name != "nt":
            return False, False
        win = self._get_cloudmusic_main_window()
        if win is None:
            return False, False
        try:
            win.set_focus()
            time.sleep(0.2)
            # Prefer explicit search button click.
            search_clicked = False
            for btn in win.descendants(control_type="Button"):
                name = str(btn.window_text() or "").strip().lower()
                if name in {"search", "搜索"}:
                    try:
                        btn.click_input()
                        search_clicked = True
                        break
                    except Exception:
                        continue
            if not search_clicked:
                send_keys("^f", pause=0.02)
            time.sleep(0.2)

            # Paste query and submit.
            try:
                send_keys("^a", pause=0.02)
            except Exception:
                pass
            if not self._set_clipboard_text(song_name):
                send_keys(song_name, with_spaces=True, pause=0.03, vk_packet=True)
            else:
                send_keys("^v", pause=0.03)
            time.sleep(0.08)
            send_keys("{ENTER}", pause=0.02)
            time.sleep(1.4)
            search_hit = self._window_contains_text(win, song_name)

            # Click the first play control in result area.
            target = None
            for btn in win.descendants(control_type="Button"):
                name = str(btn.window_text() or "").strip().lower()
                if name in {"play 播放", "播放"}:
                    target = btn
                    break
            if target is None:
                for btn in win.descendants(control_type="Button"):
                    name = str(btn.window_text() or "").strip().lower()
                    if name == "play":
                        target = btn
                        break
            if target is None:
                return bool(search_hit), False

            try:
                target.click_input()
            except Exception:
                try:
                    target.invoke()
                except Exception:
                    return bool(search_hit), False
            time.sleep(0.35)
            # one more enter helps on some UI states.
            try:
                send_keys("{ENTER}", pause=0.02)
                send_keys(" ", pause=0.02)
            except Exception:
                pass
            confirmed = self._wait_track_switch(before_track=before_track, expect_song=song_name, timeout_sec=4.0)
            return bool(search_hit), confirmed or bool(search_hit)
        except Exception:
            return False, False

    def _set_clipboard_text(self, text: str) -> bool:
        if win32clipboard is None:
            return False
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(str(text or ""), win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return True
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            return False

    def _window_contains_text(self, win, needle: str) -> bool:
        target = str(needle or "").strip().lower()
        if not target:
            return False
        try:
            docs = win.descendants(control_type="Document")
            for doc in docs:
                txt = str(doc.window_text() or "").lower()
                if txt and target in txt:
                    return True
        except Exception:
            pass
        try:
            for ctrl in win.descendants():
                txt = str(ctrl.window_text() or "").strip().lower()
                if txt and target in txt:
                    return True
        except Exception:
            pass
        return False

    def _find_cloudmusic_pid(self) -> int:
        if os.name != "nt":
            return -1
        pids = self._list_cloudmusic_pids()
        return pids[0] if pids else -1

    def _wait_cloudmusic_ready(self, timeout_sec: float = 4.0) -> bool:
        end = time.time() + max(1.0, float(timeout_sec))
        while time.time() < end:
            if self._find_cloudmusic_pid() > 0:
                return True
            time.sleep(0.25)
        return self._find_cloudmusic_pid() > 0
