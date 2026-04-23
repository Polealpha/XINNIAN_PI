import subprocess
import sys


PLINK = r"C:\Program Files\PuTTY\plink.exe"
HOST = "10.101.0.36"
PORT = "2222"
USER = "v6yvdcnv#root#bec2604c-ae04-4222-85f3-b399f6ab2e51"
PASSWORD = "Qingbei36974!"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/tmp_remote_exec.py \"remote command\"", file=sys.stderr)
        return 2
    use_bash = False
    args = sys.argv[1:]
    if args and args[0] == "--bash":
        use_bash = True
        args = args[1:]
    if args and args[0] == "-":
        remote_cmd = sys.stdin.read()
    else:
        remote_cmd = " ".join(args)
    if use_bash:
        remote_cmd = f"bash -lc {remote_cmd!r}"
    cmd = [
        PLINK,
        "-ssh",
        "-batch",
        "-P",
        PORT,
        "-l",
        USER,
        "-pw",
        PASSWORD,
        HOST,
        remote_cmd,
    ]
    proc = subprocess.run(cmd)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
