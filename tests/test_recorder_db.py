"""derivs.sqlite: şema (ARCHITECTURE.md sözleşmesi), upsert, avail_ms, likidasyon kovaları, boşluklar."""

import re
import sqlite3
from pathlib import Path

import pytest

from cyberbot.recorder.db import BN_ENDPOINTS, DerivsDB, coverage_per_bucket, parse_bn_rows
from tests.recorder_fakes import T0, load

ARCH = Path(__file__).resolve().parent.parent / "docs" / "ARCHITECTURE.md"
MIN = 60_000
BAR = 300_000


def contract_tables() -> dict[str, set[str]]:
    """ARCHITECTURE.md 'derivs.sqlite şeması' tablosundaki tablo ve sütun adları
    (birincil anahtar ve UNIQUE dahil): her `...` parçasındaki virgülle ayrılmış adlar."""
    text = ARCH.read_text(encoding="utf-8")
    section = text.split("## derivs.sqlite", 1)[1].split("\n## ", 1)[0]
    tables = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or not cells[0].startswith("`"):
            continue
        cols = set()
        for span in re.findall(r"`([^`]*)`", cells[1] + " " + cells[2]):
            for piece in span.split(","):
                match = re.search(r"[a-z_]+", piece)
                if match:
                    cols.add(match.group(0))
        tables[cells[0].strip("`")] = cols
    return tables


def contract_keys() -> dict[str, list[str]]:
    """Birincil anahtar hücresinin ilk `...` parçası: '(symbol, period, ts_ms)' -> [...]."""
    text = ARCH.read_text(encoding="utf-8").split("## derivs.sqlite", 1)[1].split("\n## ", 1)[0]
    keys = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("`"):
            first = re.findall(r"`([^`]*)`", cells[1])[0]
            keys[cells[0].strip("`")] = [p.strip(" ()") for p in first.split(",")]
    return keys


def columns(db: DerivsDB, table: str) -> set[str]:
    return {row[1] for row in db.query(f"PRAGMA table_info({table})")}


@pytest.fixture
def db(tmp_path):
    d = DerivsDB(tmp_path / "derivs.sqlite")
    yield d
    d.close()


def test_schema_matches_architecture_contract(db):
    contract = contract_tables()
    assert len(contract) == 10
    assert {"symbol", "period", "ts_ms"} <= contract["bn_futures_data"]
    assert {"source", "symbol", "start_ms", "state"} <= contract["gaps"]
    for table, cols in contract.items():
        assert cols <= columns(db, table), (table, cols - columns(db, table))


def test_primary_keys_match_contract(db):
    for table, key in contract_keys().items():
        pk = [r[1] for r in sorted(db.query(f"PRAGMA table_info({table})"), key=lambda r: r[5]) if r[5]]
        assert pk == key, table
    uniques = db.query("SELECT sql FROM sqlite_master WHERE name='gaps'")[0][0]
    assert "UNIQUE(source, symbol, start_ms)" in uniques


def test_schema_idempotent_wal_and_without_rowid(tmp_path):
    path = tmp_path / "d.sqlite"
    DerivsDB(path).close()
    db = DerivsDB(path)  # ikinci açılış hata vermez
    assert db.query("PRAGMA journal_mode")[0][0] == "wal"
    sql = dict(db.query("SELECT name, sql FROM sqlite_master WHERE type='table'"))
    for t in ("bn_futures_data", "bn_liquidations", "bn_liq_1m", "weex_premium", "weex_oi", "weex_funding_hist"):
        assert "WITHOUT ROWID" in sql[t]
    db.close()


def test_parse_bn_rows_attaches_symbol_and_skips_others():
    fx = load("binance/futures_data.json")
    rows = parse_bn_rows("takerlongshortRatio", "BTCUSDT", fx["takerlongshortRatio"])
    assert rows == [(1775597400000, {"tk_ratio": 1.0412, "tk_buy_vol": 1234.567, "tk_sell_vol": 1185.701})]
    assert parse_bn_rows("openInterestHist", "ETHUSDT", fx["openInterestHist"]) == []
    assert parse_bn_rows("openInterestHist", "BTCUSDT", "not a list") == []


