"""ws_probe'u localhost'ta çalışan gerçek bir WebSocket sunucusuyla dener (internet yok)."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from cyberbot.connection_test import event_is, weex_ping_reply, ws_probe

PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
              "WSS_PROXY", "wss_proxy", "WS_PROXY", "ws_proxy")


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    for name in PROXY_VARS:
        monkeypatch.delenv(name, raising=False)


def probe_against(handler, **kwargs):
    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            return await ws_probe(f"ws://127.0.0.1:{port}/v3/ws/public", **kwargs)

    return asyncio.run(main())


def test_answers_json_ping_skips_noise_and_returns_first_data():
    received = []

    async def handler(ws):
        received.append(json.loads(await ws.recv()))  # abonelik
        await ws.send(json.dumps({"event": "ping", "time": "1776078750000"}))
        received.append(json.loads(await ws.recv()))  # PONG cevabı
        await ws.send("json olmayan mesaj")
        await ws.send(json.dumps({"id": 1, "result": None}))
        await ws.send(json.dumps({"e": "ticker", "s": "BTCUSDT"}))
        await ws.wait_closed()

    result = probe_against(
        handler,
        subscribe=[{"id": 1, "method": "SUBSCRIBE", "params": ["BTCUSDT@ticker"]}],
        headers={"User-Agent": "test"},
        accept=event_is("ticker"),
        ping_reply=weex_ping_reply,
        timeout=5.0,
    )
    assert result.first == {"e": "ticker", "s": "BTCUSDT"}
    assert result.ms_open >= 0 and result.ms_first >= result.ms_open
    assert received[0]["method"] == "SUBSCRIBE"
    assert received[1]["method"] == "PONG"


def test_returns_none_when_no_data_before_timeout():
    async def handler(ws):
        await ws.wait_closed()

    result = probe_against(handler, subscribe=None, headers=None, accept=event_is("kline"), ping_reply=None, timeout=0.5)
    assert result.first is None and result.ms_first is None
