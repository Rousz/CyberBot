"""Likidasyon WS istemcisi: 127.0.0.1'de gerçek websockets sunucusu (internet yok)."""

import asyncio
import json
import sqlite3

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


async def ack(ws):
    """Binance gibi: SUBSCRIBE'a {"result": null, "id": n} cevabı."""
    msg = json.loads(await ws.recv())
    await ws.send(json.dumps({"result": None, "id": msg["id"]}))
    return msg


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
        await ack(ws)
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
        await ack(ws)
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


def test_rejected_subscription_is_not_counted_as_coverage(tmp_path):
    """Abonelik hata cevabı = bağlanamadı: oturum (kapsama) yok, kopukluk sürer (izleme uyarır)."""
    attempts = {"n": 0}

    async def handler(ws):
        attempts["n"] += 1
        msg = json.loads(await ws.recv())
        await ws.send(json.dumps({"error": {"code": 2, "msg": "Invalid request"}, "id": msg["id"]}))
        await ws.wait_closed()

    stream, rows, db, status = run_stream(tmp_path, handler, lambda s, r: attempts["n"] >= 2)
    assert db.query("SELECT COUNT(*) FROM ws_sessions")[0][0] == 0
    assert status.ws_down_since_ms is not None


def test_missing_ack_times_out_and_early_data_is_kept(tmp_path):
    attempts = {"n": 0}

    async def handler(ws):
        attempts["n"] += 1
        msg = json.loads(await ws.recv())
        if attempts["n"] == 1:
            await ws.wait_closed()  # hiç cevap yok
            return
        await ws.send(json.dumps(force_order(t=T0 + 7)))  # onaydan önce gelen veri kaybolmaz
        await ws.send(json.dumps({"result": None, "id": msg["id"]}))
        await ws.wait_closed()

    stream, rows, db, status = run_stream(tmp_path, handler, lambda s, r: len(r) >= 1, timeout=8.0,
                                          ws_ack_timeout_s=0.3)
    assert attempts["n"] >= 2 and rows[0]["trade_ms"] == T0 + 7
    assert db.query("SELECT COUNT(*) FROM ws_sessions")[0][0] == 1
    assert rows[0]["conn_id"] == db.query("SELECT conn_id FROM ws_sessions")[0][0]


def test_silent_stream_reconnects_and_marks_silence_uncovered(tmp_path):
    """Bağlantı açık ama hiç forceOrder yok: oturum son mesaj anında kapanır, yeniden bağlanılır."""
    count = {"n": 0}

    async def handler(ws):
        count["n"] += 1
        await ack(ws)
        if count["n"] == 1:
            await ws.send(json.dumps(force_order(t=T0 + 1)))
        await ws.wait_closed()  # sonra sessiz

    stream, rows, db, status = run_stream(tmp_path, handler, lambda s, r: s.silent_closes >= 1 and count["n"] >= 2,
                                          timeout=8.0, ws_silence_s=0.4, ws_gap_min_s=0)
    sessions = db.query("SELECT conn_id, open_ms, close_ms, reason FROM ws_sessions ORDER BY conn_id")
    assert sessions[0][3] == "silent"
    first_msg_ms = rows[0]["recv_ms"]
    assert sessions[0][2] == first_msg_ms        # kapsama son mesajda biter (sessiz süre kapsanmaz)
    assert stream.reagg_from_ms == first_msg_ms  # kovalar o andan yeniden hesaplanacak
    gaps = db.gaps("bn_liq")
    assert gaps and gaps[0][2] == first_msg_ms and gaps[0][-1] == "unrecoverable"


def test_db_error_after_open_closes_connection_and_raises(tmp_path):
    """_after_open içinde DB hatası: run() hatayla biter (kaydedici yeniden başlatır), soket sızmaz."""
    from tests.recorder_fakes import FakeWsFactory

    c = cfg(binance={"ws_backoff_max_s": 0.02})["binance"]
    db = DerivsDB(tmp_path / "d.sqlite")
    ws = FakeWsFactory([[]])

    def broken():
        raise sqlite3.OperationalError("disk I/O error")

    db.ws_open_sessions = broken

    async def main():
        stream = LiquidationStream("ws://x", db, RealClock(), c, Status(), lambda r: None, connect=ws)
        with pytest.raises(sqlite3.OperationalError):
            await asyncio.wait_for(stream.run(asyncio.Event()), 2)

    asyncio.run(main())
    assert ws.connections[0].closed
    assert db.query("SELECT reason FROM ws_sessions WHERE close_ms IS NOT NULL") == [("error",)]
