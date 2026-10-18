"""İzlenen semboller, WEEX -> Binance eşlemesi, binance_perps.json."""

import json

import pytest

from cyberbot.recorder import symbols as sm
from cyberbot.recorder.defaults import RECORDER_DEFAULTS
from tests.recorder_fakes import BN_EXTRA, BN_MARKS, WEEX_EXTRA, WEEX_MARKS, load

REGEXES = RECORDER_DEFAULTS["symbols"]["exclude_regexes"]
HOUR = 3_600_000


def weex_info():
    info = load("weex/exchangeInfo.json")
    info["symbols"] += WEEX_EXTRA
    return info


def bn_perps():
    info = load("binance/exchangeInfo.json")
    info["symbols"] += BN_EXTRA
    return sm.binance_usdt_perps(info)


def test_weex_universe_is_usdt_margined_usdt_perps():
    perps = sm.weex_usdt_perps(weex_info())
    assert perps["BTCUSDT"] == "BTC" and "PEPEUSDT" in perps
    assert "BTCUSD" not in perps  # coin teminatlı


def test_binance_perps_filter():
    perps = bn_perps()
    assert {"BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT"} <= set(perps)
    assert "BTCUSDT_261225" not in perps and "OLDUSDT" not in perps and "ETHUSDC" not in perps
    assert perps["BTCUSDT"] == 1569398400000


@pytest.mark.parametrize("base,excluded", [
    ("USDC", True), ("FDUSD", True), ("USDE", True), ("EUR", True),
    ("BTCUP", True), ("ETHDOWN", True), ("BTC3L", True), ("ETH5S", True),
    ("JUP", False), ("SYRUP", False), ("BTC", False), ("PEPE", False), ("USUAL", False), ("1000PEPE", False),
    ("PAXG", False), ("SUP", False), ("T", False), ("ETHFI", False), ("L3", False),
])
def test_exclusion_regexes(base, excluded):
    assert sm.is_excluded(base, REGEXES) is excluded


def test_rank_by_volume_excludes_and_sorts():
    perps = sm.weex_usdt_perps(weex_info())
    tickers = [{"symbol": "USDCUSDT", "quoteVolume": "9e9"}, {"symbol": "ETHUSDT", "quoteVolume": "1e9"},
               {"symbol": "BTCUSDT", "quoteVolume": "3e9"}, {"symbol": "NOPEUSDT", "quoteVolume": "1e12"},
               {"symbol": "SOLUSDT", "quoteVolume": "bad"}]
    assert sm.rank_by_volume(tickers, perps, REGEXES) == [("BTCUSDT", 3e9), ("ETHUSDT", 1e9)]


def test_select_tracked_hysteresis_48h():
    now = 1000 * HOUR
    ranked = [("AAA", 3.0), ("BBB", 2.0), ("CCC", 1.0)]
    available = {"AAA", "BBB", "CCC", "OLD", "GONE", "BTCUSDT", "VERYOLD"}
    prev = {"OLD": now - 47 * HOUR, "VERYOLD": now - 49 * HOUR, "GONE": now - HOUR, "CCC": now - 2 * HOUR}
    tracked = sm.select_tracked(ranked, prev, now, top_n=2, keep_hours=48, always=["BTCUSDT"],
                                available=available - {"GONE"})
    assert tracked["AAA"] == now and tracked["BBB"] == now and tracked["BTCUSDT"] == now
    assert tracked["OLD"] == now - 47 * HOUR          # 48 saat dolmadı: kalır
    assert tracked["CCC"] == now - 2 * HOUR           # ilk N dışında, histerezisle kalır
    assert "VERYOLD" not in tracked and "GONE" not in tracked
    order = sm.priority_order(tracked, ranked, ["BTCUSDT", "ETHUSDT"])
    assert order[:3] == ["BTCUSDT", "AAA", "BBB"]


def test_split_prefix_and_candidates():
    assert sm.split_prefix("1000PEPE") == ("PEPE", 1000.0, "1000")
    assert sm.split_prefix("1000000MOG") == ("MOG", 1e6, "1000000")
    assert sm.split_prefix("1MBABYDOGE") == ("BABYDOGE", 1e6, "1M")
    assert sm.split_prefix("1INCH") == ("1INCH", 1.0, "")
    assert sm.split_prefix("BTC") == ("BTC", 1.0, "")
    cands = sm.candidates("PEPE")
    assert cands[0] == ("PEPEUSDT", 1.0, "exact")
    assert ("1000PEPEUSDT", 1000.0, "prefix_1000") in cands
    assert ("1MPEPEUSDT", 1e6, "prefix_1M") in cands
    cands = sm.candidates("1000PEPE")
    assert ("PEPEUSDT", 0.001, "strip_1000") in cands and cands[0] == ("1000PEPEUSDT", 1.0, "exact")


