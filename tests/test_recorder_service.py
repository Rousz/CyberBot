"""Uçtan uca: sahte HTTP + sahte WS + sahte saat ile birkaç tur; tablolar dolar, kapanış düzgün."""

import asyncio
import json

from cyberbot.recorder.service import Recorder
from cyberbot.uptime import UptimeStore
from tests.recorder_fakes import BAR, HOUR, MIN, T0, FakeClock, FakeHttp, FakeWsFactory, cfg, force_order, mon_cfg

START = T0 + 10 * HOUR + 12_000
FAST = {"binance": {"max_rps": 1000}, "weex": {"max_rps": 1000}}


def make(tmp_path, clock, http, ws=None, sent=None, **sections):
    conf = cfg(**{**FAST, **sections})
    return Recorder(conf, mon_cfg(), clock=clock, http_binance=http, http_weex=http,
                    ws_connect=ws or FakeWsFactory([]), send=(sent.append if sent is not None else None),
                    db_path=tmp_path / "derivs.sqlite", uptime_path=tmp_path / "uptime.sqlite",
                    perps_json_path=tmp_path / "binance_perps.json")


async def run_until(rec, clock, end_ms, step_ms=1_000):
    t = clock.now_ms()
    while t < end_ms:
        t = max(t + step_ms, clock.now_ms())
        clock.set(t)
        await rec.tick()
        await rec.drain()
        await asyncio.sleep(0)


