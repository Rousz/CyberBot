"""CyberScalp saf sinyal mantığı (pandas + talib; Freqtrade nesnesi yok).

Akış (her satır = KAPANMIŞ 5m mum; Freqtrade oluşan mumu zaten düşürür):
  add_indicators        5m EMA20/50/200, ADX14, ATR14, hacim SMA20, swing dip/tepe
  add_informative       1h EMA50/200 (hem paritenin hem BTC'nin 1h verisine uygulanır)
  populate_signals      trend katmanı (zorunlu filtre + puan) -> tetik -> stop/hedef -> toplam puan
                        -> enter_long/enter_short, score, sl_price, tp_price, rr

Kurallar: shift(-n) yok, merkezli pencere yok, tüm sütun üzerinden normalizasyon yok.
Her değer sadece o satır ve öncesinden hesaplanır (lookahead yok).

Trend tanımları (long; short tam tersi):
  5m hizalı     : EMA20 > EMA50 > EMA200
  1h parite     : close_1h > EMA50_1h ve close_1h > EMA200_1h
  BTC 1h filtresi: BTC "ayı" = close < EMA50 < EMA200 (1h). Long sadece BTC ayı DEĞİLKEN,
                  short sadece BTC "boğa" (close > EMA50 > EMA200) DEĞİLKEN.
  Rejim         : ADX >= adx_trend -> trend; altı yatay. Faz 1 yatayda işlem AÇMAZ
                  (yatay kurulumlar destek/direnç tespiti ister, Faz 4).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib

IMPLEMENTED_LAYERS = frozenset({"trend"})
ALL_LAYERS = ("trend", "indicators", "patterns", "derivatives", "news")
ENTER_TAG = "trend_pullback"


# --------------------------------------------------------------------------- göstergeler


def _f(series: pd.Series) -> np.ndarray:
    return series.to_numpy(dtype="float64")


def ema(series: pd.Series, period: int) -> pd.Series:
    """Üstel ortalama (ilk değerle tohumlanır, ilk `period` satır NaN).
    talib'in SMA tohumuna göre kısa geçmişte daha hızlı yakınsar: backtest başlangıç mumu
    sayısı (startup_candle_count) ile canlıdaki uzun geçmiş arasındaki fark küçük kalır."""
    return series.astype("float64").ewm(span=int(period), adjust=False, min_periods=int(period)).mean()


def add_indicators(df: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    """5m göstergeleri. df: date, open, high, low, close, volume."""
    t, trig, s = p["trend"], p["trigger"], p["stop"]
    close, high, low = _f(df["close"]), _f(df["high"]), _f(df["low"])
    df["ema_fast"] = ema(df["close"], t["ema_fast"])
    df["ema_mid"] = ema(df["close"], t["ema_mid"])
    df["ema_slow"] = ema(df["close"], t["ema_slow"])
    df["adx"] = talib.ADX(high, low, close, timeperiod=int(t["adx_period"]))
    df["atr"] = talib.ATR(high, low, close, timeperiod=int(s["atr_period"]))
    df["vol_sma"] = df["volume"].rolling(int(trig["vol_sma"])).mean()
    n = int(s["swing_lookback"])
    df["swing_low"] = df["low"].rolling(n).min()
    df["swing_high"] = df["high"].rolling(n).max()
    return df


def add_informative(df: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    """1h bilgi zaman dilimi göstergeleri (parite 1h ve BTC 1h için aynı)."""
    t = p["trend"]
    df["ema_mid"] = ema(df["close"], t["inf_ema_mid"])
    df["ema_slow"] = ema(df["close"], t["inf_ema_slow"])
    return df


def informative_fresh(df: pd.DataFrame, date_col: str, inf_tf: str = "1h", tf: str = "5m") -> pd.Series:
    """Sinyal satırına bağlanan bilgi mumu beklenen (en son kapanmış) mum mu?

    Canlıda yeni 1h mum borsada geç açılırsa Freqtrade kapanmış 1h mumu 15 sn bekletir;
    o anda analiz edilen 5m satırı bir önceki saatin değerleriyle kalır. Beklenen tarih:
    floor(date + tf, inf_tf) - inf_tf. Backtest'te her zaman doğrudur.
    """
    if date_col not in df.columns:
        return pd.Series(False, index=df.index)
    inf = pd.Timedelta(inf_tf)
    expected = (df["date"] + pd.Timedelta(tf)).dt.floor(inf_tf) - inf
    return (df[date_col] == expected).fillna(False).astype(bool)


# --------------------------------------------------------------------------- yardımcılar


def _ramp(x: pd.Series, lo: float, hi: float) -> pd.Series:
    """lo -> 0, hi -> 1 arası doğrusal, kırpılmış."""
    return ((x - lo) / (hi - lo)).clip(0.0, 1.0)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col] if col in df.columns else pd.Series(np.nan, index=df.index)


# --------------------------------------------------------------------------- katman A: trend


def trend_layer(df: pd.DataFrame, p: dict[str, Any], btc_prefix: str = "btc_usdt_") -> dict[str, pd.Series]:
    """Zorunlu trend filtresi (long_ok/short_ok) ve trend alt puanı (0-100, her yön için).

    Puan bileşenleri (long; short ayna): 5m hizalı 20 + 1h yığın (EMA50>EMA200) 10, değilse 5
    + ADX adx_trend..adx_strong arası 0-20 + BTC 1h boğa 20 / nötr 10 + geri çekilme EMA50
    üstünde tuttu 10 + sinyal mumu gövde/aralık 0.3..0.7 -> 0-10 + hacim oranı 1x..2x -> 0-10.
    Temiz kurulum >= 70, zayıf kurulum (ADX ~eşik, BTC nötr, derin geri çekilme) < 70.
    """
    t, trig = p["trend"], p["trigger"]
    c1h, m1h, s1h = _num(df, "close_1h"), _num(df, "ema_mid_1h"), _num(df, "ema_slow_1h")
    bc = _num(df, f"{btc_prefix}close_1h")
    bm = _num(df, f"{btc_prefix}ema_mid_1h")
    bs = _num(df, f"{btc_prefix}ema_slow_1h")

    align_long = (df["ema_fast"] > df["ema_mid"]) & (df["ema_mid"] > df["ema_slow"])
    align_short = (df["ema_fast"] < df["ema_mid"]) & (df["ema_mid"] < df["ema_slow"])
    pair_long = (c1h > m1h) & (c1h > s1h)
    pair_short = (c1h < m1h) & (c1h < s1h)
    btc_bull = (bc > bm) & (bm > bs)
    btc_bear = (bc < bm) & (bm < bs)
    btc_known = bc.notna() & bm.notna() & bs.notna()
    trending = df["adx"] >= float(t["adx_trend"])

    long_ok = trending & align_long & pair_long & btc_known & ~btc_bear
    short_ok = trending & align_short & pair_short & btc_known & ~btc_bull

    n = int(trig["pullback_lookback"])
    held_long = df["low"].rolling(n).min() > df["ema_mid"]
    held_short = df["high"].rolling(n).max() < df["ema_mid"]
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    body = ((df["close"] - df["open"]) / rng).fillna(0.0)
    vol_ratio = (df["volume"] / df["vol_sma"].replace(0, np.nan)).fillna(0.0)
    adx_pts = 20 * _ramp(df["adx"], float(t["adx_trend"]), float(t["adx_strong"]))
    vol_pts = 10 * _ramp(vol_ratio, 1.0, 2.0)

    score_long = (
        20.0
        + np.where(m1h > s1h, 10.0, 5.0)
        + adx_pts
        + np.where(btc_bull, 20.0, 10.0)
        + np.where(held_long, 10.0, 0.0)
        + 10 * _ramp(body, 0.3, 0.7)
        + vol_pts
    )
    score_short = (
        20.0
        + np.where(m1h < s1h, 10.0, 5.0)
        + adx_pts
        + np.where(btc_bear, 20.0, 10.0)
        + np.where(held_short, 10.0, 0.0)
        + 10 * _ramp(-body, 0.3, 0.7)
        + vol_pts
    )
    # gösterge eksikse (ısınma) puan yok
    valid = df[["ema_slow", "adx"]].notna().all(axis=1) & c1h.notna() & s1h.notna() & btc_known
    return {
        "long_ok": long_ok.fillna(False).astype(bool),
        "short_ok": short_ok.fillna(False).astype(bool),
        "score_long": score_long.where(valid),
        "score_short": score_short.where(valid),
        "regime_trend": trending.fillna(False).astype(bool),
    }


# --------------------------------------------------------------------------- tetik


def triggers(df: pd.DataFrame, p: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    """Trend yönünde geri çekilme dönüşü (kapanmış mumla teyit).

    Long: son pullback_lookback mumda low <= EMA20 olmuş, sinyal mumu EMA20 üstünde kapanmış,
    yeşil mum, kapanış önceki mumun tepesinin üstünde, hacim >= vol_mult x SMA20(hacim).
    """
    trig = p["trigger"]
    n = int(trig["pullback_lookback"])
    vol_ok = (df["vol_sma"] > 0) & (df["volume"] >= float(trig["vol_mult"]) * df["vol_sma"])
    touched_long = (df["low"] <= df["ema_fast"]).astype(float).rolling(n).max() > 0
    touched_short = (df["high"] >= df["ema_fast"]).astype(float).rolling(n).max() > 0
    long_trig = (
        touched_long
        & (df["close"] > df["ema_fast"])
        & (df["close"] > df["open"])
        & (df["close"] > df["high"].shift(1))
        & vol_ok
    )
    short_trig = (
        touched_short
        & (df["close"] < df["ema_fast"])
        & (df["close"] < df["open"])
        & (df["close"] < df["low"].shift(1))
        & vol_ok
    )
    return long_trig.fillna(False).astype(bool), short_trig.fillna(False).astype(bool)


# --------------------------------------------------------------------------- stop / hedef


def stops_targets(df: pd.DataFrame, p: dict[str, Any]) -> dict[str, pd.Series]:
    """Sinyal mumu kapanışına (giriş referansı) göre stop, hedef, stop mesafesi, R/R."""
    s = p["stop"]
    rr_target = float(p["target_rr"])
    buf = float(s["atr_buffer"]) * df["atr"]
    ref = df["close"]
    sl_long = df["swing_low"] - buf
    sl_short = df["swing_high"] + buf
    risk_long = ref - sl_long
    risk_short = sl_short - ref
    tp_long = ref + rr_target * risk_long
    tp_short = ref - rr_target * risk_short
    pct_long = risk_long / ref
    pct_short = risk_short / ref
    lo, hi = float(s["min_stop_pct"]), float(s["max_stop_pct"])
    rr_long = (tp_long - ref) / risk_long.where(risk_long > 0)
    rr_short = (ref - tp_short) / risk_short.where(risk_short > 0)
    return {
        "sl_long": sl_long, "tp_long": tp_long, "stop_pct_long": pct_long, "rr_long": rr_long,
        "sl_short": sl_short, "tp_short": tp_short, "stop_pct_short": pct_short, "rr_short": rr_short,
        "stop_ok_long": ((pct_long >= lo) & (pct_long <= hi)).fillna(False).astype(bool),
        "stop_ok_short": ((pct_short >= lo) & (pct_short <= hi)).fillna(False).astype(bool),
    }


# --------------------------------------------------------------------------- puan birleştirme


def enabled_layers(p: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(kullanılan katmanlar, açık ama henüz yazılmamış katmanlar)."""
    on = [name for name, flag in (p.get("layers") or {}).items() if flag]
    used = [name for name in on if name in IMPLEMENTED_LAYERS]
    missing = [name for name in on if name not in IMPLEMENTED_LAYERS]
    return used, missing


