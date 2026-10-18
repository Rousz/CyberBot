"""Kaydedici (recorder) ve izleme (monitor) varsayılan ayarları.

Config'de "cyberbot": {"recorder": {...}, "monitor": {...}} ile değiştirilir
(cyberbot.settings.section). Süreler saniye (_s), milisaniye (_ms) veya dakika (_minutes).
"""

from __future__ import annotations

# Sabit fiyatlı (stablecoin) tabanlar: hacim sıralamasına girmez.
STABLECOIN_REGEX = (
    r"^(USDT|USDC|BUSD|DAI|TUSD|FDUSD|USDP|USDD|PYUSD|USDE|USDS|USD0|USD1|USDX|RLUSD|GUSD|LUSD|FRAX|SUSD"
    r"|EURC|EURT|EURI|AEUR|EUR|GBP|TRY)$"
)
# Kaldıraçlı tokenler (BTCUP, ETHDOWN, BTC3L, ETH5S...). "JUP", "SYRUP" gibi gerçek
# coinleri yakalamamak için UP/DOWN sadece bilinen büyük coinlerin arkasında aranır.
LEVERAGED_REGEXES = [
    r"^(BTC|ETH|BNB|XRP|ADA|DOT|LINK|LTC|EOS|TRX|XTZ|SXP|FIL|YFI|SUSHI|AAVE|UNI|1INCH|BCH|XLM|SOL|DOGE)"
    r"(UP|DOWN|BULL|BEAR)$",
    r"^[A-Z]{2,10}[2-9][LS]$",
]

RECORDER_DEFAULTS: dict = {
    "http_timeout_s": 15,
    "tick_s": 1.0,
    "fetch_log_days": 7,
    "log_max_mb": 10,
    "log_backups": 5,
    # Arka plan işi (WS, doldurma) hata verip biterse yeniden başlatılır: 5, 10, 20 ... en fazla 300 sn
    # bekleyerek. task_stable_s kadar hatasız çalışınca sağlıklı sayılır.
    "task_restart_base_s": 5,
    "task_restart_max_s": 300,
    "task_stable_s": 120,
    "symbols": {
        "track_top_n": 60,
        "keep_hours": 48,            # listeden düşen sembol 48 saat daha izlenir (histerezis)
        "refresh_s": 3600,           # WEEX ticker/24hr pahalı: saatte en fazla bir kez
        "retry_s": 300,              # yenileme başarısızsa tekrar
        "always_track": ["BTCUSDT", "ETHUSDT"],
        "exclude_regexes": [STABLECOIN_REGEX, *LEVERAGED_REGEXES],  # WEEX baseAsset üzerinde
        "price_tolerance": 0.015,    # Binance/WEEX fiyat oranı beklenen çarpandan en fazla %1.5 sapabilir
        # Elle eşleme: {"WEEXSYMBOL": {"binance_symbol": "1000XUSDT", "multiplier": 1000}}
        # veya {"WEEXSYMBOL": null} (Binance'te yok say).
        "overrides": {},
    },
    "binance": {
        "enabled": True,
        "rest_url": "https://fapi.binance.com",
        "ws_url": "wss://fstream.binance.com/market/ws",
        "period": "5m",
        "poll_offset_s": 30,         # mum sınırı + 30 sn
        "retry_offset_s": 90,        # eksik kalan semboller için + 90 sn
        "limit": 500,
        "max_rps": 2.0,
        "window_s": 300,
        "window_max": 700,           # /futures/data sınırı 1000/5dk/IP; %70'i
        "safety_ms": 60_000,         # avail_ms = ts + period + safety
        "backfill": True,
        "backfill_days": 29.5,
        "backfill_attempts": 3,
        "ban_pause_s": 600,          # 418'de Retry-After yoksa en az bu kadar dur
        "rate_limit_pause_s": 60,    # 429'da Retry-After yoksa
        "ws_rotate_s": 23 * 3600,    # sunucu 24 saatte keser; 23 saatte örtüşmeli yenile
        "ws_overlap_s": 10,
        "ws_backoff_max_s": 60,
        "ws_open_timeout_s": 15,
        "ws_gap_min_s": 5,           # bundan kısa kopukluk boşluk sayılmaz
    "ws_ack_timeout_s": 10,      # SUBSCRIBE onayı bu sürede gelmezse bağlantı başarısız
    "ws_silence_s": 600,         # bu kadar hiç forceOrder gelmezse yeniden bağlan (0 = kapalı)
    },
    "weex": {
        "enabled": True,
        "rest_url": "https://api-contract.weex.com",
        "premium_interval_s": 60,
        "premium_offset_s": 2,       # dakika başı + 2 sn
        "oi_lead_s": 30,             # 5m mum kapanışından 30 sn önce
        "funding_delay_s": 120,      # nextFundingTime + 2 dk
        "funding_limit": 1000,
        "max_rps": 2.5,              # freqtrade aynı IP'yi kullanıyor: yük çok küçük tutulur
        "window_s": 60,
        "window_max": 100,
    },
}

MONITOR_DEFAULTS: dict = {
    "enabled": True,
    "check_interval_s": 30,
    "grace_s": 300,                  # kaydedici açıldıktan sonraki ilk 5 dk uyarı yok
    "alert_after_s": 120,            # WEEX bu kadar ulaşılamazsa uyarı
    "realert_minutes": 180,          # sorun sürerse hatırlatma (0 = kapalı)
    "bot_heartbeat_stale_s": 300,
    "binance_alert_after_s": 600,
    "task_alert_failures": 3,        # bir kaydedici işi üst üste bu kadar hata verirse uyarı (0 = kapalı)
}
