"""Kaynaklar: likidasyon ayrıştırma, WEEX ayrıştırma, zamanlama, Binance canlı tur, 429/418, geçmiş doldurma."""

import asyncio

import pytest

from cyberbot.recorder import binance_rest as br
from cyberbot.recorder.binance_ws import backoff_s, iter_payloads, parse_force_order
from cyberbot.recorder.db import DerivsDB
from cyberbot.recorder.monitor import Status
from cyberbot.recorder.service import next_aligned
from cyberbot.recorder.weex_poll import FundingSchedule, is_error_payload, oi_due_ms, parse_funding, parse_oi, \
    parse_premium
from tests.recorder_fakes import BAR, DAY, MIN, T0, FakeClock, FakeHttp, cfg, force_order, load

# --- likidasyon ayrıştırma ------------------------------------------------------


def test_force_order_keeps_um_only_and_computes_notional():
    row = parse_force_order(force_order(ap="100.5", z="2"), T0 + 99, 7)
    assert row["symbol"] == "BTCUSDT" and row["side"] == "SELL" and row["trade_ms"] == T0
    assert row["notional"] == pytest.approx(201.0) and row["st"] == 1 and row["conn_id"] == 7
    assert row["recv_ms"] == T0 + 99 and row["event_ms"] == T0 + 5 and row["status"] == "FILLED"
    assert parse_force_order(force_order(st=2), T0, 1) is None          # COIN-M
    assert parse_force_order(force_order(st="1"), T0, 1) is not None
    assert parse_force_order(force_order(st=None), T0, 1)["st"] is None  # alan yoksa (eski biçim) kabul
    assert parse_force_order({"stream": "x", "data": force_order()}, T0, 1) is not None
    assert parse_force_order({"e": "kline"}, T0, 1) is None
    bad = force_order()
    bad["o"]["S"] = "?"
    assert parse_force_order(bad, T0, 1) is None


def test_iter_payloads_handles_lists_and_garbage():
    assert iter_payloads('[{"a":1},{"b":2}]') == [{"a": 1}, {"b": 2}]
    assert iter_payloads("not json") == []


def test_backoff_is_exponential_jittered_and_capped():
    assert backoff_s(1, 60, rng=lambda: 1.0) == 1.0
    assert backoff_s(3, 60, rng=lambda: 1.0) == 4.0
    assert backoff_s(10, 60, rng=lambda: 1.0) == 60.0
    assert backoff_s(10, 60, rng=lambda: 0.0) == 30.0


# --- WEEX ayrıştırma ------------------------------------------------------------


def test_weex_premium_parse_raw_fields_and_bucket():
    recv = T0 + 2 * MIN + 2_345
    rows = parse_premium(load("weex/premiumIndex.json"), recv, {"BTCUSDT"})
    assert rows == [{"symbol": "BTCUSDT", "bucket_ms": T0 + 2 * MIN, "server_ms": 1775597594265, "recv_ms": recv,
                     "mark": 74011.0, "idx": 74020.3, "last_funding": 0.00001031, "forecast_funding": 0.00005618,
                     "interest_rate": 0.001, "next_funding_ms": 1775606400000, "collect_cycle_min": 480,
                     "avail_ms": recv}]
    assert parse_premium(load("weex/premiumIndex.json"), recv, {"ETHUSDT"}) == []


