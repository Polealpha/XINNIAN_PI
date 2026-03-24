from __future__ import annotations

import argparse
import base64
import io
import os
from pathlib import Path
import re
import sys
import tarfile
import time
from typing import Iterable, Optional

import serial  # type: ignore


PROMPT_RE = re.compile(r"(?m)([\w.@:/~-]+[#$] )$")
LOGIN_RE = re.compile(r"(?im)(login:|username:)")
PASSWORD_RE = re.compile(r"(?im)(password:|密码：|密码:)")


def safe_print(text: str) -> None:
    data = f"{text}\n".encode(sys.stdout.encoding or "utf-8", errors="replace")
    sys.stdout.buffer.write(data)
    sys.stdout.flush()


class SerialLinuxConsole:
    def __init__(self, port: str, baud: int, timeout: float = 0.25) -> None:
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=2,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def write(self, text: str) -> None:
        self.ser.write(text.encode("utf-8", errors="ignore"))
        self.ser.flush()

    def read_available(self, quiet_for: float = 0.5, max_wait: float = 5.0) -> str:
        deadline = time.time() + max_wait
        chunks: list[bytes] = []
        last_rx = time.time()
        while time.time() < deadline:
            waiting = self.ser.in_waiting
            if waiting:
                data = self.ser.read(waiting)
                if data:
                    chunks.append(data)
                    last_rx = time.time()
                    continue
            if chunks and (time.time() - last_rx) >= quiet_for:
                break
            time.sleep(0.05)
        return b"".join(chunks).decode("utf-8", errors="ignore")

    def interrupt(self) -> str:
        self.ser.reset_input_buffer()
        self.write("\x03\x03\x03")
        time.sleep(0.2)
        self.write("\n")
        return self.read_available()

    def probe(self) -> str:
        self.ser.reset_input_buffer()
        self.write("\n\n")
        out = self.read_available(max_wait=3.0)
        if not out.strip():
            self.write("\x03\n")
            out = self.read_available(max_wait=3.0)
        return out

    def is_shell_ready(self, text: str) -> bool:
        return bool(PROMPT_RE.search(text))

    def login(self, username: str, password: str, timeout: float = 20.0, initial_text: str = "") -> tuple[bool, str]:
        chunks: list[str] = [initial_text] if initial_text else []
        deadline = time.time() + timeout
        prompted_user = False
        prompted_password = False
        self.write("\n")
        while time.time() < deadline:
            text = self.read_available(max_wait=1.5)
            if text:
                chunks.append(text)
            combined = "".join(chunks)
            if self.is_shell_ready(combined):
                return True, combined
            if LOGIN_RE.search(combined) and not prompted_user:
                self.write(username + "\n")
                prompted_user = True
                time.sleep(0.2)
                continue
            if PASSWORD_RE.search(combined) and not prompted_password:
                self.write(password + "\n")
                prompted_password = True
                time.sleep(0.2)
                continue
            time.sleep(0.2)
        return False, "".join(chunks)

    def run(self, command: str, timeout: float = 20.0) -> tuple[int, str]:
        marker = f"__SERIAL_PI_DONE_{int(time.time() * 1000)}__"
        wrapped = (
            f"printf '\\n'; {command}; "
            f"rc=$?; printf '\\n{marker}:%s\\n' \"$rc\""
            "\n"
        )
        self.ser.reset_input_buffer()
        self.write(wrapped)
        deadline = time.time() + timeout
        chunks: list[bytes] = []
        while time.time() < deadline:
            waiting = self.ser.in_waiting
            if waiting:
                chunks.append(self.ser.read(waiting))
                text = b"".join(chunks).decode("utf-8", errors="ignore")
                match = re.search(rf"{re.escape(marker)}:(-?\d+)", text)
                if match:
                    rc = int(match.group(1))
                    clean = re.sub(rf"\n?{re.escape(marker)}:-?\d+\n?", "\n", text)
                    return rc, clean
            time.sleep(0.05)
        return 124, b"".join(chunks).decode("utf-8", errors="ignore")

    def upload_bytes(self, data: bytes, remote_path: str, timeout: float = 120.0) -> tuple[int, str]:
        encoded = base64.b64encode(data).decode("ascii")
        tmp_b64 = f"{remote_path}.b64"
        rc, out = self.run(f"mkdir -p {shell_quote(str(Path(remote_path).parent))} && : > {shell_quote(tmp_b64)}")
        if rc != 0:
            return rc, out
        chunk_size = 512
        for idx in range(0, len(encoded), chunk_size):
            chunk = encoded[idx : idx + chunk_size]
            rc, out = self.run(f"printf '%s' {shell_quote(chunk)} >> {shell_quote(tmp_b64)}", timeout=timeout)
            if rc != 0:
                return rc, out
        return self.run(
            f"base64 -d {shell_quote(tmp_b64)} > {shell_quote(remote_path)} && rm -f {shell_quote(tmp_b64)}",
            timeout=timeout,
        )

    def download_bytes(self, remote_path: str, timeout: float = 120.0) -> tuple[int, bytes]:
        rc, out = self.run(
            "python3 -c "
            + shell_quote(
                "import base64, pathlib, sys; "
                f"p = pathlib.Path({remote_path!r}); "
                "sys.stdout.write(base64.b64encode(p.read_bytes()).decode()) if p.exists() else sys.exit(3)"
            ),
            timeout=timeout,
        )
        if rc != 0:
            return rc, b""
        payload = "".join(line.strip() for line in out.splitlines())
        try:
            return 0, base64.b64decode(payload.encode("ascii"))
        except Exception:
            return 4, b""


