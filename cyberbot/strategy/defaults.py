"""Strateji varsayılanları: config.json "cyberbot": {"strategy": {...}} bunların üzerine yazılır.

Oranlar ondalık: 0.01 = %1. Fiyat mesafeleri fiyatın oranıdır (kaldıraçsız).
"""

from __future__ import annotations

from typing import Any

from cyberbot import settings

STRATEGY_DEFAULTS: dict[str, Any] = {
    # Puan katmanları. Toplam puan = açık katmanların ağırlıklı ortalaması (0-100),
    # böylece katman açıp kapatmak eşiği değiştirmeyi gerektirmez.
    # Faz 1'de sadece "trend" var; diğerleri yer tutucu (açılırsa uyarı yazılır, yok sayılır).
    "layers": {"trend": True, "indicators": False, "patterns": False, "derivatives": False, "news": False},
    "weights": {"trend": 1.0, "indicators": 1.0, "patterns": 1.0, "derivatives": 1.0, "news": 1.0},
    "entry_score_threshold": 70,
    # Zorunlu: planlanan ödül/risk >= min_rr. Hedef = giriş +/- target_rr x risk.
    "min_rr": 1.5,
    "target_rr": 1.8,
    "leverage": 3,
    # Risk tabanlı pozisyon: teminat = özsermaye x risk_per_trade / (stop mesafesi x kaldıraç)
    "risk_per_trade": 0.01,
    # True: teminat, Freqtrade'in slot başına önerdiği payı (bakiye / max_open_trades) aşmaz.
    "cap_stake_to_slot": True,
    "max_hold_minutes": 180,
    "trend": {
        "ema_fast": 20,
        "ema_mid": 50,
        "ema_slow": 200,
        "adx_period": 14,
        "adx_trend": 20,  # ADX >= bu: trend rejimi; altı: yatay (Faz 1'de yatayda işlem yok)
        "adx_strong": 40,  # puan için: ADX bu değerde tam puan
        "inf_ema_mid": 50,  # 1h EMA'lar (parite ve BTC)
        "inf_ema_slow": 200,
    },
    "trigger": {
        "pullback_lookback": 3,  # son N mumda fiyat EMA20'ye değmiş olmalı
        "vol_sma": 20,
        "vol_mult": 1.0,  # hacim >= vol_mult x SMA20(hacim)
    },
    "stop": {
        "swing_lookback": 6,  # stop = son N mumun en düşüğü - atr_buffer x ATR (short: tersi)
        "atr_period": 14,
        "atr_buffer": 0.25,
        # WEEX taker ücreti işlem başına %0.08 (gidiş-dönüş %0.16): %0.4'ten dar stopta
        # ücret riskin %40'ını aşar; %3'ten geniş stop scalp değildir.
        "min_stop_pct": 0.004,
        "max_stop_pct": 0.03,
    },
    "ranking": {
        "binance_priority_bonus": 5.0,  # Binance'te de olan paritelere sıralamada +puan (eşiğe etkisi yok)
        "binance_max_age_hours": 48,
        "binance_refresh_s": 3600,
    },
    "depth": {
        # Sadece dry-run/canlı: girişte alınan taraftaki derinlik (orta fiyat +/- band_pct)
        "enabled": True,
        "levels": 20,
        "band_pct": 0.005,
        "min_depth_usdt": 50000,
    },
    "health": {
        # Sadece dry-run/canlı: BTC 5m mumu gecikirse yeni işlem kilidi + tek Telegram uyarısı
        "enabled": True,
        "max_candle_delay_s": 45,
        "lock_minutes": 10,
        "recovery_loops": 3,
    },
}


def load(config: dict | None) -> dict[str, Any]:
    """Freqtrade config'inden (dict) strateji ayarları; eksik anahtarlar varsayılandan."""
    return settings.section("strategy", STRATEGY_DEFAULTS, config or {})


def validate(p: dict[str, Any]) -> list[str]:
    """Ayar hatalarını Türkçe liste olarak döner (boş = sorun yok)."""
    errors = []
    if float(p["target_rr"]) < float(p["min_rr"]):
        errors.append(f"target_rr ({p['target_rr']}) min_rr'den ({p['min_rr']}) küçük olamaz")
    if float(p["min_rr"]) <= 0:
        errors.append("min_rr sıfırdan büyük olmalı")
    s = p["stop"]
    if not 0 < float(s["min_stop_pct"]) < float(s["max_stop_pct"]):
        errors.append("stop: 0 < min_stop_pct < max_stop_pct olmalı")
    if float(p["leverage"]) < 1:
        errors.append("leverage en az 1 olmalı")
    if not 0 < float(p["risk_per_trade"]) <= 0.05:
        errors.append("risk_per_trade 0 ile 0.05 (%5) arasında olmalı")
    t = p["trend"]
    if not float(t["adx_strong"]) > float(t["adx_trend"]):
        errors.append("trend: adx_strong adx_trend'den büyük olmalı")
    if not int(t["ema_fast"]) < int(t["ema_mid"]) < int(t["ema_slow"]):
        errors.append("trend: ema_fast < ema_mid < ema_slow olmalı")
    if int(p["trigger"]["pullback_lookback"]) < 1 or int(s["swing_lookback"]) < 1:
        errors.append("pullback_lookback ve swing_lookback en az 1 olmalı")
    if int(p["health"]["recovery_loops"]) < 1:
        errors.append("health.recovery_loops en az 1 olmalı")
    return errors
