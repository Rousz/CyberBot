"""cyberbot.strategy.core: trend filtresi, tetik, stop/hedef, puan (sentetik veri, saf pandas)."""

import numpy as np
import pandas as pd
import pytest

from cyberbot.strategy import core, defaults
from tests import strategy_data as sd

P = defaults.load({})


def signals(df, **overrides):
    p = defaults.load({"cyberbot": {"strategy": overrides}}) if overrides else P
    return core.populate_signals(df.copy(), p)


def last(df):
    return df.iloc[-1]


# --------------------------------------------------------------------------- long / short


def test_uptrend_pullback_gives_long_with_planned_stop_and_target():
    out = signals(sd.scenario())
    row = last(out)
    assert row.enter_long == 1 and row.enter_short == 0 and row.enter_tag == core.ENTER_TAG
    sl = 98.9 - 0.25 * 0.5  # son 6 mumun en düşüğü - 0.25 x ATR
    assert row.sl_price == pytest.approx(sl)
    assert row.tp_price == pytest.approx(100.5 + 1.8 * (100.5 - sl))
    assert row.rr == pytest.approx(1.8) and row.rr >= P["min_rr"]
    assert row.score == pytest.approx(85.0)  # 20+10+10(ADX 30)+20+10+10+5(hacim 1.5x)
    assert row.regime == "trend"
    assert out["enter_long"].iloc[:-1].sum() == 0  # sadece sinyal mumu
    assert out["enter_short"].sum() == 0


def test_downtrend_mirror_gives_short():
    out = signals(sd.mirror(sd.scenario()))
    row = last(out)
    assert row.enter_short == 1 and row.enter_long == 0
    sl = (200 - 98.9) + 0.25 * 0.5
    entry = 200 - 100.5
    assert row.sl_price == pytest.approx(sl)
    assert row.tp_price == pytest.approx(entry - 1.8 * (sl - entry))
    assert row.score == pytest.approx(85.0)


# --------------------------------------------------------------------------- filtreler


def test_range_regime_low_adx_opens_nothing():
    out = signals(sd.scenario(adx=15))
    assert last(out).regime == "range"
    assert out["enter_long"].sum() == 0 and out["enter_short"].sum() == 0


def test_btc_bearish_blocks_long_but_neutral_allows_with_lower_score():
    assert last(signals(sd.scenario(btc="bear"))).enter_long == 0
    row = last(signals(sd.scenario(btc="neutral")))
    assert row.enter_long == 1 and row.score == pytest.approx(75.0)


def test_btc_bullish_blocks_short():
    df = sd.mirror(sd.scenario())  # short kurulumu, BTC aynalanınca ayı olur
    bull = sd.scenario()
    for col in ("btc_usdt_close_1h", "btc_usdt_ema_mid_1h", "btc_usdt_ema_slow_1h"):
        df[col] = bull[col]
    assert last(signals(df)).enter_short == 0


def test_counter_trend_on_pair_1h_is_blocked():
    assert last(signals(sd.scenario(pair_1h="bear"))).enter_long == 0
    assert last(signals(sd.scenario(pair_1h="neutral"))).enter_long == 0  # close_1h EMA50'nin altında


def test_5m_ema_alignment_is_required():
    df = sd.scenario()
    df["ema_mid"] = 99.5  # EMA20 < EMA50
    assert last(signals(df)).enter_long == 0


def test_weak_setup_scores_below_threshold():
    df = sd.scenario(adx=21, btc="neutral", pair_1h="weak", signal_volume=100.0, body_open=100.2)
    out = signals(df)
    assert last(out).enter_long == 0
    assert last(out).score_long < 70
    # eşik düşürülünce aynı kurulum girer (zorunlu şartlar sağlanıyor)
    assert last(signals(df, entry_score_threshold=40)).enter_long == 1


def test_trigger_needs_volume_and_close_above_previous_high():
    assert last(signals(sd.scenario(signal_volume=90.0))).enter_long == 0
    df = sd.scenario()
    df.loc[len(df) - 1, "close"] = 99.55  # önceki tepe 99.6'nın altında
    assert last(signals(df)).enter_long == 0


def test_trigger_needs_touch_of_ema20_within_lookback():
    df = sd.scenario()
    df.loc[len(df) - 3:, "low"] = 99.3  # hiçbir mum EMA20'ye (99) değmedi
    df["swing_low"] = df["low"].rolling(6).min()
    assert last(signals(df)).enter_long == 0


