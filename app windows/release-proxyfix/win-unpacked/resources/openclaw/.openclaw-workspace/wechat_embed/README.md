# WeCom Embed (Enterprise WeChat)

This folder is now back to **Enterprise WeCom route as default**.

Primary runtime:
- `wecom_gateway.py` (callback verify/decrypt, auto reply, proactive send)
- default local port: `28789`

Project location:
- `E:\Desktop\openclaw\.openclaw-workspace\wechat_embed`

## Quick Start

1. Install deps

```powershell
py -3.9 -m venv .venv39
.\.venv39\Scripts\python -m pip install -r .\wechat_embed\requirements.txt
```

2. Prepare env

```powershell
Copy-Item .\wechat_embed\.env.wecom.example .\wechat_embed\.env.wecom
```

Fill required fields:
- `WECOM_CORP_ID`
- `WECOM_AGENT_ID`
- `WECOM_SECRET`
- `WECOM_TOKEN`
- `WECOM_AES_KEY`
- `WECOM_ALLOWLIST`

3. Doctor check

```powershell
.\.venv39\Scripts\python .\wechat_embed\wecom_gateway.py --env-file .\wechat_embed\.env.wecom doctor
```

4. Run gateway

```powershell
.\.venv39\Scripts\python .\wechat_embed\wecom_gateway.py --env-file .\wechat_embed\.env.wecom run --host 0.0.0.0 --port 28789
```

or directly:

```powershell
.\wechat_embed\start_wecom.ps1
```

5. Health check

```powershell
Invoke-WebRequest http://127.0.0.1:28789/healthz
```

## Callback URL

After exposing `28789` via tunnel, callback path is:
- `https://<public-host>/wecom/agent`

## Auto-start With OpenClaw (Windows)

Install scheduled task:

```powershell
.\wechat_embed\install_wecom_autostart.ps1
```

Note:
- If `schtasks` cannot be created due permission limits, installer automatically falls back to user Startup folder.

Manual trigger test:

```powershell
schtasks /Run /TN "OpenClaw WeCom Bridge"
```

Remove scheduled task:

```powershell
.\wechat_embed\uninstall_wecom_autostart.ps1
```

## Reply Backend Order

`wecom_gateway.py` fallback order:
1. OpenClaw WS (`OPENCLAW_*`)
2. Codex CLI (`CODEX_CLI_*`)
3. OpenAI API (`OPENAI_API_KEY`)
4. local fallback echo

## Legacy Personal-WeChat Scripts

The following scripts are kept for reference only and are **not default path**:
- `wechat_bridge.py`
- `wechat_notify_bridge.py`
- `wechat_os_send.py`
- `start_wechat_personal_legacy.ps1`
