import asyncio
import json
import os
import ssl

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse


UPSTREAM_BASE = os.environ.get("MINICPMO_DUPLEX_UPSTREAM", "wss://127.0.0.1:18994")

app = FastAPI(title="MiniCPM-o Official Duplex Bridge")


def _build_ssl_context():
    if not UPSTREAM_BASE.startswith("wss://"):
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


UPSTREAM_SSL = _build_ssl_context()


@app.get("/health")
async def health():
    return JSONResponse(
        {
            "ok": True,
            "upstream": UPSTREAM_BASE,
            "mode": "official_duplex_ws_proxy",
        }
    )


async def _pipe_client_to_upstream(client_ws: WebSocket, upstream_ws) -> None:
    while True:
        msg = await client_ws.receive()
        if msg["type"] == "websocket.disconnect":
            break
        if "text" in msg and msg["text"] is not None:
            await upstream_ws.send(msg["text"])
        elif "bytes" in msg and msg["bytes"] is not None:
            await upstream_ws.send(msg["bytes"])


async def _pipe_upstream_to_client(client_ws: WebSocket, upstream_ws) -> None:
    async for msg in upstream_ws:
        if isinstance(msg, bytes):
            await client_ws.send_bytes(msg)
        else:
            try:
                json.loads(msg)
                await client_ws.send_text(msg)
            except Exception:
                await client_ws.send_text(msg)


@app.websocket("/ws/duplex/{session_id}")
async def duplex_proxy(ws: WebSocket, session_id: str):
    await ws.accept()
    upstream_url = f"{UPSTREAM_BASE}/ws/duplex/{session_id}"
    try:
        async with websockets.connect(
            upstream_url,
            max_size=None,
            ssl=UPSTREAM_SSL,
            ping_interval=30,
            ping_timeout=120,
            close_timeout=10,
        ) as upstream:
            t1 = asyncio.create_task(_pipe_client_to_upstream(ws, upstream))
            t2 = asyncio.create_task(_pipe_upstream_to_client(ws, upstream))
            done, pending = await asyncio.wait(
                {t1, t2}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "error": str(e)}))
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


def main():
    uvicorn.run(
        "deployment.minicpmo_native_duplex.bridge_app:app",
        host="127.0.0.1",
        port=19002,
        reload=False,
    )


if __name__ == "__main__":
    main()