def shell_quote(text: str) -> str:
    return "'" + str(text).replace("'", "'\"'\"'") + "'"


def build_archive(paths: Iterable[Path], root: Path) -> bytes:
    buffer = io.BytesIO()
    skip_parts = {"__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", ".git"}
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in paths:
            full = root / path
            if full.is_dir():
                for child in sorted(full.rglob("*")):
                    if child.is_dir():
                        continue
                    if any(part in skip_parts for part in child.parts):
                        continue
                    tar.add(child, arcname=str(child.relative_to(root)).replace("\\", "/"))
            elif full.exists():
                if any(part in skip_parts for part in full.parts):
                    continue
                tar.add(full, arcname=str(path).replace("\\", "/"))
    return buffer.getvalue()


def try_connect(port: str, baud_list: list[int]) -> tuple[Optional[SerialLinuxConsole], str]:
    attempts: list[str] = []
    for baud in baud_list:
        try:
            console = SerialLinuxConsole(port, baud)
        except Exception as exc:
            attempts.append(f"{baud}: open failed: {exc}")
            continue
        text = console.probe()
        attempts.append(f"{baud}: {text[-200:]!r}")
        if console.is_shell_ready(text) or LOGIN_RE.search(text) or PASSWORD_RE.search(text):
            return console, "\n".join(attempts)
        console.close()
    return None, "\n".join(attempts)


def cmd_probe(args: argparse.Namespace) -> int:
    baud_list = [int(x) for x in args.bauds.split(",") if str(x).strip()]
    console, detail = try_connect(args.port, baud_list)
    safe_print(detail)
    if console is None:
        return 1
    try:
        banner = console.probe()
        safe_print(banner)
        if PASSWORD_RE.search(banner):
            safe_print("PASSWORD_PROMPT_DETECTED")
            return 2
        if LOGIN_RE.search(banner):
            safe_print("LOGIN_PROMPT_DETECTED")
            return 3
        safe_print(f"SHELL_READY baud={console.baud}")
        return 0
    finally:
        console.close()


def cmd_run(args: argparse.Namespace) -> int:
    console = SerialLinuxConsole(args.port, int(args.baud))
    try:
        banner = console.probe()
        if not console.is_shell_ready(banner) and args.username and args.password:
            ok, login_out = console.login(
                args.username,
                args.password,
                timeout=float(args.login_timeout),
                initial_text=banner,
            )
            safe_print(login_out)
            if not ok:
                return 5
        elif not console.is_shell_ready(banner):
            safe_print(banner)
            return 6
        if args.interrupt:
            safe_print(console.interrupt())
        rc, out = console.run(args.command, timeout=float(args.timeout))
        safe_print(out)
        return rc
    finally:
        console.close()


