"""user_data/config.json ve config.backtest.json: Freqtrade'in kendi şema/doğrulaması (internetsiz)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cyberbot import settings
from cyberbot.strategy import defaults
from freqtrade.configuration import Configuration
from freqtrade.enums import RunMode
from freqtrade.plugins.pairlist.pairlist_helpers import expand_pairlist
from freqtrade.resolvers import StrategyResolver

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "user_data" / "config.json"
BACKTEST = ROOT / "user_data" / "config.backtest.json"


def ft_config(tmp_path, runmode, *files):
    args = {"config": [str(f) for f in files], "user_data_dir": str(tmp_path), "datadir": str(tmp_path / "data"),
            "strategy": "CyberScalp", "strategy_path": str(ROOT / "user_data" / "strategies")}
    return Configuration(args, runmode).get_config()


def same_keys(a: dict, b: dict, prefix=""):
    assert set(a) == set(b), f"{prefix}: {sorted(set(a) ^ set(b))}"
    for key, value in a.items():
        if isinstance(value, dict):
            same_keys(value, b[key], f"{prefix}.{key}")


def test_config_is_strict_json_and_loads_with_settings():
    raw = CONFIG.read_text(encoding="utf-8")
    json.loads(raw)  # yorum yok, katı JSON
    cfg = settings.load_config(CONFIG)
    strat = cfg["cyberbot"]["strategy"]
    same_keys(defaults.STRATEGY_DEFAULTS, strat, "cyberbot.strategy")  # yazım hatası yok, tüm ayarlar görünür
    assert defaults.load(cfg) == defaults.STRATEGY_DEFAULTS
    assert defaults.validate(defaults.load(cfg)) == []
    assert cfg["cyberbot"]["recorder"] == {} and cfg["cyberbot"]["monitor"] == {}


def test_dry_run_config_passes_freqtrade_validation(tmp_path):
    c = ft_config(tmp_path, RunMode.DRY_RUN, CONFIG)
    assert c["dry_run"] is True and c["dry_run_wallet"] == 1000
    assert (c["trading_mode"], c["margin_mode"]) == ("futures", "isolated")
    assert c["stake_currency"] == "USDT" and c["stake_amount"] == "unlimited" and c["max_open_trades"] == 3
    assert c["tradable_balance_ratio"] == 0.99 and c["liquidation_buffer"] == 0.05
    for side in ("entry_pricing", "exit_pricing"):
        assert c[side]["price_side"] == "other" and c[side]["use_order_book"] and c[side]["order_book_top"] == 1
    ot = c["order_types"]
    assert {ot[k] for k in ("entry", "exit", "stoploss", "emergency_exit")} == {"market"}
    assert ot["stoploss_on_exchange"] is False
    assert c["order_time_in_force"] == {"entry": "GTC", "exit": "GTC"}
    assert c["internals"]["process_throttle_secs"] == 5 and c["internals"]["heartbeat_interval"] == 60
    assert c["dataformat_ohlcv"] == "feather"
    ex = c["exchange"]
    assert ex["name"] == "weex" and ex["weex_maintenance_margin_rate"] == 0.01
    assert ex["pair_whitelist"] == []
    methods = [p["method"] for p in c["pairlists"]]
    assert methods == ["VolumePairList", "AgeFilter", "SpreadFilter", "PriceFilter"]
    vol = c["pairlists"][0]
    assert vol["number_assets"] == 40 and vol["sort_key"] == "quoteVolume" and vol["refresh_period"] == 3600
    assert vol["min_value"] >= 1_000_000


def test_no_secrets_and_telegram_api_off_in_repo_config():
    cfg = settings.load_config(CONFIG)
    assert cfg["exchange"]["key"] == cfg["exchange"]["secret"] == cfg["exchange"]["password"] == ""
    tg = cfg["telegram"]
    assert tg["enabled"] is False and tg["token"] == "" and tg["chat_id"] == ""  # cyberbot.launch .env'den açar
    assert cfg["api_server"]["enabled"] is False


def test_backtest_overlay_passes_validation_and_uses_static_pairs(tmp_path):
    c = ft_config(tmp_path, RunMode.BACKTEST, CONFIG, BACKTEST)
    assert c["pairlists"] == [{"method": "StaticPairList"}]
    wl = c["exchange"]["pair_whitelist"]
    assert len(wl) == 20 and all(p.endswith("/USDT:USDT") for p in wl) and "BTC/USDT:USDT" in wl
    assert c["fee"] == 0.0008
    assert c["exchange"]["pair_blacklist"] == settings.load_config(CONFIG)["exchange"]["pair_blacklist"]


def test_strategy_loads_with_expected_settings(tmp_path):
    strat = StrategyResolver.load_strategy(ft_config(tmp_path, RunMode.BACKTEST, CONFIG, BACKTEST))
    assert type(strat).__name__ == "CyberScalp" and strat.INTERFACE_VERSION == 3
    assert strat.timeframe == "5m" and strat.can_short and strat.startup_candle_count == 400
    assert strat.minimal_roi == {0: 100} and strat.stoploss == -0.30
    assert strat.use_custom_stoploss and strat.use_exit_signal and strat.process_only_new_candles


LEGIT = ["BTC", "ETH", "JUP", "SYRUP", "SUSHI", "USUAL", "1INCH", "API3", "C98", "L3", "1000PEPE", "1000SATS",
         "ENA", "DUSK", "ORDI", "PEOPLE", "SUPER", "UNI", "AI16Z", "GMT", "ZK", "EIGEN", "S", "BEL", "OP", "ARB",
         "TRUMP"]
BLOCKED = ["USDC", "FDUSD", "TUSD", "DAI", "USDE", "PYUSD", "USD1", "EUR", "BTCBULL", "ETHBEAR", "BTC3L", "ETH3S",
           "SOL5L", "usdc"]


@pytest.mark.parametrize("bases,blocked", [(LEGIT, False), (BLOCKED, True)])
def test_blacklist_regexes_use_fullmatch_and_spare_legit_pairs(bases, blocked):
    patterns = settings.load_config(CONFIG)["exchange"]["pair_blacklist"]
    pairs = [f"{b}/USDT:USDT" for b in bases]
    matched = set(expand_pairlist(patterns, pairs))
    assert matched == (set(pairs) if blocked else set()), matched ^ (set(pairs) if blocked else set())
