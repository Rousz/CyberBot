"""Offline WEEX for Freqtrade tests.

Routes ccxt.weex implicit API calls (`request`) to synthetic data, so the real
ccxt parsing code and the real Freqtrade Exchange code run without any network.
Every ccxt `fetch` (the HTTP layer) raises, so nothing can leak to the internet.

Usage:
    with offline_weex() as router:
        ex = make_exchange(tmp_path)
        ...
        assert router.calls_to("capi/v3/market/historyKlines")
"""

from __future__ import annotations

import contextlib
import importlib
import json
import time
from pathlib import Path
from unittest.mock import patch

import ccxt
import ccxt.async_support as ccxt_async

import freqtrade.exchange as ft_exchange
from freqtrade.enums import RunMode
from freqtrade_ext.weex import Weex

FIXTURES = Path(__file__).parent / "fixtures"
HOUR_MS = 3_600_000
FUNDING_STEP_MS = 8 * HOUR_MS
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": HOUR_MS,
         "4h": 4 * HOUR_MS, "12h": 12 * HOUR_MS, "1d": 24 * HOUR_MS, "1w": 7 * 24 * HOUR_MS}

RAW_SPOT = [
    {"symbol": "ETHUSDT", "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "USDT",
     "tickSize": "0.01", "stepSize": "0.00001", "minTradeAmount": "0.0001",
     "takerFeeRate": "0.001", "makerFeeRate": "0.001", "enableTrade": True},
]


def register_weex() -> None:
    """ExchangeResolver resolves getattr(freqtrade.exchange, "weex".title())."""
    ft_exchange.Weex = Weex


def raw_contracts() -> list[dict]:
    return json.loads((FIXTURES / "weex" / "exchangeInfo.json").read_text(encoding="utf-8"))["symbols"]


def _price_at(t_ms: int, base: float) -> float:
    # deterministic, gently oscillating synthetic price
    step = t_ms // 300_000
    return base * (1 + 0.01 * ((step % 200) - 100) / 100)