def cmd_deploy(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    include = [
        Path("engine"),
        Path("backend"),
        Path("pi_runtime"),
        Path("config"),
        Path("scripts"),
        Path("server_backend"),
        Path("systemd"),
        Path("requirements-pi.txt"),
        Path("README.md"),
    ]
    archive = build_archive(include, root)
    console = SerialLinuxConsole(args.port, int(args.baud))
    remote_root = str(Path(args.remote_root.replace("~", f"/home/{args.username or 'pi'}"))).rstrip("/")
    remote_archive = f"{remote_root}/emotion-pi.tar.gz"
    try:
        banner = console.probe()
        if not console.is_shell_ready(banner) and args.username and args.password:
            ok, login_out = console.login(
                args.username,
                args.password,
                timeout=float(args.login_timeout),
                initial_text=banner,
            )
            safe_print(login_out)
            if not ok:
                return 5
        elif not console.is_shell_ready(banner):
            safe_print(banner)
            return 6
        rc, out = console.run(f"mkdir -p {shell_quote(remote_root)}")
        safe_print(out)
        if rc != 0:
            return rc
        rc, out = console.upload_bytes(archive, remote_archive, timeout=float(args.timeout))
        safe_print(out)
        if rc != 0:
            return rc
        rc, out = console.run(
            f"cd {shell_quote(remote_root)} && "
            f"tar -xzf {shell_quote(remote_archive)} && rm -f {shell_quote(remote_archive)}",
            timeout=float(args.timeout),
        )
        safe_print(out)
        return rc
    finally:
        console.close()


def _login_console(console: SerialLinuxConsole, args: argparse.Namespace) -> tuple[int, str]:
    banner = console.probe()
    if not console.is_shell_ready(banner) and args.username and args.password:
        ok, login_out = console.login(
            args.username,
            args.password,
            timeout=float(args.login_timeout),
            initial_text=banner,
        )
        safe_print(login_out)
        if not ok:
            return 5, login_out
        return 0, login_out
    if not console.is_shell_ready(banner):
        safe_print(banner)
        return 6, banner
    return 0, banner


def cmd_doctor(args: argparse.Namespace) -> int:
    console = SerialLinuxConsole(args.port, int(args.baud))
    remote_root = args.remote_root.rstrip("/")
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_lines: list[str] = []
    try:
        rc, banner = _login_console(console, args)
        report_lines.append("=== login ===")
        report_lines.append(banner)
        if rc != 0:
            (output_dir / "doctor_report.txt").write_text("\n".join(report_lines), encoding="utf-8")
            return rc

        checks = [
            ("service", "systemctl status emotion-pi.service --no-pager -l || true"),
            ("camera", "libcamera-hello --list-cameras || true"),
            (
                "picamera2",
                "python3 -c \"import picamera2; print('picamera2:ok')\" 2>&1 || true",
            ),
            ("spi", "ls -l /dev/spidev* 2>/dev/null || echo 'no /dev/spidev devices'"),
            ("gpio_groups", "id && groups"),
            (
                "runtime_env",
                "grep -E '^(PI_RUNTIME_CONFIG|ENGINE_CONFIG_PATH)=' /etc/default/emotion-pi 2>/dev/null || true",
            ),
        ]
        for label, command in checks:
            rc, out = console.run(command, timeout=float(args.timeout))
            report_lines.append(f"=== {label} (rc={rc}) ===")
            report_lines.append(out.strip())

        diag_command = (
            f"cd {shell_quote(remote_root)} && "
            "export PI_RUNTIME_CONFIG=config/pi_zero2w.st7789.example.json && "
            ".venv/bin/python scripts/pi_runtime_diagnostics.py "
            "--config config/pi_zero2w.st7789.example.json "
            "--disable-audio --disable-backend"
        )
        rc, out = console.run(diag_command, timeout=float(args.timeout))
        report_lines.append(f"=== diagnostics (rc={rc}) ===")
        report_lines.append(out.strip())

        artifacts = {
            "status.json": f"{remote_root}/outputs/pi_runtime_diagnostics/status.json",
            "camera_preview.jpg": f"{remote_root}/outputs/pi_runtime_diagnostics/camera_preview.jpg",
            "display_preview.png": f"{remote_root}/outputs/pi_runtime_diagnostics/display_preview.png",
        }
        for local_name, remote_path in artifacts.items():
            file_rc, content = console.download_bytes(remote_path, timeout=float(args.timeout))
            report_lines.append(f"=== fetch {local_name} (rc={file_rc}) ===")
            if file_rc == 0 and content:
                (output_dir / local_name).write_bytes(content)
                report_lines.append(f"saved {output_dir / local_name}")
            else:
                report_lines.append(f"missing or unreadable: {remote_path}")

        (output_dir / "doctor_report.txt").write_text("\n".join(report_lines), encoding="utf-8")
        return rc
    finally:
        console.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serial manager for Raspberry Pi over COM port.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    probe = sub.add_parser("probe")
    probe.add_argument("--port", default="COM8")
    probe.add_argument("--bauds", default="115200,9600,57600,230400")
    probe.set_defaults(func=cmd_probe)

    run = sub.add_parser("run")
    run.add_argument("--port", default="COM8")
    run.add_argument("--baud", required=True, type=int)
    run.add_argument("--timeout", default="20")
    run.add_argument("--login-timeout", default="20")
    run.add_argument("--interrupt", action="store_true")
    run.add_argument("--username")
    run.add_argument("--password")
    run.add_argument("command")
    run.set_defaults(func=cmd_run)

    deploy = sub.add_parser("deploy")
    deploy.add_argument("--port", default="COM8")
    deploy.add_argument("--baud", required=True, type=int)
    deploy.add_argument("--timeout", default="120")
    deploy.add_argument("--login-timeout", default="20")
    deploy.add_argument("--root", default=os.getcwd())
    deploy.add_argument("--remote-root", default="~/emotion-pi")
    deploy.add_argument("--username")
    deploy.add_argument("--password")
    deploy.set_defaults(func=cmd_deploy)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--port", default="COM8")
    doctor.add_argument("--baud", required=True, type=int)
    doctor.add_argument("--timeout", default="180")
    doctor.add_argument("--login-timeout", default="20")
    doctor.add_argument("--remote-root", default="~/emotion-pi")
    doctor.add_argument("--output-dir", default="outputs/pi_runtime_diagnostics/serial_pi")
    doctor.add_argument("--username")
    doctor.add_argument("--password")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