def count(rec_db_path, sql):
    import sqlite3

    conn = sqlite3.connect(rec_db_path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def test_end_to_end_a_few_cycles(tmp_path):
    clock = FakeClock(START)
    http = FakeHttp(clock)
    ws = FakeWsFactory([[{"result": None, "id": 1}, force_order(t=START + 1_000),
                         force_order(symbol="BTCUSD_PERP", st=2, t=START + 2_000)]])
    sent: list[str] = []
    rec = make(tmp_path, clock, http, ws, sent)

    async def main():
        await rec.start(background=False, heartbeat=False)
        planned = len(rec.binance.queue)
        rec.start_background(backfill=False)
        await run_until(rec, clock, START + 400_000)
        for _ in range(7):  # birkaç geçmiş doldurma isteği (BTC önce)
            await rec.binance.backfill_once()
        await rec.shutdown()
        return planned

    planned = asyncio.run(main())
    db = tmp_path / "derivs.sqlite"

    # semboller ve eşleme
    perps = json.loads((tmp_path / "binance_perps.json").read_text(encoding="utf-8"))
    assert perps["pairs"]["BTC/USDT:USDT"]["binance_symbol"] == "BTCUSDT"
    assert perps["pairs"]["PEPE/USDT:USDT"] == {"binance_symbol": "1000PEPEUSDT", "multiplier": 1000.0,
                                                "method": "prefix_1000"}
    assert "COLL/USDT:USDT" not in perps["pairs"]
    assert rec.tracked[:2] == ["BTCUSDT", "ETHUSDT"] and "USDCUSDT" not in rec.tracked
    assert count(db, "SELECT COUNT(*) FROM symbol_map WHERE active=1") == len(rec.tracked) == 6
    assert len(http.calls_to("ticker/24hr")) == 1  # pahalı uç: açılışta bir kez

    # WEEX
    assert count(db, "SELECT COUNT(DISTINCT symbol) FROM weex_premium") == 6
    assert count(db, "SELECT COUNT(*) FROM weex_premium WHERE avail_ms = recv_ms") == \
        count(db, "SELECT COUNT(*) FROM weex_premium")
    assert count(db, "SELECT COUNT(*) FROM weex_oi") == 6
    oi_recv = count(db, "SELECT MIN(recv_ms) FROM weex_oi")
    assert (oi_recv - oi_recv % BAR + BAR) - oi_recv <= 30_000      # mum kapanışından ~30 sn önce
    assert count(db, "SELECT COUNT(DISTINCT symbol) FROM weex_funding_hist") == 6
    assert count(db, "SELECT COUNT(*) FROM weex_funding_hist WHERE avail_ms <> funding_ms") == 0

    # Binance canlı tur (+30 sn) ve geçmiş doldurma
    live = [(t, p) for t, (u, p) in zip(http.times, http.calls) if "/futures/data/" in u and "endTime" not in p]
    assert len(live) == 2 * 4 * 5  # iki tur (+30 sn ve +330 sn): BTC, ETH, SOL, 1000PEPE x 5 uç
    bar = START - START % BAR
    assert 0 <= live[0][0] - (bar + 30_000) < 1_100            # mum sınırı + 30 sn (tick 1 sn)
    assert 0 <= live[20][0] - (bar + BAR + 30_000) < 1_100
    assert live[20][1]["startTime"] == bar - BAR  # ikinci tur: son kayıtlı ts'den
    assert count(db, "SELECT COUNT(DISTINCT symbol) FROM bn_futures_data") == 4
    assert count(db, "SELECT COUNT(*) FROM bn_futures_data WHERE (oi_qty IS NULL OR tk_ratio IS NULL"
                     " OR gl_ratio IS NULL OR ta_ratio IS NULL OR tp_ratio IS NULL)"
                     f" AND ts_ms >= {bar - 499 * BAR}") == 0
    assert count(db, "SELECT COUNT(*) FROM bn_futures_data WHERE avail_ms <> ts_ms + 360000") == 0
    assert planned == 4 * 5 * 16
    backfill = [p for u, p in http.calls if "/futures/data/" in u and "endTime" in p]
    assert len(backfill) == 7 and {p["symbol"] for p in backfill} == {"BTCUSDT"}
    assert len({p["startTime"] for p in backfill}) == 2  # en eski dilim 5 uç için, sonra ikinci dilim

    # likidasyonlar (st=2 atıldı), 1 dk kovası, WS oturumu
    assert count(db, "SELECT COUNT(*) FROM bn_liquidations") == 1
    assert count(db, "SELECT COUNT(*) FROM bn_liq_1m") == 1
    assert count(db, "SELECT long_liq_usd FROM bn_liq_1m") > 0
    assert count(db, "SELECT COUNT(*) FROM bn_liq_coverage_1m") >= 5
    assert count(db, "SELECT reason FROM ws_sessions") == "shutdown"
    assert json.loads(ws.connections[0].sent[0])["params"] == ["!forceOrder@arr"]

    # sağlık, istek günlüğü, uptime, izleme
    assert count(db, "SELECT COUNT(*) FROM heartbeat WHERE component IN ('weex','binance_rest','recorder')") == 3
    assert count(db, "SELECT COUNT(*) FROM fetch_log") == len(http.calls)
    (session,) = UptimeStore(tmp_path / "uptime.sqlite", "recorder").sessions()
    assert session.stop_kind == "clean" and session.stopped_ms is not None
    # testte freqtrade yok: açılış süresi (300 sn) dolunca sadece 'Bot çalışmıyor' uyarısı, tek sefer
    assert len(sent) == 1 and sent[0].startswith("UYARI: Bot çalışmıyor")
    assert http.closed


def test_restart_records_unrecoverable_and_backfillable_gaps(tmp_path):
    clock = FakeClock(START)
    http = FakeHttp(clock)

    async def first():
        rec = make(tmp_path, clock, http, FakeWsFactory([[]]))
        await rec.start(background=False, heartbeat=False)
        rec.start_background(backfill=False)
        await run_until(rec, clock, START + 400_000)
        await rec.shutdown()

    async def second():
        rec = make(tmp_path, clock, http, FakeWsFactory([[]]))
        await rec.start(background=False, heartbeat=False)
        rec.start_background(backfill=False)
        await run_until(rec, clock, clock.now_ms() + 120_000)
        gaps = rec.db.gaps()
        await rec.shutdown()
        return gaps

    asyncio.run(first())
    clock.set(clock.now_ms() + 3 * HOUR)  # 3 saat kapalı
    gaps = asyncio.run(second())
    by_source = {}
    for source, symbol, start, end, reason, state in gaps:
        by_source.setdefault(source, []).append((symbol, state, end - start))
    assert by_source["weex_premium"][0][1] == "unrecoverable" and by_source["weex_premium"][0][2] >= 3 * HOUR - 2 * MIN
    assert by_source["bn_liq"][0][1] == "unrecoverable"
    assert {s for s, _, _ in by_source["bn_futures"]} == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT"}
    assert all(state == "open" for _, state, _ in by_source["bn_futures"])  # canlı tur henüz gelmedi
    sessions = UptimeStore(tmp_path / "uptime.sqlite", "recorder").sessions()
    assert [s.stop_kind for s in sessions] == ["clean", "clean"]


def test_weex_outage_alerts_after_grace_and_sources_keep_running(tmp_path):
    clock = FakeClock(START)
    http = FakeHttp(clock)
    sent: list[str] = []

    async def main():
        rec = make(tmp_path, clock, http, sent=sent)
        await rec.start(background=False, heartbeat=False)
        UptimeStore(tmp_path / "uptime.sqlite", "freqtrade").start_session(at_ms=START + 10 * MIN)  # bot canlı
        http.fail["api-contract.weex.com"] = ConnectionError("WEEX yok")
        await run_until(rec, clock, START + 11 * MIN)
        rows = rec.db.query("SELECT COUNT(*) FROM bn_futures_data")[0][0]
        await rec.shutdown()
        return rows

    bn_rows = asyncio.run(main())
    assert any("WEEX'e ulaşılamıyor" in m for m in sent)
    assert bn_rows > 0  # WEEX hatası Binance kaydını durdurmadı
    kinds = [e.kind for e in UptimeStore(tmp_path / "uptime.sqlite", "recorder").events()]
    assert "weex_unreachable" in kinds


def test_binance_down_at_start_keeps_weex_and_retries_symbols(tmp_path):
    clock = FakeClock(START)
    http = FakeHttp(clock)
    http.fail["/fapi/v1/"] = 503

    async def main():
        rec = make(tmp_path, clock, http)
        await rec.start(background=False, heartbeat=False)
        retry_due = rec.due["symbols"] - START
        await run_until(rec, clock, START + 100_000)
        state = (retry_due, rec.binance_symbols(), rec.db.query("SELECT COUNT(*) FROM weex_premium")[0][0])
        await rec.shutdown()
        return state

    retry_due, bn, weex_rows = asyncio.run(main())
    assert retry_due <= 300_000 + 1000 and bn == [] and weex_rows > 0
    assert not (tmp_path / "binance_perps.json").exists()


def test_binance_retry_does_not_repeat_expensive_weex_ticker(tmp_path):
    clock = FakeClock(START)
    http = FakeHttp(clock)
    http.fail["/fapi/v1/"] = 503

    async def main():
        rec = make(tmp_path, clock, http)
        await rec.start(background=False, heartbeat=False)
        http.fail.clear()  # Binance düzeldi
        await run_until(rec, clock, START + 400_000)
        bn = rec.binance_symbols()
        await rec.shutdown()
        return bn

    bn = asyncio.run(main())
    assert len(http.calls_to("ticker/24hr")) == 1          # 5 dk sonraki tekrar sadece Binance'i sordu
    assert len(http.calls_to("/fapi/v1/exchangeInfo")) == 2
    assert "BTCUSDT" in bn and (tmp_path / "binance_perps.json").exists()


def test_missing_weex_prices_never_overwrite_good_perps_json(tmp_path):
    clock = FakeClock(START)
    http = FakeHttp(clock)
    good = {"generated_ms": 1, "pairs": {"BTC/USDT:USDT": {"binance_symbol": "BTCUSDT", "multiplier": 1.0,
                                                          "method": "exact"}}}
    (tmp_path / "binance_perps.json").write_text(json.dumps(good), encoding="utf-8")
    http.fail["premiumIndex"] = 503  # WEEX ve Binance premiumIndex yok

    async def main():
        rec = make(tmp_path, clock, http)
        await rec.start(background=False, heartbeat=False)
        await rec.shutdown()

    asyncio.run(main())
    assert json.loads((tmp_path / "binance_perps.json").read_text(encoding="utf-8")) == good


def test_live_cycle_skipped_while_banned(tmp_path):
    clock = FakeClock(START)
    http = FakeHttp(clock)

    async def main():
        rec = make(tmp_path, clock, http)
        await rec.start(background=False, heartbeat=False)
        rec.binance.limiter.pause(3600, clock.now_ms(), "HTTP 418")
        n = len(http.calls)
        stats = await rec.binance.live_cycle(START - START % BAR, rec.binance_symbols(), START)
        await rec.shutdown()
        return stats, len(http.calls) - n

    stats, new_calls = asyncio.run(main())
    assert stats["skipped"] and new_calls == 0


def test_run_stops_cleanly_on_request_stop(tmp_path):
    clock = FakeClock(START)
    http = FakeHttp(clock)
    ws = FakeWsFactory([[force_order(t=START + 1)]])
    rec = make(tmp_path, clock, http, ws, tick_s=0.01)

    async def main():
        task = asyncio.create_task(rec.run())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if ws.connections:
                break
        rec.request_stop()  # SIGTERM/SIGINT işleyicisi bunu çağırır
        await asyncio.wait_for(task, 15)

    asyncio.run(main())
    (session,) = UptimeStore(tmp_path / "uptime.sqlite", "recorder").sessions()
    assert session.stop_kind == "clean"
    assert count(tmp_path / "derivs.sqlite", "SELECT COUNT(*) FROM bn_liquidations") == 1  # tampon yazıldı
    assert count(tmp_path / "derivs.sqlite", "SELECT reason FROM ws_sessions") == "shutdown"
    assert ws.connections[0].closed
