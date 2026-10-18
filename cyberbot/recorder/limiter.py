"""Zaman kaynağı, HTTP arayüzü ve istek hızı sınırlayıcı.

Tüm ağ ve zaman erişimi küçük arayüzlerin arkasındadır; testler sahte saat ve
sahte HTTP istemcisi verir (internet yok).

REST için aiohttp kullanılır (Freqtrade imajında hazır, asyncio ile doğal).
Tek bir yöntem: her kaynak (Binance, WEEX) kendi RateLimiter'ını kullanır.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

USER_AGENT = "CyberBot-recorder/0.1"


# --------------------------------------------------------------------------
# Saat
# --------------------------------------------------------------------------


class Clock(Protocol):
    def now_ms(self) -> int: ...

    async def sleep(self, seconds: float) -> None: ...


class RealClock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


@dataclass
class HttpResponse:
    status: int
    data: Any                      # JSON çözülebildiyse nesne, değilse metin
    headers: dict[str, str] = field(default_factory=dict)  # anahtarlar küçük harf
    ms: float = 0.0


class HttpClient(Protocol):
    async def get(self, url: str, params: dict | None = None) -> HttpResponse: ...

    async def close(self) -> None: ...


class AiohttpClient:
    """Gerçek ağ: aiohttp. Ağ hatasında istisna fırlatır (çağıran kaynak bazında yakalar)."""

    def __init__(self, timeout_s: float = 15.0, user_agent: str = USER_AGENT):
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        self._session = None

    async def _http(self):
        if self._session is None or self._session.closed:
            import aiohttp

            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_s),
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
        return self._session

    async def get(self, url: str, params: dict | None = None) -> HttpResponse:
        session = await self._http()
        t0 = time.perf_counter()
        clean = {k: str(v) for k, v in (params or {}).items() if v is not None}
        async with session.get(url, params=clean) as resp:
            text = await resp.text()
            ms = (time.perf_counter() - t0) * 1000
            try:
                data = json.loads(text)
            except ValueError:
                data = text
            return HttpResponse(resp.status, data, {k.lower(): v for k, v in resp.headers.items()}, ms)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()


def retry_after_s(headers: dict[str, str], default: float) -> float:
    """Retry-After başlığı (saniye). Yoksa veya okunamazsa default."""
    try:
        value = float(headers.get("retry-after", ""))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# --------------------------------------------------------------------------
# Hız sınırlayıcı
# --------------------------------------------------------------------------


class RateLimiter:
    """İki kural: art arda iki istek arası en az 1/max_rps saniye ve kayan
    window_s penceresinde en fazla window_max istek. pause() tüm istekleri
    belirtilen süre durdurur (429 Retry-After, 418 IP yasağı).

    Öncelik: düşük öncelikli istekler (geçmiş doldurma) yüksek öncelikli bir istek
    beklerken ya da high_section() açıkken bekler. Pencerede en fazla low_cap düşük
    öncelikli istek olabilir (sadece düşük öncelikli istekler sayılır; canlı istekler
    window_max'a sayılır). low_cap = window_max - canlı tur payı olduğundan canlı sorgu
    her zaman yer bulur, kalan pay da gerçekten doldurmaya kalır."""

    def __init__(self, clock: Clock, *, max_rps: float, window_s: float, window_max: int, name: str = ""):
        self.clock = clock
        self.name = name
        self.min_gap_ms = 1000.0 / max_rps if max_rps > 0 else 0.0
        self.window_ms = int(window_s * 1000)
        self.window_max = max(1, int(window_max))
        self.low_cap = self.window_max
        self.stamps: deque[int] = deque()        # tüm istekler
        self.low_stamps: deque[int] = deque()    # sadece düşük öncelikli istekler
        self.last_ms: int | None = None
        self.paused_until_ms = 0
        self.pause_reason = ""
        self._high_waiting = 0
        self._high_active = 0

    # --- saf hesap (testli) -------------------------------------------------

    def _prune(self, now: int) -> None:
        for stamps in (self.stamps, self.low_stamps):
            while stamps and stamps[0] <= now - self.window_ms:
                stamps.popleft()

    def in_window(self, now: int) -> int:
        self._prune(now)
        return len(self.stamps)

    def delay_ms(self, now: int, low: bool = False) -> float:
        """Şu an istek atılabilirse 0, değilse beklenecek ms."""
        if now < self.paused_until_ms:
            return self.paused_until_ms - now
        self._prune(now)
        wait = 0.0
        if self.last_ms is not None and self.min_gap_ms:
            wait = max(wait, self.last_ms + self.min_gap_ms - now)
        if low:
            cap = min(self.low_cap, self.window_max)
            if cap <= 0:
                return max(wait, 1000.0)  # düşük önceliğe pay kalmadı: sonra tekrar bak
            if len(self.low_stamps) >= cap:
                wait = max(wait, self.low_stamps[len(self.low_stamps) - cap] + self.window_ms - now)
        if len(self.stamps) >= self.window_max:
            wait = max(wait, self.stamps[len(self.stamps) - self.window_max] + self.window_ms - now)
        return wait

    def record(self, now: int, low: bool = False) -> None:
        self.stamps.append(now)
        if low:
            self.low_stamps.append(now)
        self.last_ms = now

    def pause(self, seconds: float, now: int, reason: str = "") -> None:
        until = now + int(seconds * 1000)
        if until > self.paused_until_ms:
            self.paused_until_ms = until
            self.pause_reason = reason
            logger.warning("%s istekleri %.0f sn durduruldu (%s)", self.name or "kaynak", seconds, reason)

    def paused(self, now: int) -> bool:
        return now < self.paused_until_ms

    # --- asyncio ------------------------------------------------------------

    @contextlib.contextmanager
    def high_section(self):
        """Canlı tur boyunca düşük öncelikli istekleri bekletir."""
        self._high_active += 1
        try:
            yield
        finally:
            self._high_active -= 1

    async def acquire(self, low: bool = False) -> None:
        if not low:
            self._high_waiting += 1
        try:
            while True:
                now = self.clock.now_ms()
                wait = self.delay_ms(now, low)
                if low and (self._high_waiting or self._high_active):
                    wait = max(wait, 200.0)
                if wait <= 0:
                    self.record(now, low)
                    return
                await self.clock.sleep(min(wait, 5000.0) / 1000.0)
        finally:
            if not low:
                self._high_waiting -= 1
