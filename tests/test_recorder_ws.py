"""Likidasyon WS istemcisi: 127.0.0.1'de gerçek websockets sunucusu (internet yok)."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from cyberbot.recorder.binance_ws import LiquidationStream
from cyberbot.recorder.db import DerivsDB
from cyberbot.recorder.limiter import RealClock
from cyberbot.recorder.monitor import Status
from tests.recorder_fakes import T0, cfg, force_order

PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
              "WSS_PROXY", "wss_proxy", "WS_PROXY", "ws_proxy")


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    for name in PROXY_VARS:
        monkeypatch.delenv(name, raising=False)


def run_stream(tmp_path, handler, until, timeout=5.0, **bcfg):
    """Sunucuyu açar, akışı until(stream, rows) doğru olana kadar çalıştırır."""
    c = cfg(binance={"ws_backoff_max_s": 0.05, "ws_open_timeout_s": 2, **bcfg})["binance"]
    db = DerivsDB(tmp_path / "d.sqlite")
    rows: list[dict] = []
    status = Status()

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            stream = LiquidationStream(f"ws://127.0.0.1:{port}/market/ws", db, RealClock(), c, status, rows.extend)
            stop = asyncio.Event()
            task = asyncio.create_task(stream.run(stop))
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while not until(stream, rows) and loop.time() < deadline:
                await asyncio.sleep(0.01)
            stop.set()
            await asyncio.wait_for(task, 5)
            return stream

    stream = asyncio.run(main())
    return stream, rows, db, status


def test_subscribes_filters_st_and_records_session(tmp_path):
    received = []

    async def handler(ws):
        received.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"result": None, "id": received[0]["id"]}))
        await ws.send(json.dumps(force_order(symbol="BTCUSDT", st=1)))
        await ws.send(json.dumps(force_order(symbol="BTCUSD_PERP", st=2)))       # COIN-M: atılır
        await ws.send(json.dumps([force_order(symbol="ETHUSDT", st=1, t=T0 + 1)]))  # liste de olur
        await ws.send("bozuk")
        await ws.wait_closed()

    stream, rows, db, status = run_stream(tmp_path, handler, lambda s, r: len(r) >= 2)
    assert received[0]["method"] == "SUBSCRIBE" and received[0]["params"] == ["!forceOrder@arr"]
    assert [r["symbol"] for r in rows] == ["BTCUSDT", "ETHUSDT"]
    sessions = db.query("SELECT open_ms, close_ms, reason FROM ws_sessions")
    assert len(sessions) == 1 and sessions[0][1] >= sessions[0][0] and sessions[0][2] == "shutdown"
    assert status.ws_down_since_ms is None


def test_reconnects_after_server_close_and_records_gap(tmp_path):
    count = {"n": 0}

    async def handler(ws):
        count["n"] += 1
        n = count["n"]
        await ws.recv()
        await ws.send(json.dumps(force_order(t=T0 + n)))
        if n == 1:
            await asyncio.sleep(0.05)
            await ws.close()  # sunucu keser
            return
        await ws.wait_closed()

    stream, rows, db, _ = run_stream(tmp_path, handler, lambda s, r: len(r) >= 2, ws_gap_min_s=0)
    sessions = db.query("SELECT conn_id, open_ms, close_ms, reason FROM ws_sessions ORDER BY conn_id")
    assert len(sessions) == 2 and sessions[0][3] == "server_closed"
    assert sessions[1][1] >= sessions[0][2]
    gaps = db.gaps("bn_liq")
    assert len(gaps) == 1 and gaps[0][-1] == "unrecoverable" and gaps[0][2] == sessions[0][2]


def test_rotation_overlaps_connections(tmp_path):
    async def handler(ws):
        await ws.recv()
        await ws.send(json.dumps(force_order()))  # her bağlantı aynı emri yollar: doğal anahtar eler
        await ws.wait_closed()

    stream, rows, db, _ = run_stream(tmp_path, handler, lambda s, r: s.rotations >= 1,
                                     ws_rotate_s=0.3, ws_overlap_s=0.1, ws_gap_min_s=0)
    sessions = db.query("SELECT open_ms, close_ms, reason FROM ws_sessions ORDER BY conn_id")
    assert sessions[0][2] == "rotate"
    assert sessions[1][0] <= sessions[0][1]       # yeni bağlantı eskisi kapanmadan açıldı
    assert db.gaps("bn_liq") == []                 # örtüşme: boşluk yok
    assert db.insert_liquidations(rows) == 1


def test_connect_failure_backs_off_and_keeps_trying(tmp_path):
    attempts = {"n": 0}

    async def failing_connect(url, **kwargs):
        attempts["n"] += 1
        raise OSError("bağlantı reddedildi")

    c = cfg(binance={"ws_backoff_max_s": 0.02})["binance"]
    db = DerivsDB(tmp_path / "d.sqlite")
    status = Status()

    async def main():
        stream = LiquidationStream("ws://127.0.0.1:9/x", db, RealClock(), c, status, lambda r: None,
                                   connect=failing_connect)
        stop = asyncio.Event()
        task = asyncio.create_task(stream.run(stop))
        await asyncio.sleep(0.3)
        stop.set()
        await asyncio.wait_for(task, 2)

    asyncio.run(main())
    assert attempts["n"] >= 3 and status.ws_down_since_ms is not None
    assert db.query("SELECT COUNT(*) FROM ws_sessions")[0][0] == 0