def test_bn_upsert_idempotent_merges_columns_and_avail(db):
    fx = load("binance/futures_data.json")
    ts = 1775597400000
    now = ts + 400_000
    for endpoint in BN_ENDPOINTS:
        db.upsert_bn_futures(endpoint, "BTCUSDT", "5m", fx[endpoint], now_ms=now, safety_ms=60_000, live=True)
    db.upsert_bn_futures("openInterestHist", "BTCUSDT", "5m", fx["openInterestHist"], now_ms=now + 5,
                         safety_ms=60_000, live=True)  # tekrar: idempotent
    rows = db.query("SELECT * FROM bn_futures_data")
    assert len(rows) == 1
    cur = db.conn.execute("SELECT oi_qty, oi_value, cmc_supply, gl_ratio, ta_long, tp_short, tk_ratio, avail_ms,"
                          " first_seen_ms, updated_ms FROM bn_futures_data")
    oi_qty, oi_value, cmc, gl, ta_long, tp_short, tk, avail, first_seen, updated = cur.fetchone()
    assert (oi_qty, oi_value, cmc) == (81234.123, 6012345678.9, 19950000.0)
    assert (gl, ta_long, tp_short, tk) == (1.8105, 0.5891, 0.4716, 1.0412)
    assert avail == ts + BAR + 60_000           # ts + period + safety
    assert first_seen == now and updated == now + 5
    assert db.bn_last_ts("5m")[("BTCUSDT", "takerlongshortRatio")] == ts


def test_first_seen_only_for_live_recent_rows(db):
    rows = [{"symbol": "X", "sumOpenInterest": "1", "sumOpenInterestValue": "2", "timestamp": T0},
            {"symbol": "X", "sumOpenInterest": "1", "sumOpenInterestValue": "2", "timestamp": T0 + 10 * BAR}]
    db.upsert_bn_futures("openInterestHist", "X", "5m", rows[:1], now_ms=T0 + 11 * BAR, safety_ms=0, live=False)
    db.upsert_bn_futures("openInterestHist", "X", "5m", rows, now_ms=T0 + 11 * BAR, safety_ms=0, live=True)
    got = dict(db.query("SELECT ts_ms, first_seen_ms FROM bn_futures_data"))
    assert got == {T0: None, T0 + 10 * BAR: T0 + 11 * BAR}
    # başka bir uç noktanın satırları OI sütunlarına dokunmaz
    db.upsert_bn_futures("globalLongShortAccountRatio", "X", "5m",
                         [{"symbol": "X", "longShortRatio": "2", "longAccount": ".66", "shortAccount": ".33",
                           "timestamp": T0}], now_ms=T0 + 12 * BAR, safety_ms=0, live=True)
    assert db.query("SELECT oi_qty, gl_ratio FROM bn_futures_data WHERE ts_ms=?", (T0,)) == [(1.0, 2.0)]


def liq(symbol="BTCUSDT", t=T0 + 10_000, side="SELL", price=100.0, qty=1.0, notional=100.0):
    return {"symbol": symbol, "trade_ms": t, "side": side, "price": price, "qty": qty, "event_ms": t,
            "avg_price": price, "last_qty": qty, "filled_qty": qty, "status": "FILLED", "order_type": "LIMIT",
            "tif": "IOC", "ps": "BOTH", "st": 1, "notional": notional, "recv_ms": t + 50, "conn_id": 1}


def test_liquidations_natural_key_dedup(db):
    assert db.insert_liquidations([liq(), liq(side="BUY")]) == 2
    assert db.insert_liquidations([liq(), liq(price=101.0)]) == 1  # aynısı (rotasyon örtüşmesi) atlanır
    assert db.query("SELECT COUNT(*) FROM bn_liquidations")[0][0] == 3


def test_coverage_per_bucket_union_of_overlapping_sessions():
    cov = coverage_per_bucket([(T0 + 30_000, T0 + 90_000), (T0 + 80_000, T0 + 100_000)], T0, T0 + 3 * MIN)
    assert cov == {T0: 0.5, T0 + MIN: pytest.approx(40_000 / MIN, abs=1e-4), T0 + 2 * MIN: 0.0}


