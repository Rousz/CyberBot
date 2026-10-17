"""WEEX USDT-M perpetual futures for Freqtrade 2026.9 (CyberBot).

This file is copied into the Docker image as freqtrade/exchange/weex.py and
registered as freqtrade.exchange.Weex (ExchangeResolver uses "weex".title()).
It only imports freqtrade and ccxt, never the cyberbot package.

Verified against freqtrade 2026.9 and ccxt 4.5.88 source (see PROGRESS.md):
- WEEX quantities are base-asset units; ccxt sets contractSize=contractVal (a lot step),
  so get_contract_size() must return 1.0 or orders would be scaled by 1/contractVal.
- No leverage tiers: get_max_leverage() would return 1.0 and every trade would be 1x.
- capi/v3/market/klines ignores `since` and returns the newest <=1000 candles;
  older windows need historyKlines (max 100 per request, startTime/endTime).
- ticker/24hr has no bid/ask: merge ticker/bookTicker so SpreadFilter works.
- fetchL2OrderBook is declared False by ccxt but its base implementation wraps
  fetch_order_book (capi/v3/market/depth); order-book pricing needs it.

Live trading is intentionally blocked (RunMode.LIVE) until the live-only items in
PROGRESS.md (isolated leverage param, order status mapping, algo stoploss orders,
funding history pagination) are implemented and verified on the PC.
"""

import logging
from copy import deepcopy

import ccxt

from freqtrade.enums import CandleType, MarginMode, PriceType, RunMode, TradingMode
from freqtrade.exceptions import DDosProtection, OperationalException, TemporaryError
from freqtrade.exchange.common import retrier_async
from freqtrade.exchange.exchange import Exchange
from freqtrade.exchange.exchange_types import FtHas, OHLCVResponse, Tickers
from freqtrade.exchange.exchange_utils import date_minus_candles
from freqtrade.exchange.exchange_utils_timeframe import timeframe_to_msecs
from freqtrade.misc import deep_merge_dicts
from freqtrade.util import dt_from_ts, dt_ts


logger = logging.getLogger(__name__)

WEEX_RECENT_LIMIT = 1000  # capi/v3/market/klines | markPriceKlines | indexPriceKlines
WEEX_HISTORY_LIMIT = 100  # capi/v3/market/historyKlines
WEEX_RECENT_SAFETY = 5  # candles of margin before switching to historyKlines
DEFAULT_MAINTENANCE_MARGIN_RATE = 0.01  # assumption; WEEX exposes no MMR publicly


