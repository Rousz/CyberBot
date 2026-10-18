"""Borsa sağlık durum makinesi + stratejideki bağlantısı (kilit, tek Telegram uyarısı, uptime)."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from cyberbot import settings, uptime
from cyberbot.strategy.health import ExchangeHealth
from freqtrade.enums import CandleType, RunMode
from freqtrade.persistence import PairLocks

ROOT = Path(__file__).resolve().parent.parent
TF = 300_000
T0 = 1_768_003_200_000  # 2026-01-10 00:00 UTC (5m sınırı)


def fresh_open(now_ms: int) -> int:
    return (now_ms - 45_000) // TF * TF - TF


# --------------------------------------------------------------------------- saf durum makinesi


def test_fresh_threshold_matches_grace_and_delay():
    h = ExchangeHealth()
    now = T0 + 5 * 60_000 + 3_000  # 00:05:03 -> 23:55 mumu yeterli (00:00 mumu daha bekletiliyor olabilir)
    assert h.expected_open_ms(now) == T0 - TF
    assert h.is_fresh(T0 - TF, now)
    later = T0 + 5 * 60_000 + 46_000  # 00:05:46 -> 00:00 mumu gelmiş olmalı
    assert not h.is_fresh(T0 - TF, later) and h.is_fresh(T0, later)
    assert not h.is_fresh(None, now)


def test_single_alert_lock_renewal_and_recovery_after_n_loops():
    h = ExchangeHealth(lock_minutes=10, recovery_loops=3)
    now = T0 + 3_600_000
    assert h.update(fresh_open(now), now).transition is None
    stale = fresh_open(now)  # veri bu mumda donuyor
    transitions, locks = [], []
    for i in range(1, 400):  # ~33 dk, 5 sn'de bir döngü
        t = now + 60_000 + i * 5_000
        d = h.update(stale, t)
        transitions.append(d.transition)
        if d.lock_until_ms:
            locks.append((t, d.lock_until_ms))
        assert not d.healthy
    assert transitions.count("down") == 1 and "recovered" not in transitions
    # kilit hep ileride; yarısı dolunca yenilenir (her döngüde değil)
    assert 3 <= len(locks) <= 8
    assert all(until - t == 600_000 for t, until in locks)
    # kurtarma: 3 ardışık taze döngü
    t = now + 60_000 + 400 * 5_000
    results = [h.update(fresh_open(t + k * 5_000), t + k * 5_000) for k in range(3)]
    assert [r.transition for r in results] == [None, None, "recovered"]
    assert results[-1].healthy and h.healthy


def test_no_flapping_one_stale_loop_resets_recovery_counter():
    h = ExchangeHealth(recovery_loops=3)
    t = T0 + 3_600_000
    assert h.update(None, t).transition == "down"
    seq = [True, True, False, True, True, True]
    out = []
    for k, ok in enumerate(seq, start=1):
        now = t + k * 5_000
        out.append(h.update(fresh_open(now) if ok else None, now).transition)
    assert out == [None, None, None, None, None, "recovered"]
    # düzeldikten sonra yeni kesinti -> yeni (tek) uyarı
    now = t + 100_000
    assert h.update(None, now).transition == "down"
    assert h.update(None, now + 5_000).transition is None


# --------------------------------------------------------------------------- strateji bağlantısı


def load_strategy_class():
    path = ROOT / "user_data" / "strategies" / "CyberScalp.py"
    spec = importlib.util.spec_from_file_location("CyberScalp_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CyberScalp


class FakeDP:
    def __init__(self, runmode=RunMode.DRY_RUN):
        self.runmode = runmode
        self.messages: list[str] = []
        self.candles = pd.DataFrame({"date": pd.to_datetime([], utc=True)})
        self.whitelist: list[str] = []
        self.book = {"bids": [[100.0, 10_000]], "asks": [[100.1, 10_000]]}

    def ohlcv(self, pair, timeframe=None, copy=True, candle_type=""):
        return self.candles

    def send_msg(self, message, *, always_send=False):
        assert always_send
        self.messages.append(message)

    def current_whitelist(self):
        return list(self.whitelist)

    def orderbook(self, pair, maximum):
        return self.book


@pytest.fixture
def strategy(tmp_path, monkeypatch):
    monkeypatch.setenv("CYBERBOT_DATA_DIR", str(tmp_path / "data"))
    PairLocks.use_db = False
    PairLocks.timeframe = "5m"
    PairLocks.reset_locks()
    config = settings.load_config(ROOT / "user_data" / "config.json")
    config["runmode"] = RunMode.DRY_RUN
    config["candle_type_def"] = CandleType.FUTURES
    strat = load_strategy_class()(config)
    strat.dp = FakeDP()
    yield strat
    strat.ft_bot_cleanup()
    PairLocks.reset_locks()


def set_last_candle(strat, open_ms: int):
    strat.dp.candles = pd.DataFrame({"date": [pd.Timestamp(open_ms, unit="ms", tz="UTC")]})


def dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def test_bot_start_records_uptime_and_cleanup_closes_it(strategy, tmp_path):
    strategy.bot_start()
    store = uptime.UptimeStore(tmp_path / "data" / "uptime.sqlite", "freqtrade")
    (s,) = store.sessions()
    assert s.stopped_ms is None and "freqtrade" in s.version
    strategy.bot_start()  # reload_config: önceki oturum kapanır, yenisi açılır
    first, second = store.sessions()
    assert first.stop_kind == "reload" and second.stopped_ms is None
    strategy.ft_bot_cleanup()
    assert store.sessions()[-1].stop_kind == "clean"
    strategy.ft_bot_cleanup()  # ikinci çağrı bozmaz


def test_bot_start_rejects_target_rr_below_min_rr(strategy):
    strategy.config.setdefault("cyberbot", {}).setdefault("strategy", {})["target_rr"] = 1.2
    with pytest.raises(ValueError, match="target_rr"):
        strategy.bot_start()


def test_bot_loop_locks_alerts_once_and_recovers(strategy, tmp_path):
    strategy.bot_start()
    # gerçek saat civarı: Freqtrade'in unlock_reason'ı datetime.now ile çalışır
    now = int(datetime.now(timezone.utc).timestamp() * 1000) // TF * TF - 600_000
    set_last_candle(strategy, fresh_open(now))
    strategy.bot_loop_start(dt(now))
    assert not PairLocks.is_global_lock() and strategy.dp.messages == []
    # veri donar
    for k in range(1, 30):
        strategy.bot_loop_start(dt(now + 60_000 + k * 5_000))
    assert PairLocks.is_global_lock(dt(now + 60_000 + 30 * 5_000))
    assert len(strategy.dp.messages) == 1 and "WEEX" in strategy.dp.messages[0]
    assert "BTC/USDT:USDT" in strategy.dp.messages[0]
    assert not strategy.confirm_trade_entry("ETH/USDT:USDT", "market", 1, 100, "GTC", dt(now), None, "long")
    # düzelir
    t = now + 60_000 + 40 * 5_000
    for k in range(3):
        set_last_candle(strategy, fresh_open(t + k * 5_000))
        strategy.bot_loop_start(dt(t + k * 5_000))
    assert not PairLocks.is_global_lock(dt(t + 20_000))
    assert len(strategy.dp.messages) == 2 and "düzeldi" in strategy.dp.messages[1]
    kinds = [e.kind for e in uptime.UptimeStore(tmp_path / "data" / "uptime.sqlite", "freqtrade").events()]
    assert kinds == ["exchange_down", "exchange_recovered"]


def test_no_side_effects_outside_dry_run(strategy, tmp_path):
    strategy.dp.runmode = RunMode.BACKTEST
    strategy.bot_start()
    strategy.bot_loop_start(dt(T0 + 3_600_000))  # boş veri -> canlıda bayat sayılırdı
    assert strategy.dp.messages == [] and not PairLocks.is_global_lock()
    assert not (tmp_path / "data" / "uptime.sqlite").exists()
    strategy.dp.runmode = RunMode.UTIL_NO_EXCHANGE  # lookahead/recursive analizi
    strategy.bot_start()
    strategy.bot_loop_start(dt(T0 + 3_600_000))
    assert strategy.dp.messages == [] and not (tmp_path / "data" / "uptime.sqlite").exists()


def test_messages_escape_markdown(strategy):
    strategy.btc_pair = "BTC_X/USDT:USDT"  # alt çizgi kaçışlanmalı
    strategy.bot_start()
    strategy.bot_loop_start(dt(T0 + 3_600_000))
    assert "BTC\\_X/USDT:USDT" in strategy.dp.messages[0]


def test_leverage_is_capped_by_exchange_max(strategy):
    strategy.bot_start()
    assert strategy.leverage("ETH/USDT:USDT", dt(T0), 100, 1, 400, None, "long") == 3.0
    assert strategy.leverage("ETH/USDT:USDT", dt(T0), 100, 1, 2, None, "long") == 2.0
