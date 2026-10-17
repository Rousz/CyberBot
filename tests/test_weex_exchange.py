"""Freqtrade Weex exchange subclass against real freqtrade 2026.9 + ccxt code, offline."""

import ccxt
import pytest

from freqtrade.enums import CandleType, RunMode
from freqtrade.exceptions import OperationalException, TemporaryError
from freqtrade_ext.weex import WEEX_HISTORY_LIMIT, Weex
from tests.weex_router import TF_MS, WeexRouter, make_exchange, offline_weex

BTC = "BTC/USDT:USDT"
ETH = "ETH/USDT:USDT"


@pytest.fixture
def router():
    with offline_weex() as r:
        yield r


@pytest.fixture
def ex(router, tmp_path):
    exchange = make_exchange(tmp_path)
    yield exchange
    exchange.close()


def run(ex, coro):
    return ex.loop.run_until_complete(coro)


def test_resolver_returns_weex_subclass_in_isolated_futures(ex):
    assert type(ex) is Weex
    assert ex.trading_mode.value == "futures" and ex.margin_mode.value == "isolated"
    assert BTC in ex.markets and ETH in ex.markets


def test_contract_size_is_one_because_weex_quantities_are_base_units(ex):
    # ccxt reports contractVal (0.001 for ETH) as contractSize; WEEX order quantity is ETH.
    assert ex.markets[ETH]["contractSize"] == pytest.approx(0.001)
    assert ex.get_contract_size(ETH) == 1.0
    assert ex.get_contract_size("NOPE/USDT:USDT") is None
    assert ex._amount_to_contracts(ETH, 0.5) == pytest.approx(0.5)


def test_max_leverage_comes_from_market_limits_not_tiers(ex):
    assert ex.get_max_leverage(ETH, 100) == pytest.approx(400)
    assert ex.get_max_leverage("SOL/USDT:USDT", 100) == pytest.approx(200)


def test_maintenance_ratio_and_dry_run_liquidation_price(ex):
    assert ex.get_maintenance_ratio_and_amt(ETH, 1000) == (0.01, 0.0)
    liq = ex.get_liquidation_price(ETH, open_rate=100.0, is_short=False, amount=3.0, stake_amount=100.0,
                                   leverage=3.0, wallet_balance=100.0)
    assert liq is not None and 60 < liq < 75  # ~0.69 x open at 3x with 5% buffer


def test_timeframes_are_contract_intervals(ex):
    assert {"5m", "15m", "1h", "1d"} <= set(ex.timeframes)
    assert not {"2h", "6h", "8h", "1M"} & set(ex.timeframes)


def test_order_book_pricing_and_l2_override(ex):
    assert ex.exchange_has("fetchL2OrderBook")
    book = ex.fetch_l2_order_book(ETH, 20)
    assert book["bids"] and book["asks"]
    rate = ex.get_rate(ETH, side="entry", is_short=False, refresh=True)
    assert rate == pytest.approx(2000.2)  # long entry, price_side=other -> best ask


def test_tickers_are_merged_with_book_ticker(ex):
    tickers = ex.get_tickers()
    assert tickers[ETH]["quoteVolume"] and tickers[ETH]["bid"] == pytest.approx(2081.79)
    assert tickers[ETH]["ask"] == pytest.approx(2081.81)
    assert tickers[BTC]["bid"] == pytest.approx(74010.5)


def test_tickers_fall_back_to_last_good_on_outage(ex, router):
    first = ex.get_tickers()
    router.fail_paths["capi/v3/market/ticker/24hr"] = ccxt.NetworkError("down")
    second = ex.get_tickers()
    assert second[ETH]["bid"] == first[ETH]["bid"]


def test_tickers_raise_when_nothing_cached(router, tmp_path):
    router.fail_paths["capi/v3/market/ticker/24hr"] = ccxt.NetworkError("down")
    exchange = make_exchange(tmp_path)
    try:
        with pytest.raises(TemporaryError):
            exchange.get_tickers()
    finally:
        exchange.close()


