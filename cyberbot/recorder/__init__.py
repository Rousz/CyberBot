"""Türev verisi kaydedici + izleme (docker-compose "recorder" servisi: python -m cyberbot.recorder).

Faz 1: sadece veri toplar (puanlama yok). Yazdığı yerler:
- /data/derivs.sqlite      (cyberbot.recorder.db; tek yazar)
- /data/binance_perps.json (WEEX paritesi -> Binance vadeli karşılığı)
- /data/uptime.sqlite      (bileşen 'recorder' oturumu + izleme olayları)
Modüller: defaults (ayarlar), limiter (saat/HTTP/hız sınırı), db, symbols, binance_rest,
binance_ws, weex_poll, monitor, service.
"""