def combine_scores(layer_scores: dict[str, pd.Series], p: dict[str, Any], index: pd.Index) -> pd.Series:
    """Toplam puan = sum(w_i * s_i) / sum(w_i), sadece açık ve yazılmış katmanlar.
    Hiç katman yoksa NaN (giriş olmaz)."""
    used, _ = enabled_layers(p)
    weights = p.get("weights") or {}
    num = pd.Series(0.0, index=index)
    den = 0.0
    for name in used:
        w = float(weights.get(name, 1.0))
        if w <= 0 or name not in layer_scores:
            continue
        num = num + w * layer_scores[name]
        den += w
    if den == 0:
        return pd.Series(np.nan, index=index)
    return num / den


# --------------------------------------------------------------------------- sinyaller


def populate_signals(df: pd.DataFrame, p: dict[str, Any], btc_prefix: str = "btc_usdt_",
                     timeframe: str = "5m") -> pd.DataFrame:
    """Giriş sinyali + planlanan stop/hedef/puan sütunları.

    Zorunlu (puandan bağımsız): trend filtresi uyumu, kapanmış mum teyidi (tetik),
    stop mesafesi sınırlar içinde, R/R >= min_rr, bilgi mumları taze. Sonra puan >= eşik.
    """
    trend = trend_layer(df, p, btc_prefix)
    long_trig, short_trig = triggers(df, p)
    st = stops_targets(df, p)
    fresh = informative_fresh(df, "date_1h", "1h", timeframe) & informative_fresh(
        df, f"{btc_prefix}date_1h", "1h", timeframe
    )
    min_rr = float(p["min_rr"]) - 1e-9
    total_long = combine_scores({"trend": trend["score_long"]}, p, df.index)
    total_short = combine_scores({"trend": trend["score_short"]}, p, df.index)
    threshold = float(p["entry_score_threshold"])

    mand_long = trend["long_ok"] & long_trig & st["stop_ok_long"] & (st["rr_long"] >= min_rr) & fresh
    mand_short = trend["short_ok"] & short_trig & st["stop_ok_short"] & (st["rr_short"] >= min_rr) & fresh
    go_long = (mand_long & (total_long >= threshold)).fillna(False).astype(bool)
    go_short = (mand_short & (total_short >= threshold)).fillna(False).astype(bool) & ~go_long

    df["regime"] = np.where(trend["regime_trend"], "trend", "range")
    df["score_long"] = total_long
    df["score_short"] = total_short
    df["enter_long"] = go_long.astype(int)
    df["enter_short"] = go_short.astype(int)
    df["enter_tag"] = np.where(go_long | go_short, ENTER_TAG, None)
    df["score"] = np.where(go_long, total_long, np.where(go_short, total_short, np.nan))
    df["sl_price"] = np.where(go_long, st["sl_long"], np.where(go_short, st["sl_short"], np.nan))
    df["tp_price"] = np.where(go_long, st["tp_long"], np.where(go_short, st["tp_short"], np.nan))
    df["rr"] = np.where(go_long, st["rr_long"], np.where(go_short, st["rr_short"], np.nan))
    return df