def test_stop_distance_bounds():
    # ATR çok büyük: stop > %3
    assert last(signals(sd.scenario(atr=8.0))).enter_long == 0
    # stop çok yakın: min_stop_pct yükseltilince (%2) aynı kurulum reddedilir
    assert last(signals(sd.scenario(), stop={"min_stop_pct": 0.02})).enter_long == 0
    st = core.stops_targets(sd.scenario(), P)
    assert 0.004 <= st["stop_pct_long"].iloc[-1] <= 0.03


def test_staleness_guard_blocks_row_with_old_informative_candle():
    df = sd.scenario()
    df.loc[len(df) - 1, "btc_usdt_date_1h"] -= pd.Timedelta("1h")
    assert last(signals(df)).enter_long == 0
    df = sd.scenario()
    df.loc[len(df) - 1, "date_1h"] -= pd.Timedelta("1h")
    assert last(signals(df)).enter_long == 0
    assert not core.informative_fresh(df.drop(columns=["date_1h"]), "date_1h").any()


def test_informative_fresh_expected_dates():
    dates = pd.Series(pd.to_datetime(["2026-01-10 14:10", "2026-01-10 14:55"], utc=True))
    df = pd.DataFrame({"date": dates,
                       "date_1h": pd.to_datetime(["2026-01-10 13:00", "2026-01-10 14:00"], utc=True)})
    assert core.informative_fresh(df, "date_1h").tolist() == [True, True]


# --------------------------------------------------------------------------- puan çerçevesi


def test_weighted_average_ignores_disabled_and_unimplemented_layers():
    idx = pd.RangeIndex(2)
    s = pd.Series([80.0, 60.0])
    p = defaults.load({"cyberbot": {"strategy": {"layers": {"trend": True, "news": True},
                                                 "weights": {"trend": 2.0, "news": 5.0}}}})
    used, missing = core.enabled_layers(p)
    assert used == ["trend"] and missing == ["news"]
    assert core.combine_scores({"trend": s, "news": pd.Series([0.0, 0.0])}, p, idx).tolist() == [80.0, 60.0]
    p_off = defaults.load({"cyberbot": {"strategy": {"layers": {"trend": False}}}})
    assert core.combine_scores({"trend": s}, p_off, idx).isna().all()
    assert last(signals(sd.scenario(), layers={"trend": False})).enter_long == 0


def test_validate_rejects_target_below_min_rr():
    assert defaults.validate(P) == []
    bad = defaults.load({"cyberbot": {"strategy": {"target_rr": 1.2}}})
    assert any("target_rr" in e for e in defaults.validate(bad))


# --------------------------------------------------------------------------- gerçek göstergelerle uçtan uca


def _pipeline(five, btc):
    df = core.add_indicators(five.copy(), P)
    inf = core.add_informative(sd.resample(five, "1h"), P)
    btc_inf = core.add_informative(sd.resample(btc, "1h"), P)
    return core.populate_signals(sd.with_informative(df, inf, btc_inf), P)


def test_end_to_end_longs_in_uptrend_shorts_in_downtrend_none_in_range():
    five, btc = sd.trend_series(seed=1), sd.trend_series(seed=51)
    out = _pipeline(five, btc)
    day = (out["date"] - out["date"].iloc[0]).dt.days
    up, flat, down = day < 11, (day >= 11) & (day < 13), day >= 13
    assert out.loc[up, "enter_long"].sum() > 0 and out.loc[up, "enter_short"].sum() == 0
    assert out.loc[down, "enter_short"].sum() > 0 and out.loc[down, "enter_long"].sum() == 0
    assert out.loc[flat & (out["regime"] == "range"), ["enter_long", "enter_short"]].sum().sum() == 0
    sig = out[(out.enter_long == 1) | (out.enter_short == 1)]
    assert (sig["rr"] >= 1.5).all() and (sig["score"] >= 70).all()
    pct = (sig["close"] - sig["sl_price"]).abs() / sig["close"]
    assert pct.between(0.004, 0.03).all()


def test_signals_do_not_change_when_future_rows_are_removed():
    five, btc = sd.trend_series(seed=2), sd.trend_series(seed=52)
    full = _pipeline(five, btc)
    cut = len(five) - 2000
    part = _pipeline(five.iloc[:cut].reset_index(drop=True), btc.iloc[:cut].reset_index(drop=True))
    cols = ["enter_long", "enter_short", "score", "sl_price", "tp_price"]
    a = full.iloc[:cut - 12][cols].reset_index(drop=True)  # son 1h mumu henüz kapanmamış satırlar hariç
    b = part.iloc[:cut - 12][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)
    assert a[["enter_long", "enter_short"]].to_numpy().sum() > 0


