import argparse
import sys
import time

import paramiko


def run(host: str, username: str, password: str, ssid: str, wifi_password: str) -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        username=username,
        password=password,
        timeout=6,
        banner_timeout=6,
        auth_timeout=6,
        look_for_keys=False,
        allow_agent=False,
    )
    remote = f"""
set -e
if nmcli -t -f NAME connection show | grep -Fxq '{ssid}'; then
  echo {password} | sudo -S -k nmcli connection modify '{ssid}' wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{wifi_password}' 802-11-wireless.ssid '{ssid}' connection.autoconnect yes connection.autoconnect-priority 100
else
  echo {password} | sudo -S -k nmcli connection add type wifi ifname wlan0 con-name '{ssid}' ssid '{ssid}'
  echo {password} | sudo -S -k nmcli connection modify '{ssid}' wifi-sec.key-mgmt wpa-psk wifi-sec.psk '{wifi_password}' connection.autoconnect yes connection.autoconnect-priority 100
fi
nohup bash -lc "sleep 1; echo {password} | sudo -S -k nmcli connection up '{ssid}' ifname wlan0" >/tmp/codex-switch-wifi.log 2>&1 < /dev/null &
echo WIFI_SWITCH_SCHEDULED
"""
    stdin, stdout, stderr = client.exec_command(remote, get_pty=True)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    client.close()
    sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--ssid", required=True)
    parser.add_argument("--wifi-password", required=True)
    args = parser.parse_args()
    return run(args.host, args.username, args.password, args.ssid, args.wifi_password)


if __name__ == "__main__":
    raise SystemExit(main())