def signal_rows(df: pd.DataFrame) -> dict[int, dict[str, Any]]:
    """Sinyal satırları: {mum açılış UTC ms: {side, score, sl, tp, rr}} (sıralama ve emir için)."""
    mask = (df["enter_long"] == 1) | (df["enter_short"] == 1)
    out: dict[int, dict[str, Any]] = {}
    for row in df.loc[mask, ["date", "enter_long", "score", "sl_price", "tp_price", "rr"]].itertuples(index=False):
        out[int(pd.Timestamp(row.date).timestamp() * 1000)] = {
            "side": "long" if row.enter_long == 1 else "short",
            "score": float(row.score),
            "sl": float(row.sl_price),
            "tp": float(row.tp_price),
            "rr": float(row.rr),
        }
    return out


# --------------------------------------------------------------------------- işlem planı / çıkış


def plan_from_fill(open_rate: float, sl: float | None, is_short: bool, target_rr: float,
                   fallback_stop_pct: float) -> dict[str, Any]:
    """Gerçek giriş fiyatına göre plan: stop FİYATI korunur, hedef gerçek riske göre yeniden
    hesaplanır (R/R gerçek dolumda da target_rr). Dolum stopu zaten geçtiyse crossed=True."""
    if sl is None or not np.isfinite(sl) or sl <= 0:
        sl = open_rate * (1 + fallback_stop_pct) if is_short else open_rate * (1 - fallback_stop_pct)
        source = "fallback"
    else:
        source = "signal"
    risk = (sl - open_rate) if is_short else (open_rate - sl)
    crossed = risk <= 0
    tp = open_rate - target_rr * risk if is_short else open_rate + target_rr * risk
    return {"sl": float(sl), "tp": float(tp), "risk_pct": float(risk / open_rate), "rr": float(target_rr),
            "crossed": bool(crossed), "source": source}