def test_aggregate_liq_1m_with_coverage(db):
    cid = db.ws_open("wss://x", T0 + 30_000)
    db.insert_liquidations([liq(t=T0 + 40_000, side="SELL", notional=1000.0),
                            liq(t=T0 + 50_000, side="BUY", notional=300.0, price=99.0),
                            liq(t=T0 + 55_000, side="SELL", notional=500.0, price=98.0),
                            liq(symbol="ETHUSDT", t=T0 + 70_000, side="BUY", notional=50.0)])
    now = T0 + 2 * MIN + 1000
    db.aggregate_liq_1m(T0, now, now)
    rows = {(s, b): rest for s, b, *rest in db.query("SELECT * FROM bn_liq_1m ORDER BY symbol, bucket_ms")}
    assert rows[("BTCUSDT", T0)] == [1500.0, 300.0, 2, 1, 1000.0, 0.5, T0 + MIN]  # SELL = long likide
    assert rows[("ETHUSDT", T0 + MIN)][:4] == [0.0, 50.0, 0, 1]
    assert rows[("ETHUSDT", T0 + MIN)][5] == 1.0  # oturum hâlâ açık: dakika tam kapsandı
    assert dict(db.query("SELECT bucket_ms, coverage FROM bn_liq_coverage_1m")) == {T0: 0.5, T0 + MIN: 1.0}
    db.aggregate_liq_1m(T0, now, now)  # idempotent
    assert db.query("SELECT COUNT(*) FROM bn_liq_1m")[0][0] == 2
    db.ws_close(cid, T0 + 90_000, "test")
    assert db.ws_open_sessions() == 0 and db.ws_last_close_ms() == T0 + 90_000


def test_dangling_ws_sessions_closed_conservatively(db):
    db.ws_open("wss://x", T0)
    db.ws_open("wss://x", T0 + 100)
    assert db.ws_close_dangling(T0 + 50) == 2
    assert db.query("SELECT close_ms, reason FROM ws_sessions ORDER BY conn_id") == [(T0 + 50, "crash"),
                                                                                    (T0 + 100, "crash")]


def test_gaps_unique_and_state_change(db):
    db.add_gap("bn_futures", "BTCUSDT", T0, T0 + BAR, "downtime", "open", T0)
    db.add_gap("bn_futures", "BTCUSDT", T0, T0 + 2 * BAR, "downtime", "open", T0)  # aynı başlangıç: güncellenir
    db.add_gap("weex_oi", None, T0, T0 + BAR, "missed", "unrecoverable", T0)
    db.add_gap("weex_oi", None, T0, T0 + BAR, "missed", "unrecoverable", T0)  # '*' ile NULL tekrarı yok
    db.add_gap("weex_oi", None, T0, T0, "x", "unrecoverable", T0)  # boş aralık yazılmaz
    assert db.gaps("bn_futures") == [("bn_futures", "BTCUSDT", T0, T0 + 2 * BAR, "downtime", "open")]
    assert len(db.gaps("weex_oi")) == 1
    assert db.set_gap_state("bn_futures", "BTCUSDT", "open", "backfilled") == 1
    assert db.gaps("bn_futures")[0][-1] == "backfilled"


def test_fetch_log_retention_and_heartbeat(db):
    day = 86_400_000
    db.log_fetches([(T0 - 8 * day, "a", "X", 200, 5, 1, 3, 0), (T0 - day, "b", "X", 200, 5, 1, None, 1)])
    assert db.prune_fetch_log(T0, 7) == 1
    assert db.query("SELECT endpoint FROM fetch_log") == [("b",)]
    db.heartbeat_err("weex", T0, "boom")
    db.heartbeat_err("weex", T0 + 1, "boom")
    assert db.heartbeat("weex") == (None, T0 + 1, "boom", 2)
    db.heartbeat_ok("weex", T0 + 2)
    assert db.heartbeat("weex")[0] == T0 + 2 and db.heartbeat("weex")[3] == 0


def test_weex_upserts_and_reader_can_open_read_only(db, tmp_path):
    db.upsert_weex_premium([{"symbol": "BTCUSDT", "bucket_ms": T0, "server_ms": T0, "recv_ms": T0 + 5, "mark": 1.0,
                             "idx": 1.0, "last_funding": 0.1, "forecast_funding": 0.2, "interest_rate": 0.0,
                             "next_funding_ms": T0 + 1, "collect_cycle_min": 480, "avail_ms": T0 + 5}])
    db.upsert_weex_funding([{"symbol": "BTCUSDT", "funding_ms": T0, "rate": 0.1, "mark": 1.0, "recv_ms": T0 + 9,
                             "avail_ms": T0}])
    assert db.weex_last_funding() == {"BTCUSDT": T0}
    ro = sqlite3.connect(f"file:{tmp_path / 'derivs.sqlite'}?mode=ro", uri=True)
    assert ro.execute("SELECT mark FROM weex_premium").fetchone() == (1.0,)
    ro.close()