def test_recent_candles_use_klines_endpoint(ex, router):
    res = run(ex, ex._async_get_candle_history(ETH, "5m", CandleType.FUTURES, since_ms=None))
    assert len(res[3]) >= 999
    assert router.calls_to("capi/v3/market/klines") and not router.calls_to("capi/v3/market/historyKlines")
    assert ex.weex_last_ok_ms is not None


def test_old_since_is_served_from_history_in_100_candle_chunks(ex, router):
    now = router.now_ms()
    since = (now - 30 * 24 * 3_600_000) // TF_MS["5m"] * TF_MS["5m"]
    _, _, _, rows, _ = run(ex, ex._async_get_candle_history(ETH, "5m", CandleType.FUTURES, since_ms=since))
    chunks = router.calls_to("capi/v3/market/historyKlines")
    assert len(chunks) == 10
    assert all(int(c["endTime"]) - int(c["startTime"]) == WEEX_HISTORY_LIMIT * TF_MS["5m"] - 1 for c in chunks)
    times = [r[0] for r in rows]
    assert len(times) == 1000 and times[0] == since
    assert all(b - a == TF_MS["5m"] for a, b in zip(times, times[1:]))  # no gap at chunk borders


def test_mark_history_passes_price_type(ex, router):
    now = router.now_ms()
    since = (now - 200 * 24 * 3_600_000) // TF_MS["1h"] * TF_MS["1h"]
    run(ex, ex._async_get_candle_history(ETH, "1h", CandleType.MARK, since_ms=since))
    assert router.calls_to("capi/v3/market/historyKlines")[0]["priceType"] == "MARK"


def test_refresh_with_old_since_returns_continuous_frame(ex, router):
    now = router.now_ms()
    since = now - 5 * 24 * 3_600_000
    res = ex.refresh_latest_ohlcv([(ETH, "5m", CandleType.FUTURES)], since_ms=since, cache=False)
    df = res[(ETH, "5m", CandleType.FUTURES)]
    diffs = df["date"].diff().dropna().dt.total_seconds().unique()
    assert len(df) > 5 * 288 - 5 and list(diffs) == [300.0]


def test_history_before_exchange_start_returns_what_exists(router, tmp_path):
    router.history_days = 10
    exchange = make_exchange(tmp_path)
    try:
        now = router.now_ms()
        since = (now - 60 * 24 * 3_600_000) // TF_MS["1h"] * TF_MS["1h"]
        _, _, _, rows, _ = run(exchange, exchange._async_get_candle_history(ETH, "1h", CandleType.FUTURES, since_ms=since))
        assert rows == []  # whole 1000h window is older than the 10 days of history
    finally:
        exchange.close()


def test_funding_history_window_is_bounded_by_until(ex, router):
    now = router.now_ms()
    since = now - 3 * 24 * 3_600_000
    rows = run(ex, ex._fetch_funding_rate_history(ETH, "1h", 1000, since_ms=since))
    call = router.calls_to("capi/v3/market/fundingRate")[-1]
    assert int(call["endTime"]) == since + 1000 * 3_600_000 - 1
    assert rows and all(r[1] == pytest.approx(0.0001) for r in rows)


def test_live_runmode_is_blocked_before_any_network(router, tmp_path):
    with pytest.raises(OperationalException, match="canlı işlem"):
        make_exchange(tmp_path, runmode=RunMode.LIVE, dry_run=False)
    assert router.calls == []


def test_dry_run_order_respects_base_unit_amount(ex):
    order = ex.create_order(pair=ETH, ordertype="market", side="buy", amount=0.9999, rate=2000.2,
                            leverage=3.0)
    assert order["amount"] == pytest.approx(0.999)  # quantityPrecision 3, not scaled by contractVal