class WeexRouter:
    def __init__(self, history_days: float = 3650, now_ms: int | None = None):
        self.history_days = history_days
        self.fixed_now_ms = now_ms
        self.calls: list[tuple[str, str, dict]] = []
        self.fail_paths: dict[str, Exception] = {}  # path -> exception to raise

    # -- helpers ------------------------------------------------------------
    def now_ms(self) -> int:
        return self.fixed_now_ms or int(time.time() * 1000)

    def calls_to(self, path: str) -> list[dict]:
        return [params for _, p, params in self.calls if p == path]

    def _klines(self, symbol: str, tf: str, open_times: list[int]) -> list[list]:
        base = 74000.0 if symbol.startswith("BTC") else 2000.0
        rows = []
        for t in open_times:
            o = _price_at(t, base)
            c = _price_at(t + TF_MS[tf], base)
            rows.append([t, f"{o:.2f}", f"{max(o, c) * 1.001:.2f}", f"{min(o, c) * 0.999:.2f}",
                         f"{c:.2f}", "10", t + TF_MS[tf] - 1, "1000", 5, "5", "500"])
        return rows

    # -- router -------------------------------------------------------------
    def route(self, api, path, params):
        params = dict(params or {})
        self.calls.append((api, path, params))
        if path in self.fail_paths:
            raise self.fail_paths[path]
        now = self.now_ms()
        if path == "api/v3/coins":
            return []
        if path == "api/v3/exchangeInfo":
            return {"symbols": RAW_SPOT}
        if path == "capi/v3/market/exchangeInfo":
            return {"symbols": raw_contracts()}
        if path in ("capi/v3/market/time", "api/v3/time"):
            return {"serverTime": now}
        if path in ("capi/v3/market/klines", "capi/v3/market/markPriceKlines",
                    "capi/v3/market/indexPriceKlines"):
            tf_ms = TF_MS[params["interval"]]
            current_open = now // tf_ms * tf_ms
            n = min(int(params.get("limit", 100)), 1000)
            # like WEEX: newest n candles incl. the forming one; startTime/endTime ignored
            times = list(range(current_open - (n - 1) * tf_ms, current_open + 1, tf_ms))
            return self._klines(params["symbol"], params["interval"], times)
        if path == "capi/v3/market/historyKlines":
            tf_ms = TF_MS[params["interval"]]
            oldest = now - int(self.history_days * 24 * HOUR_MS)
            start = max((int(params["startTime"]) + tf_ms - 1) // tf_ms * tf_ms, oldest // tf_ms * tf_ms)
            end = min(int(params["endTime"]), now // tf_ms * tf_ms)
            times = list(range(start, end + 1, tf_ms))[:100]
            return self._klines(params["symbol"], params["interval"], times)
        if path == "capi/v3/market/fundingRate":
            start = int(params.get("startTime", now - 7 * 24 * HOUR_MS))
            start = (start + FUNDING_STEP_MS - 1) // FUNDING_STEP_MS * FUNDING_STEP_MS
            end = int(params.get("endTime", now))
            rows = [{"symbol": params["symbol"], "fundingRate": "0.0001", "fundingTime": str(t),
                     "markPrice": "100"} for t in range(start, min(end, now) + 1, FUNDING_STEP_MS)]
            return rows[: int(params.get("limit", 100))]
        if path == "capi/v3/market/depth":
            depth = json.loads((FIXTURES / "weex" / "depth.json").read_text(encoding="utf-8"))
            if params.get("symbol") != "BTCUSDT":
                depth = {"asks": [["2000.2", "50"], ["2001", "80"]], "bids": [["2000.0", "50"], ["1999", "80"]],
                         "lastUpdateId": 1}
            return depth
        if path == "capi/v3/market/ticker/24hr":
            rows = json.loads((FIXTURES / "weex" / "ticker_24hr.json").read_text(encoding="utf-8"))
            for row in rows:
                row["closeTime"] = now
            return rows
        if path == "capi/v3/market/ticker/bookTicker":
            return [
                {"symbol": "BTCUSDT", "bidPrice": "74010.5", "bidQty": "0.8", "askPrice": "74010.6",
                 "askQty": "1.2", "time": now},
                {"symbol": "ETHUSDT", "bidPrice": "2081.79", "bidQty": "5", "askPrice": "2081.81",
                 "askQty": "5", "time": now},
                {"symbol": "SOLUSDT", "bidPrice": "151.91", "bidQty": "50", "askPrice": "151.93",
                 "askQty": "50", "time": now},
            ]
        if path == "capi/v3/market/premiumIndex":
            return json.loads((FIXTURES / "weex" / "premiumIndex.json").read_text(encoding="utf-8"))
        raise AssertionError(f"WeexRouter: unrouted {api} {path} {params}")


@contextlib.contextmanager
def offline_weex(router: WeexRouter | None = None):
    """Patch ccxt.weex (sync + async/pro) request routing and forbid real HTTP."""
    router = router or WeexRouter()
    register_weex()
    sync_base = importlib.import_module("ccxt.base.exchange")
    async_base = importlib.import_module("ccxt.async_support.base.exchange")

    def no_net(*args, **kwargs):
        raise RuntimeError(f"Testlerde ağ erişimi yasak (ccxt fetch): {args[1:3]}")

    async def no_net_async(*args, **kwargs):
        raise RuntimeError(f"Testlerde ağ erişimi yasak (ccxt fetch): {args[1:3]}")

    def sync_request(self, path, api="public", method="GET", params={}, headers=None, body=None, config={}):
        return router.route(api, path, params)

    async def async_request(self, path, api="public", method="GET", params={}, headers=None, body=None,
                            config={}):
        return router.route(api, path, params)

    with patch.object(sync_base.Exchange, "fetch", no_net), \
            patch.object(async_base.Exchange, "fetch", no_net_async), \
            patch.object(ccxt.weex, "request", sync_request), \
            patch.object(ccxt_async.weex, "request", async_request):
        yield router


def base_config(tmp_path: Path, **overrides) -> dict:
    conf = {
        "runmode": RunMode.DRY_RUN,
        "dry_run": True,
        "dry_run_wallet": 1000,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "stake_currency": "USDT",
        "stake_amount": "unlimited",
        "timeframe": "5m",
        "startup_candle_count": 400,
        "datadir": tmp_path,
        "user_data_dir": tmp_path,
        "exchange": {"name": "weex", "key": "", "secret": "", "password": "", "pair_whitelist": [],
                     "pair_blacklist": [], "weex_maintenance_margin_rate": 0.01},
        "entry_pricing": {"price_side": "other", "use_order_book": True, "order_book_top": 1},
        "exit_pricing": {"price_side": "other", "use_order_book": True, "order_book_top": 1},
        "order_types": {"entry": "market", "exit": "market", "stoploss": "market",
                        "stoploss_on_exchange": False},
    }
    conf.update(overrides)
    return conf


def make_exchange(tmp_path: Path, **overrides):
    from freqtrade.resolvers import ExchangeResolver

    return ExchangeResolver.load_exchange(base_config(tmp_path, **overrides), load_leverage_tiers=True)