def mapping(sym, base, overrides=None, weex_marks=WEEX_MARKS, bn_marks=BN_MARKS):
    ov = overrides or {}
    return sm.map_symbol(sym, base, weex_marks, bn_perps(), bn_marks, tolerance=0.015,
                         override=ov[sym] if sym in ov else ...)


def test_map_exact():
    m = mapping("BTCUSDT", "BTC")
    assert (m.binance_symbol, m.multiplier, m.method, m.note) == ("BTCUSDT", 1.0, "exact", "ok")
    assert m.price_ratio == pytest.approx(74001.1 / 74011.0, rel=1e-6)
    assert m.ft_pair == "BTC/USDT:USDT" and m.binance_onboard_ms == 1569398400000


def test_map_prefix_1000_with_multiplier():
    m = mapping("PEPEUSDT", "PEPE")
    assert (m.binance_symbol, m.multiplier, m.method) == ("1000PEPEUSDT", 1000.0, "prefix_1000")


def test_map_price_ratio_rejects_ticker_collision():
    m = mapping("COLLUSDT", "COLL")  # Binance'te aynı ad, fiyat 5 kat farklı: başka coin
    assert m.binance_symbol is None and m.method == "none" and m.note == "price_mismatch"
    assert m.price_ratio == pytest.approx(5.0)


def test_map_not_on_binance_and_no_price():
    assert mapping("WEEXONLYUSDT", "WEEXONLY").note == "not_on_binance"
    m = mapping("SOLUSDT", "SOL", bn_marks={k: v for k, v in BN_MARKS.items() if k != "SOLUSDT"})
    assert m.binance_symbol is None and m.note == "no_price"


def test_map_tolerance_edge():
    ok = mapping("SOLUSDT", "SOL", bn_marks={**BN_MARKS, "SOLUSDT": 151.93 * 1.014})
    bad = mapping("SOLUSDT", "SOL", bn_marks={**BN_MARKS, "SOLUSDT": 151.93 * 1.016})
    assert ok.binance_symbol == "SOLUSDT" and bad.binance_symbol is None


def test_map_overrides():
    m = mapping("COLLUSDT", "COLL", {"COLLUSDT": {"binance_symbol": "COLLUSDT", "multiplier": 5}})
    assert (m.binance_symbol, m.multiplier, m.method, m.note) == ("COLLUSDT", 5.0, "manual", "override")
    m = mapping("BTCUSDT", "BTC", {"BTCUSDT": None})
    assert m.binance_symbol is None and m.method == "manual"
    m = mapping("SOLUSDT", "SOL", {"SOLUSDT": {"binance_symbol": "OLDUSDT"}})  # TRADING değil
    assert m.binance_symbol is None and m.note == "override_not_trading"


def test_perps_json_format_and_atomic_write(tmp_path):
    perps = sm.weex_usdt_perps(weex_info())
    maps = sm.map_all(perps, WEEX_MARKS, bn_perps(), BN_MARKS, tolerance=0.015)
    data = sm.perps_json(maps, 1776000000000)
    assert data["generated_ms"] == 1776000000000
    assert data["pairs"]["BTC/USDT:USDT"] == {"binance_symbol": "BTCUSDT", "multiplier": 1.0, "method": "exact"}
    assert data["pairs"]["PEPE/USDT:USDT"] == {"binance_symbol": "1000PEPEUSDT", "multiplier": 1000.0,
                                               "method": "prefix_1000"}
    assert "WEEXONLY/USDT:USDT" not in data["pairs"] and "COLL/USDT:USDT" not in data["pairs"]
    path = tmp_path / "data" / "binance_perps.json"
    path.parent.mkdir()
    path.write_text("eski", encoding="utf-8")
    sm.write_json_atomic(path, data)
    assert json.loads(path.read_text(encoding="utf-8")) == data
    assert [p.name for p in path.parent.iterdir()] == ["binance_perps.json"]  # geçici dosya kalmadı


def test_atomic_write_failure_keeps_old_file(tmp_path, monkeypatch):
    path = tmp_path / "binance_perps.json"
    path.write_text('{"generated_ms": 1, "pairs": {}}', encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk dolu")

    monkeypatch.setattr(sm.json, "dump", boom)
    with pytest.raises(OSError):
        sm.write_json_atomic(path, {"generated_ms": 2, "pairs": {}})
    assert json.loads(path.read_text(encoding="utf-8"))["generated_ms"] == 1
    assert [p.name for p in tmp_path.iterdir()] == ["binance_perps.json"]