# --------------------------------------------------------------------------- plan, çıkış, stake, derinlik


def test_plan_from_fill_keeps_stop_price_and_recomputes_target():
    plan = core.plan_from_fill(100.2, 98.775, False, 1.8, 0.03)
    assert plan["sl"] == pytest.approx(98.775)
    assert plan["tp"] == pytest.approx(100.2 + 1.8 * (100.2 - 98.775))
    assert (plan["tp"] - 100.2) / (100.2 - plan["sl"]) == pytest.approx(1.8) and not plan["crossed"]
    short = core.plan_from_fill(99.0, 101.0, True, 1.8, 0.03)
    assert short["tp"] == pytest.approx(99.0 - 3.6) and not short["crossed"]
    assert core.plan_from_fill(98.0, 98.775, False, 1.8, 0.03)["crossed"]  # dolum stopun altında
    fb = core.plan_from_fill(100.0, None, False, 1.8, 0.03)
    assert fb["source"] == "fallback" and fb["sl"] == pytest.approx(97.0)


def test_exit_reason():
    kw = dict(crossed=False, held_minutes=10, max_hold_minutes=180)
    assert core.exit_reason(is_short=False, rate=103.0, tp=103.0, **kw) == "take_profit"
    assert core.exit_reason(is_short=False, rate=102.9, tp=103.0, **kw) is None
    assert core.exit_reason(is_short=True, rate=96.0, tp=96.5, **kw) == "take_profit"
    assert core.exit_reason(is_short=True, rate=97.0, tp=96.5, **kw) is None
    assert core.exit_reason(is_short=False, rate=100, tp=103, crossed=False, held_minutes=180,
                            max_hold_minutes=180) == "time_stop"
    assert core.exit_reason(is_short=False, rate=100, tp=103, crossed=True, held_minutes=0,
                            max_hold_minutes=180) == "fill_beyond_stop"


def test_risk_stake():
    # özsermaye 1000, risk %1 = 10 USDT, stop %1, 3x -> teminat 333.3 (kayıp 333.3*3*0.01 = 10)
    stake = core.risk_stake(equity=1000, risk_per_trade=0.01, rate=100, sl=99, leverage=3, min_stake=1,
                            max_stake=900, proposed_stake=None)
    assert stake == pytest.approx(1000 * 0.01 / (0.01 * 3))
    # slot payı (bakiye / max_open_trades) ile sınırlı
    assert core.risk_stake(equity=1000, risk_per_trade=0.01, rate=100, sl=99.5, leverage=3, min_stake=1,
                           max_stake=900, proposed_stake=330) == pytest.approx(330)
    assert core.risk_stake(equity=1000, risk_per_trade=0.01, rate=100, sl=99.5, leverage=3, min_stake=1,
                           max_stake=900, proposed_stake=330, cap_to_slot=False) == pytest.approx(666.67, rel=1e-3)
    assert core.risk_stake(equity=1000, risk_per_trade=0.01, rate=100, sl=None, leverage=3, min_stake=1,
                           max_stake=900) == 0
    assert core.risk_stake(equity=1000, risk_per_trade=0.01, rate=100, sl=99, leverage=3, min_stake=50,
                           max_stake=40) == 0  # imkânsız


def test_depth_ok_counts_only_band_on_taken_side():
    book = {"bids": [[99.9, 100], [99.5, 1000], [99.0, 10000]],
            "asks": [[100.1, 100], [100.4, 1000], [101.0, 10000]]}
    ok, notional = core.depth_ok(book, "long", 0.005, 200000)  # mid 100 -> asks <= 100.5
    assert notional == pytest.approx(100.1 * 100 + 100.4 * 1000) and not ok
    ok, notional = core.depth_ok(book, "short", 0.005, 200000)  # bids >= 99.5
    assert notional == pytest.approx(99.9 * 100 + 99.5 * 1000) and not ok
    assert core.depth_ok(book, "long", 0.005, 50000)[0]
    assert core.depth_ok(book, "long", 0.02, 200000)[0]  # geniş bant 101'i de sayar
    assert core.depth_ok({"bids": [], "asks": []}, "long", 0.005, 1) == (False, 0.0)


def test_signal_rows_keyed_by_candle_open_ms():
    out = signals(sd.scenario())
    rows = core.signal_rows(out)
    (ms, row), = rows.items()
    assert ms == int(out["date"].iloc[-1].timestamp() * 1000)
    assert row["side"] == "long" and row["score"] == pytest.approx(85.0) and np.isfinite(row["sl"])