def exit_reason(*, is_short: bool, rate: float, tp: float | None, crossed: bool, held_minutes: float,
                max_hold_minutes: float) -> str | None:
    """custom_exit kararı: dolum stopu geçtiyse hemen çık; hedef geçildiyse kâr al; süre dolduysa çık."""
    if crossed:
        return "fill_beyond_stop"
    if tp is not None and ((not is_short and rate >= tp) or (is_short and rate <= tp)):
        return "take_profit"
    if max_hold_minutes > 0 and held_minutes >= max_hold_minutes:
        return "time_stop"
    return None


def risk_stake(*, equity: float, risk_per_trade: float, rate: float, sl: float | None, leverage: float,
               min_stake: float | None, max_stake: float, proposed_stake: float | None = None,
               cap_to_slot: bool = True) -> float:
    """Risk tabanlı teminat (USDT). 0 = işlem açma.

    Kayıp ≈ teminat x kaldıraç x stop mesafesi = özsermaye x risk_per_trade.
    """
    if sl is None or not np.isfinite(sl) or rate <= 0 or leverage <= 0 or equity <= 0:
        return 0.0
    dist = abs(rate - sl) / rate
    if dist <= 0:
        return 0.0
    stake = equity * risk_per_trade / (dist * leverage)
    upper = max_stake
    if cap_to_slot and proposed_stake:
        upper = min(upper, proposed_stake)
    if min_stake is not None and min_stake > upper:
        return 0.0
    stake = min(stake, upper)
    if min_stake is not None:
        stake = max(stake, min_stake)
    return float(stake)


def depth_ok(orderbook: dict, side: str, band_pct: float, min_depth_usdt: float) -> tuple[bool, float]:
    """Alınan tarafta orta fiyat +/- band_pct içindeki USDT derinliği yeterli mi?
    long -> asks (alıyoruz), short -> bids (satıyoruz). Miktarlar baz birim (WEEX)."""
    bids, asks = orderbook.get("bids") or [], orderbook.get("asks") or []
    if not bids or not asks:
        return False, 0.0
    mid = (float(bids[0][0]) + float(asks[0][0])) / 2
    if side == "long":
        limit = mid * (1 + band_pct)
        notional = sum(float(px) * float(qty) for px, qty, *_ in asks if float(px) <= limit)
    else:
        limit = mid * (1 - band_pct)
        notional = sum(float(px) * float(qty) for px, qty, *_ in bids if float(px) >= limit)
    return notional >= min_depth_usdt, notional
