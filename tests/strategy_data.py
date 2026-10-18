"""Strateji testleri için sentetik veri (internetsiz, deterministik).

- scenario(): elle kurulmuş tek bir geri çekilme kurulumu; gösterge sütunları sabit verilir,
  böylece core.populate_signals'ın kuralları tek tek denetlenebilir.
- trend_series() / write_futures_data(): rejimli (yukarı/aşağı/yatay) 5m fiyat serisi ve
  Freqtrade backtest'i için futures + 1h mark + 1h funding_rate feather dosyaları.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2026-01-10 00:00", tz="UTC")
PRICE_COLS = ("open", "high", "low", "close")


def _inf_date(dates: pd.Series) -> pd.Series:
    """5m satırına bağlanması gereken (en son kapanmış) 1h mumun açılışı."""
    return (dates + pd.Timedelta("5min")).dt.floor("1h") - pd.Timedelta("1h")


def scenario(*, n: int = 30, adx: float = 30.0, atr: float = 0.5, btc: str = "bull", pair_1h: str = "bull",
             signal_volume: float = 150.0, pullback_low: float = 98.9, held: bool = True,
             body_open: float = 99.4) -> pd.DataFrame:
    """Yükselen trendde EMA20'ye geri çekilme + yukarı kırılım; son satır sinyal mumu.

    EMA20=99, EMA50=97, EMA200=95 (5m), ATR=atr, hacim SMA=100. Son 3 mum: geri çekilme
    (low=pullback_low, EMA20'ye değer), toparlanma, sinyal (close 100.5 > önceki tepe 99.6).
    btc / pair_1h: "bull" | "weak" | "neutral" | "bear".
    """
    dates = pd.Series(pd.date_range(START, periods=n, freq="5min", tz="UTC"))
    df = pd.DataFrame({"date": dates, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2,
                       "volume": 100.0})
    df.loc[n - 3, PRICE_COLS] = (100.0, 100.1, pullback_low, 99.2)
    df.loc[n - 2, PRICE_COLS] = (99.2, 99.6, 99.0, 99.4)
    df.loc[n - 1, PRICE_COLS] = (body_open, 100.6, 99.3, 100.5)
    df.loc[n - 1, "volume"] = signal_volume
    df["ema_fast"], df["ema_mid"], df["ema_slow"] = 99.0, 97.0, 95.0
    if not held:  # geri çekilme EMA50'nin altına sarktı (kalitesiz)
        df.loc[n - 3, "low"] = 96.5
    df["adx"] = adx
    df["atr"] = atr
    df["vol_sma"] = 100.0
    df["swing_low"] = df["low"].rolling(6).min()
    df["swing_high"] = df["high"].rolling(6).max()
    # (close_1h, ema50_1h, ema200_1h); "weak": fiyat iki EMA'nın üstünde ama EMA50 < EMA200
    levels = {"bull": (101.0, 99.0, 97.0), "weak": (101.0, 98.0, 99.0), "neutral": (98.0, 99.0, 97.0),
              "bear": (95.0, 97.0, 99.0)}
    df["close_1h"], df["ema_mid_1h"], df["ema_slow_1h"] = levels[pair_1h]
    df["btc_usdt_close_1h"], df["btc_usdt_ema_mid_1h"], df["btc_usdt_ema_slow_1h"] = levels[btc]
    df["date_1h"] = _inf_date(dates)
    df["btc_usdt_date_1h"] = _inf_date(dates)
    return df


def mirror(df: pd.DataFrame, center: float = 100.0) -> pd.DataFrame:
    """Fiyatları center etrafında aynalar: long kurulumu -> short kurulumu."""
    out = df.copy()
    m = lambda s: 2 * center - s  # noqa: E731
    out["open"], out["close"] = m(df["open"]), m(df["close"])
    out["high"], out["low"] = m(df["low"]), m(df["high"])
    for col in ("ema_fast", "ema_mid", "ema_slow", "close_1h", "ema_mid_1h", "ema_slow_1h",
                "btc_usdt_close_1h", "btc_usdt_ema_mid_1h", "btc_usdt_ema_slow_1h"):
        out[col] = m(df[col])
    out["swing_low"] = out["low"].rolling(6).min()
    out["swing_high"] = out["high"].rolling(6).max()
    return out


# --------------------------------------------------------------------------- seri üretimi

# (gün sayısı, yön): +1 yukarı trend, 0 yatay, -1 aşağı trend
DEFAULT_REGIMES = ((11, 1), (2, 0), (11, -1))


def trend_series(*, start: pd.Timestamp = START, regimes=DEFAULT_REGIMES, base: float = 100.0, seed: int = 1,
                 leg: int = 12, pullback: int = 6, step: float = 0.0015, pb_step: float = 0.0022,
                 noise: float = 0.0006) -> pd.DataFrame:
    """Rejimli 5m OHLCV (testere dişi): trendde `leg` mum trend yönünde `step`, sonra `pullback`
    mum ters yönde `pb_step` (EMA20'ye geri çekilme) + gürültü. Yatayda simetrik salınım
    (ADX düşük). Hacim, büyük hareketli mumlarda daha yüksek."""
    rng = np.random.default_rng(seed)
    cycle = leg + pullback
    offset = int(rng.integers(0, cycle))
    parts = []
    for days, direction in regimes:
        idx = (np.arange(int(days * 288)) + offset) % cycle
        if direction == 0:
            parts.append(np.where(idx < cycle // 2, step, -step))
        else:
            parts.append(direction * np.where(idx < leg, step, -pb_step))
    rets = np.concatenate(parts)
    n = len(rets)
    rets = rets + rng.normal(0, noise, n)
    close = base * np.exp(np.cumsum(rets))
    op = np.r_[base, close[:-1]]
    wick = np.abs(rng.normal(0, noise * 1.5, n)) * close
    high = np.maximum(op, close) + wick
    low = np.minimum(op, close) - wick
    volume = rng.uniform(80, 120, n) * np.where(np.abs(rets) > step * 0.5, 1.3, 0.9)
    dates = pd.date_range(start, periods=n, freq="5min", tz="UTC")
    return pd.DataFrame({"date": dates, "open": op, "high": high, "low": low, "close": close, "volume": volume})


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.set_index("date").resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna().reset_index()


def pair_file(pair: str) -> str:
    return pair.replace("/", "_").replace(":", "_")


def write_futures_data(datadir: Path, series: dict[str, pd.DataFrame]) -> None:
    """Freqtrade futures backtest dosyaları: <datadir>/futures/{PAIR}-{tf}-{type}.feather."""
    folder = Path(datadir) / "futures"
    folder.mkdir(parents=True, exist_ok=True)
    for pair, five in series.items():
        name = pair_file(pair)
        five.to_feather(folder / f"{name}-5m-futures.feather")
        hour = resample(five, "1h")
        hour.to_feather(folder / f"{name}-1h-futures.feather")
        hour.to_feather(folder / f"{name}-1h-mark.feather")
        funding_dates = pd.date_range(five["date"].iloc[0].floor("8h"), five["date"].iloc[-1], freq="8h")
        pd.DataFrame({"date": funding_dates, "funding_rate": 0.0001}).to_feather(
            folder / f"{name}-1h-funding_rate.feather")


def with_informative(df5: pd.DataFrame, pair_1h: pd.DataFrame, btc_1h: pd.DataFrame,
                     btc_prefix: str = "btc_usdt_") -> pd.DataFrame:
    """@informative('1h') ve @informative('1h', 'BTC/...') ile aynı sütun adları ve birleştirme."""
    from freqtrade.strategy import merge_informative_pair

    df = merge_informative_pair(df5, pair_1h, "5m", "1h", ffill=True)
    btc = btc_1h.rename(columns={c: f"{btc_prefix}{c}" for c in btc_1h.columns})
    return merge_informative_pair(df, btc, "5m", "1h", ffill=True, append_timeframe=False, suffix="1h",
                                  date_column=f"{btc_prefix}date")