class Weex(Exchange):
    _ft_has: FtHas = {
        "ohlcv_candle_limit": WEEX_RECENT_LIMIT,
        "ohlcv_has_history": True,
        "order_time_in_force": ["GTC", "IOC", "FOK"],
        "stoploss_on_exchange": False,
        "exchange_has_overrides": {"fetchL2OrderBook": True},
        "l2_limit_range": [15, 200],
        "l2_limit_range_required": True,
        "trades_has_history": False,
        "ws_enabled": False,
    }
    _ft_has_futures: FtHas = {
        "funding_fee_candle_limit": 1000,
        "mark_ohlcv_price": "mark",
        "mark_ohlcv_timeframe": "1h",
        "funding_fee_timeframe": "1h",
        "uses_leverage_tiers": False,
        "stoploss_blocks_assets": False,
        "stop_price_param": "stopLossPrice",
        "stop_price_prop": "stopLossPrice",
        "stop_price_type_field": "stopLossPriceType",
        "stop_price_type_value_mapping": {PriceType.LAST: "last", PriceType.MARK: "mark"},
    }
    _supported_trading_mode_margin_pairs = [
        (TradingMode.SPOT, MarginMode.NONE),
        (TradingMode.FUTURES, MarginMode.ISOLATED),
    ]

    def __init__(self, config, *, exchange_config=None, validate=True, load_leverage_tiers=False):
        # Checked before any network call. OperationalException (not AttributeError, which
        # ExchangeResolver would swallow) stops the bot with a clear message.
        if config.get("runmode") == RunMode.LIVE:
            self._exchange_ws = None  # Exchange.__del__ -> close() reads these
            self._ws_async = None
            raise OperationalException(
                "CyberBot: WEEX canlı işlem henüz doğrulanmadı ve kapalı. Sadece dry-run kullanılabilir."
            )
        self._weex_last_tickers: Tickers = {}
        self._weex_last_bidsasks: Tickers = {}
        self.weex_last_ok_ms: int | None = None  # last successful public market-data call
        super().__init__(
            config,
            exchange_config=exchange_config,
            validate=validate,
            load_leverage_tiers=load_leverage_tiers,
        )

    # ---------------------------------------------------------------- markets

    @property
    def timeframes(self) -> list[str]:
        # ccxt keys contract intervals as options.timeframes.contract (no 2h/6h/8h/1M);
        # Freqtrade's base property would look for "swap" and fall back to the generic list.
        if self.trading_mode == TradingMode.FUTURES:
            tfs = self._api.options.get("timeframes", {}).get("contract")
            if tfs:
                return list(tfs.keys())
        return super().timeframes

    def get_contract_size(self, pair: str) -> float | None:
        # WEEX quantity/size/qty and volumes are base-asset units; contractVal is a lot step.
        if self.trading_mode == TradingMode.FUTURES:
            return 1.0 if self.markets.get(pair) else None
        return 1

    # ---------------------------------------------------------------- ohlcv

    def _weex_needs_history(self, timeframe: str, since_ms: int | None) -> bool:
        if since_ms is None:
            return False
        oldest_recent = dt_ts(date_minus_candles(timeframe, WEEX_RECENT_LIMIT - WEEX_RECENT_SAFETY))
        return since_ms < oldest_recent

    # ohlcv_candle_limit is deliberately NOT since-dependent: Freqtrade sees 1000-candle
    # windows (startup validation, pagination stride); windows older than the recent
    # endpoint can serve are filled here with sequential 100-candle historyKlines calls.
    # Not decorated with @retrier_async: super() and _weex_history_chunk already retry.
    async def _async_get_candle_history(
        self,
        pair: str,
        timeframe: str,
        candle_type: CandleType,
        since_ms: int | None = None,
    ) -> OHLCVResponse:
        if candle_type in (
            CandleType.SPOT,
            CandleType.FUTURES,
            CandleType.MARK,
            CandleType.INDEX,
        ) and self._weex_needs_history(timeframe, since_ms):
            tf_ms = timeframe_to_msecs(timeframe)
            window_end = min(since_ms + WEEX_RECENT_LIMIT * tf_ms, dt_ts())
            rows: dict[int, list] = {}
            start = since_ms
            while start < window_end:
                for row in await self._weex_history_chunk(pair, timeframe, candle_type, start):
                    rows[row[0]] = row
                start += WEEX_HISTORY_LIMIT * tf_ms
            data = [rows[k] for k in sorted(rows)]
            self._weex_mark_ok()
            return pair, timeframe, candle_type, data, self._drop_incomplete_candle(candle_type)
        result = await super()._async_get_candle_history(pair, timeframe, candle_type, since_ms)
        self._weex_mark_ok()
        return result

    @retrier_async
    async def _weex_history_chunk(
        self, pair: str, timeframe: str, candle_type: CandleType, start_ms: int
    ) -> list[list]:
        try:
            params = deepcopy(self._ft_has.get("ohlcv_params", {}))
            params["historical"] = True
            # endTime bounds the window to exactly WEEX_HISTORY_LIMIT candle opens
            params["until"] = start_ms + WEEX_HISTORY_LIMIT * timeframe_to_msecs(timeframe) - 1
            if candle_type not in (CandleType.SPOT, CandleType.FUTURES):
                self.verify_candle_type_support(candle_type)
                params["price"] = str(candle_type)
            return await self._api_async.fetch_ohlcv(
                pair, timeframe=timeframe, since=start_ms, limit=WEEX_HISTORY_LIMIT, params=params
            )
        except ccxt.BadRequest as e:
            if "-1170" in str(e):  # QUERY_TIME_OUT_OF_RANGE: no data that far back
                logger.debug(f"historyKlines out of range for {pair} {dt_from_ts(start_ms)}: {e}")
                return []
            raise TemporaryError(f"historyKlines rejected for {pair}: {e}") from e
        except ccxt.NotSupported as e:
            raise OperationalException(f"Weex historyKlines not supported: {e}") from e
        except ccxt.DDoSProtection as e:
            raise DDosProtection(e) from e
        except (ccxt.OperationFailed, ccxt.ExchangeError) as e:
            raise TemporaryError(
                f"Could not fetch historical candles for {pair}, {timeframe}, {candle_type} "
                f"({dt_from_ts(start_ms)}) due to {e.__class__.__name__}. Message: {e}"
            ) from e
        except ccxt.BaseError as e:
            raise OperationalException(f"Could not fetch historical candles: {e}") from e

    async def _fetch_funding_rate_history(
        self, pair: str, timeframe: str, limit: int, since_ms: int | None = None
    ) -> list[list]:
        # endTime bounds each window so the result does not depend on whether the server
        # returns the first or the last `limit` records of an open-ended range.
        params = {}
        if since_ms is not None:
            params["until"] = since_ms + limit * timeframe_to_msecs(timeframe) - 1
        data = await self._api_async.fetch_funding_rate_history(
            pair, since=since_ms, limit=limit, params=params
        )
        return [[x["timestamp"], x["fundingRate"]] for x in data]

    # ---------------------------------------------------------------- tickers

    def get_tickers(
        self,
        symbols: list[str] | None = None,
        *,
        cached: bool = False,
        market_type: TradingMode | None = None,
    ) -> Tickers:
        # A failing ticker refresh would abort Freqtrade's whole process() loop before the
        # strategy's health check runs; serve the last good tickers instead (the strategy
        # detects the outage from candle freshness and blocks entries).
        try:
            tickers = super().get_tickers(symbols=symbols, cached=cached, market_type=market_type)
        except (TemporaryError, DDosProtection) as e:
            if not self._weex_last_tickers:
                raise
            logger.warning(f"WEEX tickers unavailable, using last good tickers: {e}")
            return deepcopy(self._weex_last_tickers)
        if self.trading_mode == TradingMode.FUTURES and market_type in (None, TradingMode.FUTURES):
            # capi/v3/market/ticker/24hr has no bid/ask -> merge capi/v3/market/ticker/bookTicker
            try:
                bidsasks = self.fetch_bids_asks(symbols, cached=cached)
                self._weex_last_bidsasks = bidsasks
            except (TemporaryError, DDosProtection) as e:
                logger.warning(f"WEEX bookTicker unavailable, using last good bid/ask: {e}")
                bidsasks = self._weex_last_bidsasks
            tickers = deep_merge_dicts(deepcopy(bidsasks), tickers, allow_null_overrides=False)
        if symbols is None:
            self._weex_last_tickers = tickers
        self._weex_mark_ok()
        return tickers

    # ---------------------------------------------------------------- leverage / liquidation

    def get_max_leverage(self, pair: str, stake_amount: float | None) -> float:
        if self.trading_mode != TradingMode.FUTURES:
            return 1.0
        market = self.markets.get(pair, {})
        return float((market.get("limits", {}).get("leverage", {}) or {}).get("max") or 1.0)

    def get_maintenance_ratio_and_amt(
        self, pair: str, notional_value: float
    ) -> tuple[float, float | None]:
        mmr = float(
            self._config["exchange"].get("weex_maintenance_margin_rate", DEFAULT_MAINTENANCE_MARGIN_RATE)
        )
        return mmr, 0.0

    # ---------------------------------------------------------------- health

    def _weex_mark_ok(self) -> None:
        self.weex_last_ok_ms = dt_ts()
