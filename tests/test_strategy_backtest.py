"""CyberScalp: Freqtrade Backtesting + LookaheadAnalysis + RecursiveAnalysis (internetsiz).

Sentetik futures verisi (BTC, ETH, SOL; 5m + 1h + 1h mark + 1h funding_rate) ve
tests/weex_router.offline_weex ile gerçek Freqtrade + gerçek WEEX sınıfı çalışır.
Config: repo'daki user_data/config.json + config.backtest.json (+ test için küçük whitelist).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from freqtrade.configuration import Configuration
from freqtrade.enums import RunMode
from freqtrade.optimize.analysis.lookahead import LookaheadAnalysis
from freqtrade.optimize.analysis.lookahead_helpers import LookaheadAnalysisSubFunctions
from freqtrade.optimize.analysis.recursive import RecursiveAnalysis
from freqtrade.optimize.analysis.recursive_helpers import RecursiveAnalysisSubFunctions
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.persistence import LocalTrade
from freqtrade.persistence.custom_data import CustomDataWrapper
from freqtrade.util import get_progress_tracker
from tests import strategy_data as sd
from tests.weex_router import offline_weex

ROOT = Path(__file__).resolve().parent.parent
PAIRS = ["ETH/USDT:USDT", "SOL/USDT:USDT", "BTC/USDT:USDT"]
TIMERANGE = "20260111-20260203"
EXPECTED_EXITS = {"take_profit", "time_stop", "stop_loss", "trailing_stop_loss", "fill_beyond_stop", "force_exit"}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    base = tmp_path_factory.mktemp("bt")
    ud = base / "user_data"
    datadir = ud / "data" / "weex"
    sd.write_futures_data(datadir, {
        "BTC/USDT:USDT": sd.trend_series(seed=51, base=74000.0),
        "ETH/USDT:USDT": sd.trend_series(seed=1, base=2000.0),
        "SOL/USDT:USDT": sd.trend_series(seed=2, base=150.0),
    })
    overlay = base / "config.test.json"
    overlay.write_text(json.dumps({"exchange": {"pair_whitelist": PAIRS}}), encoding="utf-8")
    return {"base": base, "ud": ud, "datadir": datadir, "overlay": overlay}


@pytest.fixture(autouse=True)
def isolated_paths(env, monkeypatch):
    monkeypatch.setenv("CYBERBOT_DATA_DIR", str(env["base"] / "cyberbot_data"))


def load_config(env, runmode: RunMode, **extra) -> dict:
    args = {
        "config": [str(ROOT / "user_data" / "config.json"), str(ROOT / "user_data" / "config.backtest.json"),
                   str(env["overlay"])],
        "user_data_dir": str(env["ud"]),
        "datadir": str(env["datadir"]),
        "strategy": "CyberScalp",
        "strategy_path": str(ROOT / "user_data" / "strategies"),
        "timerange": TIMERANGE,
        "export": "none",
        **extra,
    }
    return Configuration(args, runmode).get_config()


@pytest.fixture(scope="module")
def backtest(env):
    with offline_weex():
        mp = pytest.MonkeyPatch()
        mp.setenv("CYBERBOT_DATA_DIR", str(env["base"] / "cyberbot_data"))
        try:
            bt = Backtesting(load_config(env, RunMode.BACKTEST))
            bt.start()
            trades = list({t.id: t for t in [*LocalTrade.bt_trades, *LocalTrade.bt_trades_open]}.values())
            custom = {}
            for item in CustomDataWrapper.custom_data:
                custom.setdefault(item.ft_trade_id, {})[item.cd_key] = item.value
            yield bt.results["strategy"]["CyberScalp"], trades, custom
        finally:
            mp.undo()


def test_backtest_trades_with_leverage_and_expected_exits(backtest):
    result, trades, _ = backtest
    assert result["total_trades"] >= 10
    assert {t["leverage"] for t in result["trades"]} == {3.0}
    assert {t["exit_reason"] for t in result["trades"]} <= EXPECTED_EXITS
    assert {t["is_short"] for t in result["trades"]} == {False, True}  # long ve short ikisi de
    assert len(trades) == result["total_trades"]


def test_backtest_every_trade_planned_rr_at_least_min_rr(backtest):
    _, trades, custom = backtest
    assert trades
    for trade in trades:
        data = custom[trade.id]
        risk = abs(trade.open_rate - data["sl"])
        reward = abs(data["tp"] - trade.open_rate)
        assert risk > 0
        assert reward / risk >= 1.5 - 1e-9
        assert data["plan_source"] == "signal"
        # stop doğru tarafta
        assert (data["sl"] > trade.open_rate) if trade.is_short else (data["sl"] < trade.open_rate)
        assert data["score"] >= 70


def test_backtest_respects_max_open_trades(backtest):
    result, trades, _ = backtest
    events = [(t.open_date_utc, 1) for t in trades] + [(t.close_date_utc, -1) for t in trades if t.close_date_utc]
    events.sort(key=lambda e: (e[0], e[1]))  # aynı anda kapanış önce
    open_now = peak = 0
    for _, delta in events:
        open_now += delta
        peak = max(peak, open_now)
    assert peak <= 3


def test_lookahead_analysis_finds_no_bias(env):
    with offline_weex():
        cfg = load_config(env, RunMode.UTIL_EXCHANGE, minimum_trade_amount=5, targeted_trade_amount=10)
        cfg["pairs"] = ["ETH/USDT:USDT", "SOL/USDT:USDT"]
        cfg = LookaheadAnalysisSubFunctions.calculate_config_overrides(cfg)
        inst = LookaheadAnalysis(cfg, {"name": "CyberScalp"})
        inst.start(get_progress_tracker())
    a = inst.current_analysis
    assert a.total_signals >= 5
    assert not inst.failed_bias_check
    assert not a.has_bias, (a.false_entry_signals, a.false_exit_signals, a.false_indicators)


def test_recursive_analysis_small_deviation_at_configured_startup(env):
    with offline_weex():
        cfg = load_config(env, RunMode.UTIL_EXCHANGE, startup_candle=[400])
        cfg["pairs"] = ["ETH/USDT:USDT"]
        cfg = RecursiveAnalysisSubFunctions.calculate_config_overrides(cfg)
        inst = RecursiveAnalysis(cfg, {"name": "CyberScalp"})
        inst.start(get_progress_tracker())
    deviations = {k: v[400] for k, v in inst.dict_recursive.items() if 400 in v}
    numeric = {k: v for k, v in deviations.items() if v == v}  # NaN = sayısal olmayan sütun
    assert len(numeric) == len(deviations), deviations  # metin sütunları (regime) değişmemeli
    # EMA200 (özellikle 1h) 400 mumda tam yakınsamaz: aşırı trendli sentetik veride ~%0.5.
    # Canlıda 1h için 1000 mum gelir (fark ~%0.03). Diğer tüm göstergeler pratikte aynı.
    slow = {k: v for k, v in numeric.items() if k.endswith(("ema_slow", "ema_slow_1h"))}
    rest = {k: v for k, v in numeric.items() if k not in slow}
    assert all(abs(v) < 0.01 for v in slow.values()), slow
    assert all(abs(v) < 1e-4 for v in rest.values()), rest