def test_weex_oi_and_funding_parse():
    recv = T0 + BAR - 29_000
    row = parse_oi(load("weex/openInterest.json"), "BTCUSDT", recv, 74011.0)
    assert row["oi_raw"] == 51234.567 and row["bucket_ms"] == T0 and row["avail_ms"] == recv
    assert row["server_ms"] == 1775595582598 and row["mark"] == 74011.0
    assert parse_oi({"symbol": "BTCUSDT"}, "BTCUSDT", recv, None) is None
    rows = parse_funding([{"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingTime": str(T0), "markPrice": "9"},
                          {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingTime": str(T0 + DAY)}], "BTCUSDT",
                         T0 + 1000)
    assert rows == [{"symbol": "BTCUSDT", "funding_ms": T0, "rate": 0.0001, "mark": 9.0, "recv_ms": T0 + 1000,
                     "avail_ms": T0}]  # gelecekteki satır atlandı; avail = ödeme anı


def test_weex_error_payload_detection():
    assert is_error_payload({"code": "-1121", "msg": "Invalid symbol"})
    assert not is_error_payload({"code": "200", "msg": "success"})
    assert not is_error_payload([{"symbol": "X"}])


# --- zamanlama ------------------------------------------------------------------


def test_bar_boundary_plus_30s_and_retry_90s():
    assert next_aligned(T0 + 10_000, BAR, 30_000) == T0 + 30_000
    assert next_aligned(T0 + 30_000, BAR, 30_000) == T0 + BAR + 30_000  # tam anında: bir sonraki
    assert next_aligned(T0 + 299_000, BAR, 30_000) == T0 + BAR + 30_000
    assert next_aligned(T0 + 1, MIN, 2_000) == T0 + 2_000


def test_oi_at_close_minus_30s():
    assert oi_due_ms(T0, 30) == T0 + BAR - 30_000
    assert oi_due_ms(T0 + BAR - 30_000, 30) == T0 + 2 * BAR - 30_000
    assert oi_due_ms(T0 + BAR - 10_000, 30) == T0 + 2 * BAR - 30_000


def test_funding_schedule_after_settlement():
    sched = FundingSchedule(delay_ms=120_000)
    nf = T0 + 8 * 3_600_000
    assert sched.due(T0, ["BTCUSDT"]) == ["BTCUSDT"]  # açılışta bir kez
    sched.observe("BTCUSDT", nf)
    sched.mark("BTCUSDT", T0, ok=True)
    assert sched.due(T0 + 1000, ["BTCUSDT"]) == []
    assert sched.due(nf + 60_000, ["BTCUSDT"]) == []        # ödeme + 2 dk dolmadı
    sched.observe("BTCUSDT", nf + 8 * 3_600_000)            # premium sonraki ödemeyi gösteriyor
    assert sched.due(nf + 120_000, ["BTCUSDT"]) == ["BTCUSDT"]  # bekleyen ödeme unutulmadı
    sched.mark("BTCUSDT", nf + 121_000, ok=False)            # hata: 60 sn sonra tekrar
    assert sched.due(nf + 130_000, ["BTCUSDT"]) == []
    assert sched.due(nf + 190_000, ["BTCUSDT"]) == ["BTCUSDT"]
    sched.mark("BTCUSDT", nf + 190_000, ok=True)
    assert sched.due(nf + 200_000, ["BTCUSDT"]) == []
    sched.observe("BTCUSDT", nf + 8 * 3_600_000)
    assert sched.due(nf + 8 * 3_600_000 + 120_000, ["BTCUSDT"]) == ["BTCUSDT"]


# --- geçmiş doldurma planı -----------------------------------------------------


def test_backfill_plan_request_counts():
    now = T0 + 12_345
    ranges = br.plan_ranges(None, now, period_ms=BAR, limit=500, backfill_days=29.5)
    floor = br.live_floor(br.bar_open(now, BAR), BAR, 500)
    assert len(ranges) == 16                                   # 29.5 g = 8496 periyot; son 500'ü canlı alır
    assert ranges[0][0] >= now - int(29.5 * DAY) and ranges[0][0] % BAR == 0
    assert ranges[-1][1] < floor
    assert all(e - s <= 499 * BAR for s, e in ranges)
    assert all(b[0] - a[0] == 500 * BAR for a, b in zip(ranges, ranges[1:]))
    # kısa kesinti: canlı sorgu kapatır, doldurma yok
    assert br.plan_ranges(now - 10 * BAR, now, period_ms=BAR, limit=500, backfill_days=29.5) == []
    # 3 günlük kesinti
    assert len(br.plan_ranges(now - 3 * DAY, now, period_ms=BAR, limit=500, backfill_days=29.5)) == 1
    tasks = br.plan_backfill(["BTCUSDT", "ETHUSDT", "SOLUSDT"], {}, now, period_ms=BAR, limit=500,
                             backfill_days=29.5)
    assert len(tasks) == 3 * 5 * 16
    assert [t.symbol for t in sorted(tasks)][:80] == ["BTCUSDT"] * 80   # öncelik: BTC önce


def make_rest(tmp_path, clock, http, **bcfg):
    c = cfg(binance={"max_rps": 1000, **bcfg})["binance"]
    db = DerivsDB(tmp_path / "d.sqlite")
    return br.BinanceRest(http, db, c, clock, Status()), db


def test_live_cycle_uses_last_ts_and_retries_missing(tmp_path):
    clock = FakeClock(T0 + 30_000)

    class LateHttp(FakeHttp):
        @property
        def newest_lag_ms(self):  # en yeni satır +60 sn'de yayımlanır
            return BAR if self.clock.now_ms() >= T0 + 60_000 else 2 * BAR

        @newest_lag_ms.setter
        def newest_lag_ms(self, value):
            pass

    http = LateHttp(clock)
    rest, db = make_rest(tmp_path, clock, http)
    rest.last_ts[("BTCUSDT", "openInterestHist")] = T0 - 6 * BAR
    stats = asyncio.run(rest.live_cycle(T0, ["BTCUSDT"], T0 + 90_000))
    first = http.calls[0][1]
    assert first["startTime"] == T0 - 6 * BAR and first["limit"] == 500 and first["period"] == "5m"
    assert stats["missing"] == 5 and stats["still_missing"] == 0
    assert len(http.calls) == 10 and clock.now_ms() >= T0 + 90_000   # tekrar +90 sn'de
    assert rest.last_ts[("BTCUSDT", "takerlongshortRatio")] == T0 - BAR
    assert db.query("SELECT COUNT(*) FROM bn_futures_data WHERE tk_ratio IS NOT NULL AND gl_ratio IS NOT NULL"
                    " AND oi_qty IS NOT NULL")[0][0] == 6
    assert db.query("SELECT COUNT(*) FROM bn_futures_data WHERE first_seen_ms IS NOT NULL")[0][0] >= 1


def test_live_poll_without_history_starts_at_live_floor(tmp_path):
    clock = FakeClock(T0 + 30_000)
    http = FakeHttp(clock)
    rest, _ = make_rest(tmp_path, clock, http)
    assert asyncio.run(rest.poll_live("ETHUSDT", "openInterestHist", T0))
    assert http.calls[0][1]["startTime"] == T0 - 499 * BAR
    assert not rest.queue  # geçmişi olmayan anahtarı canlı tur planlamaz (sembol yenileme planlar)


def test_429_honours_retry_after_and_418_pauses_all(tmp_path):
    clock = FakeClock(T0)
    http = FakeHttp(clock)
    rest, _ = make_rest(tmp_path, clock, http)
    http.fail["/futures/data/"] = (429, {"retry-after": "42"})
    status, _ = asyncio.run(rest.get("/futures/data/openInterestHist", {"symbol": "X"}))
    assert status == 429 and rest.limiter.paused_until_ms == T0 + 42_000
    assert rest.status.binance_rest.consecutive_fail == 1
    clock.set(T0 + 50_000)
    http.fail = {"/fapi/v1/exchangeInfo": 418}
    status, _ = asyncio.run(rest.get("/fapi/v1/exchangeInfo"))
    assert status == 418 and rest.status.binance_ban_until_ms == T0 + 50_000 + 600_000
    http.fail = {}
    n = len(http.calls)

    async def later():
        await rest.get("/fapi/v1/premiumIndex")
        return clock.now_ms()

    t = asyncio.run(later())
    assert t >= T0 + 650_000 and len(http.calls) == n + 1  # yasak bitene kadar hiçbir Binance isteği yok


def test_network_error_and_4xx_never_raise(tmp_path):
    clock = FakeClock(T0)
    http = FakeHttp(clock)
    rest, db = make_rest(tmp_path, clock, http)
    http.fail["/futures/data/"] = ConnectionError("yok")
    assert asyncio.run(rest.get("/futures/data/openInterestHist")) == (0, None)
    http.fail["/futures/data/"] = 400
    assert asyncio.run(rest.get("/futures/data/openInterestHist")) == (400, None)
    assert rest.status.binance_rest.consecutive_fail == 0  # 400: sunucu cevap verdi
    assert len(rest.log_sink) == 2


def test_backfill_queue_runs_by_priority_and_marks_gap(tmp_path):
    now = T0 + 12_345
    clock = FakeClock(now)
    http = FakeHttp(clock)
    rest, db = make_rest(tmp_path, clock, http)
    for e in br.ENDPOINTS:
        rest.last_ts[("BTCUSDT", e)] = now - 3 * DAY
    rest.record_startup_gaps(["BTCUSDT"], now)
    assert db.gaps("bn_futures")[0][-1] == "open"
    rest.set_priority(["BTCUSDT", "ETHUSDT"])
    n = rest.plan(["ETHUSDT", "BTCUSDT"], now)
    assert n == 5 * 1 + 5 * 16

    async def main():
        done = []
        while await rest.backfill_once():
            done.append(http.calls[-1][1]["symbol"])
        return done

    order = asyncio.run(main())
    assert order[:5] == ["BTCUSDT"] * 5 and set(order[5:]) == {"ETHUSDT"}
    assert all("endTime" in p for _, p in http.calls)
    assert not rest.pending
    # canlı da yetişince boşluk 'backfilled'
    asyncio.run(rest.live_cycle(br.bar_open(now, BAR), ["BTCUSDT"], now))
    assert db.gaps("bn_futures")[0][-1] == "backfilled"


def test_old_downtime_split_into_unrecoverable_and_open(tmp_path):
    now = T0
    clock = FakeClock(now)
    rest, db = make_rest(tmp_path, clock, FakeHttp(clock))
    for e in br.ENDPOINTS:
        rest.last_ts[("BTCUSDT", e)] = now - 40 * DAY
    rest.record_startup_gaps(["BTCUSDT", "NEWUSDT"], now)
    states = [g[-1] for g in db.gaps("bn_futures")]
    assert states == ["unrecoverable", "open"]


def test_backfill_retries_transient_then_gives_up(tmp_path):
    clock = FakeClock(T0)
    http = FakeHttp(clock)
    rest, db = make_rest(tmp_path, clock, http, backfill_attempts=2, rate_limit_pause_s=1)
    rest.enqueue([br.BackfillTask(0, 0, "BTCUSDT", "openInterestHist", T0 - DAY, T0 - DAY + 499 * BAR)])
    http.fail["/futures/data/"] = 503

    async def main():
        while await rest.backfill_once():
            pass

    asyncio.run(main())
    assert len(http.calls) == 2 and not rest.pending and "BTCUSDT" in rest.failed


def test_live_requests_keep_priority_over_backfill(tmp_path):
    clock = FakeClock(T0 + 30_000)
    http = FakeHttp(clock)
    rest, _ = make_rest(tmp_path, clock, http)
    rest.limiter.min_gap_ms = 500
    rest.enqueue(br.plan_backfill(["ETHUSDT"], {}, T0, period_ms=BAR, limit=500, backfill_days=29.5))
    stop = asyncio.Event()

    async def main():
        worker = asyncio.create_task(rest.backfill_worker(stop))
        await asyncio.sleep(0)
        await rest.live_cycle(T0, ["BTCUSDT"], T0)
        stop.set()
        worker.cancel()

    asyncio.run(main())
    symbols = [p["symbol"] for _, p in http.calls]
    first_btc, last_btc = symbols.index("BTCUSDT"), len(symbols) - 1 - symbols[::-1].index("BTCUSDT")
    assert symbols[first_btc:last_btc + 1] == ["BTCUSDT"] * 5  # canlı tur kesintisiz
    assert first_btc <= 1


def test_low_cap_reserves_window_for_live(tmp_path):
    clock = FakeClock(T0)
    rest, _ = make_rest(tmp_path, clock, FakeHttp(clock))
    rest.set_low_cap(60)
    assert rest.limiter.low_cap == 700 - (int(300 * 1.3) + 10)
    rest.set_low_cap(1000)
    assert rest.limiter.low_cap == 50
