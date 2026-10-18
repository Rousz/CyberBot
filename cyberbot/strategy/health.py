"""Borsa sağlık durum makinesi (saf; Freqtrade'siz, testte saat verilir).

Kural: WEEX'e ulaşılamıyorsa yeni işlem açılmaz + Telegram uyarısı.
Ölçüt: BTC/USDT:USDT 5m mumlarının tazeliği. Her döngüde (bot_loop_start, ~5 sn)
son kapanmış mumun açılış zamanı verilir:
    beklenen >= floor(şimdi - max_candle_delay_s, tf) - tf
    (yani bir mum, Freqtrade'in 15 sn bekleme payı + gecikme toleransı kadar kaçırıldıysa bayat)

Durumlar: healthy -> (bayat) -> down [tek uyarı, global kilit] -> recovery_loops ardışık
taze döngü -> healthy [tek düzeldi mesajı, kilit kaldırılır]. Kurtarma sırasında tek bir bayat
döngü sayacı sıfırlar (dalgalanma yok). Kilit süresi lock_minutes; kilit bitimine yarısından az
kaldığında yenilenir (her döngüde yeni kilit satırı yazılmasın).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Decision:
    healthy: bool
    transition: str | None = None  # "down" | "recovered" | None
    lock_until_ms: int | None = None  # dolu ise: bu zamana kadar global kilit koy/yenile
    stale_s: float | None = None  # son mumun beklenene göre gecikmesi (sn), bilgi için


class ExchangeHealth:
    def __init__(self, *, timeframe_s: int = 300, max_candle_delay_s: float = 45, lock_minutes: float = 10,
                 recovery_loops: int = 3):
        self.tf_ms = int(timeframe_s * 1000)
        self.delay_ms = int(max_candle_delay_s * 1000)
        self.lock_ms = int(lock_minutes * 60_000)
        self.recovery_loops = max(1, int(recovery_loops))
        self.healthy = True
        self.down_since_ms: int | None = None
        self.lock_until_ms: int | None = None
        self._good_streak = 0

    def expected_open_ms(self, now_ms: int) -> int:
        """Şu an en azından elde olması gereken son kapanmış mumun açılış zamanı."""
        return (now_ms - self.delay_ms) // self.tf_ms * self.tf_ms - self.tf_ms

    def is_fresh(self, last_open_ms: int | None, now_ms: int) -> bool:
        return last_open_ms is not None and last_open_ms >= self.expected_open_ms(now_ms)

    def update(self, last_open_ms: int | None, now_ms: int) -> Decision:
        fresh = self.is_fresh(last_open_ms, now_ms)
        stale_s = None
        if last_open_ms is not None:
            stale_s = max(0.0, (self.expected_open_ms(now_ms) - last_open_ms) / 1000)
        if self.healthy:
            if fresh:
                return Decision(True, stale_s=stale_s)
            self.healthy = False
            self.down_since_ms = now_ms
            self._good_streak = 0
            self.lock_until_ms = now_ms + self.lock_ms
            return Decision(False, "down", self.lock_until_ms, stale_s)
        # down durumu
        if fresh:
            self._good_streak += 1
            if self._good_streak >= self.recovery_loops:
                self.healthy = True
                self.down_since_ms = None
                self.lock_until_ms = None
                self._good_streak = 0
                return Decision(True, "recovered", None, stale_s)
        else:
            self._good_streak = 0
        lock = None
        if self.lock_until_ms is None or self.lock_until_ms - now_ms < self.lock_ms / 2:
            self.lock_until_ms = now_ms + self.lock_ms
            lock = self.lock_until_ms
        return Decision(False, None, lock, stale_s)
