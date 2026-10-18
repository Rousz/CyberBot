"""İzleme: WEEX erişimi, freqtrade canlılığı, Binance erişimi -> Telegram + uptime olayları.

Kaydedici sürecinde çalışır (docker-compose "recorder" servisi).
(a) WEEX: kaydedicinin WEEX istek sonuçlarından (premiumIndex her 60 sn). alert_after_s
    (120 sn) boyunca hiç başarılı istek yoksa tek uyarı + 'weex_unreachable'; düzelince
    mesaj + 'weex_recovered'. Sorun sürerse realert_minutes'ta bir hatırlatma.
(b) Freqtrade: uptime.sqlite'taki 'freqtrade' bileşeninin son kalp atışı
    bot_heartbeat_stale_s'den (300 sn) eskiyse 'Bot çalışmıyor' + 'bot_stale'; geri gelince 'bot_recovered'.
(c) Binance: REST veya likidasyon WS'i binance_alert_after_s boyunca yoksa ya da 418 IP
    yasağı varsa uyarı + 'binance_unreachable'; düzelince 'binance_recovered'.
Kaydedici açıldıktan sonraki grace_s içinde uyarı gönderilmez. İzleme asla istisna fırlatmaz.
Mesajlarda UTC + İstanbul saati yazar.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from cyberbot.timeutil import fmt_both, from_ms

logger = logging.getLogger(__name__)

HEARTBEAT_WRITE_MS = 10_000


def fmt_ms(ms: int | None) -> str:
    return fmt_both(from_ms(ms)) if ms else "bilinmiyor"


def fmt_duration(ms: int) -> str:
    """'7 dakika', '2 saat 5 dakika' (sonuna 'dır' eklenince Türkçe doğru okunur)."""
    minutes = max(0, int(ms // 60_000))
    if minutes < 60:
        return f"{minutes} dakika"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} saat {minutes} dakika"


class SourceHealth:
    """Bir kaynağın (weex, binance_rest...) son başarı/hata durumu. heartbeat tablosuna da
    yazar (başarılar en fazla 10 sn'de bir, hatalar her seferinde)."""

    def __init__(self, name: str, db: Any = None):
        self.name = name
        self.db = db
        self.last_ok_ms: int | None = None
        self.last_err_ms: int | None = None
        self.last_err = ""
        self.consecutive_fail = 0
        self.attempted = False
        self._last_db_ok = 0

    def ok(self, now_ms: int) -> None:
        self.attempted = True
        recovered = self.consecutive_fail > 0
        self.last_ok_ms = now_ms
        self.consecutive_fail = 0
        if self.db is not None and (recovered or now_ms - self._last_db_ok >= HEARTBEAT_WRITE_MS):
            self._last_db_ok = now_ms
            try:
                self.db.heartbeat_ok(self.name, now_ms)
            except Exception as exc:
                logger.warning("heartbeat yazılamadı (%s): %s", self.name, exc)

    def fail(self, now_ms: int, err: str) -> None:
        self.attempted = True
        self.last_err_ms = now_ms
        self.last_err = err
        self.consecutive_fail += 1
        if self.consecutive_fail in (1, 3) or self.consecutive_fail % 20 == 0:
            logger.warning("%s hatası (%d. kez üst üste): %s", self.name, self.consecutive_fail, err)
        if self.db is not None:
            try:
                self.db.heartbeat_err(self.name, now_ms, err)
            except Exception as exc:
                logger.warning("heartbeat yazılamadı (%s): %s", self.name, exc)

    def down_for_ms(self, now_ms: int, since_ms: int) -> int:
        """Son başarıdan (hiç yoksa since_ms'den) beri geçen süre; son istek başarılıysa 0."""
        if not self.attempted or self.consecutive_fail == 0:
            return 0
        return now_ms - (self.last_ok_ms or since_ms)


@dataclass
class Status:
    """Kaydedicinin kaynak durumları (izleme okur)."""
    weex: SourceHealth = field(default_factory=lambda: SourceHealth("weex"))
    binance_rest: SourceHealth = field(default_factory=lambda: SourceHealth("binance_rest"))
    binance_ban_until_ms: int = 0
    ws_enabled: bool = False
    ws_down_since_ms: int | None = None  # None = bağlı (veya hiç denenmedi)

    def attach_db(self, db: Any) -> None:
        self.weex.db = db
        self.binance_rest.db = db


class Condition:
    """Tek bir uyarı durumu: kötüleşince bir kez uyarı, sürerse hatırlatma, düzelince mesaj."""

    def __init__(self, name: str, down_event: str, up_event: str):
        self.name = name
        self.down_event = down_event
        self.up_event = up_event
        self.active = False
        self.since_ms: int | None = None
        self.last_alert_ms: int | None = None


class Monitor:
    def __init__(self, cfg: dict, *, status: Status, notifier: Any, events: Any, bot_store: Any,
                 started_ms: int, binance_enabled: bool = True, weex_enabled: bool = True,
                 send: Callable[[str], Any] | None = None):
        """events: UptimeStore('recorder') (add_event). bot_store: UptimeStore('freqtrade') (sessions okunur).
        send: test/özel gönderici; verilmezse notifier.send iş parçacığında çağrılır."""
        self.cfg = cfg
        self.status = status
        self.notifier = notifier
        self.events = events
        self.bot_store = bot_store
        self.started_ms = started_ms
        self.binance_enabled = binance_enabled
        self.weex_enabled = weex_enabled
        self._send = send
        self.weex = Condition("weex", "weex_unreachable", "weex_recovered")
        self.bot = Condition("bot", "bot_stale", "bot_recovered")
        self.binance = Condition("binance", "binance_unreachable", "binance_recovered")
        self.sent: list[str] = []

    # --- yardımcılar --------------------------------------------------------

    async def _notify(self, text: str) -> None:
        self.sent.append(text)
        try:
            if self._send is not None:
                result = self._send(text)
                if asyncio.iscoroutine(result):
                    await result
            elif self.notifier is not None:
                await asyncio.to_thread(self.notifier.send, text)
        except Exception as exc:
            logger.warning("izleme mesajı gönderilemedi: %s", type(exc).__name__)

    def _event(self, kind: str, detail: str, now_ms: int) -> None:
        try:
            self.events.add_event(kind, detail, at_ms=now_ms)
        except Exception as exc:
            logger.warning("uptime olayı yazılamadı (%s): %s", kind, exc)

    async def _update(self, cond: Condition, bad: bool, now_ms: int, since_ms: int | None, detail: str,
                      down_text: Callable[[], str], up_text: Callable[[int], str],
                      remind_text: Callable[[], str]) -> None:
        realert_ms = int(float(self.cfg.get("realert_minutes") or 0) * 60_000)
        if bad and not cond.active:
            cond.active, cond.since_ms, cond.last_alert_ms = True, since_ms or now_ms, now_ms
            logger.warning("İZLEME: %s sorunu: %s", cond.name, detail)
            self._event(cond.down_event, detail, now_ms)
            await self._notify(down_text())
        elif bad and cond.active and realert_ms and now_ms - (cond.last_alert_ms or now_ms) >= realert_ms:
            cond.last_alert_ms = now_ms
            await self._notify(remind_text())
        elif not bad and cond.active:
            since = cond.since_ms or now_ms
            cond.active, cond.since_ms = False, None
            logger.info("İZLEME: %s düzeldi", cond.name)
            self._event(cond.up_event, f"kesinti {fmt_duration(now_ms - since)}", now_ms)
            await self._notify(up_text(since))

    # --- kontroller ---------------------------------------------------------

    async def check(self, now_ms: int) -> None:
        """Periyodik kontrol. Asla istisna fırlatmaz."""
        if not self.cfg.get("enabled", True):
            return
        if now_ms - self.started_ms < float(self.cfg["grace_s"]) * 1000:
            return
        for fn in (self._check_weex, self._check_bot, self._check_binance):
            try:
                await fn(now_ms)
            except Exception:
                logger.exception("izleme kontrolü hatası (%s)", fn.__name__)

    async def _check_weex(self, now_ms: int) -> None:
        if not self.weex_enabled:
            return
        h = self.status.weex
        down = h.down_for_ms(now_ms, self.started_ms)
        bad = down > float(self.cfg["alert_after_s"]) * 1000
        last_ok = h.last_ok_ms
        await self._update(
            self.weex, bad, now_ms, now_ms - down, h.last_err,
            lambda: (f"UYARI: WEEX'e ulaşılamıyor ({fmt_duration(down)}dır). Bağlantı gelene kadar bot yeni işlem "
                     f"açmayacak. Son başarılı istek: {fmt_ms(last_ok)}. Şu an: {fmt_ms(now_ms)}. "
                     f"İnternet bağlantısını ve PC'yi kontrol edin."),
            lambda since: (f"DÜZELDİ: WEEX'e yeniden ulaşılıyor. Kesinti: {fmt_duration(now_ms - since)} "
                           f"({fmt_ms(since)} - {fmt_ms(now_ms)})."),
            lambda: f"HATIRLATMA: WEEX'e hâlâ ulaşılamıyor ({fmt_duration(down)}dır). Şu an: {fmt_ms(now_ms)}.",
        )

    async def _check_bot(self, now_ms: int) -> None:
        sessions = self.bot_store.sessions("freqtrade")
        stale_ms = float(self.cfg["bot_heartbeat_stale_s"]) * 1000
        last = sessions[-1] if sessions else None
        last_hb = max((s.last_heartbeat_ms for s in sessions), default=None)
        running = last is not None and last.stopped_ms is None and last_hb is not None and now_ms - last_hb <= stale_ms
        if last is None:
            reason = "freqtrade hiç kalp atışı yazmadı"
        elif last.stopped_ms is not None:
            reason = f"freqtrade kapatıldı ({fmt_ms(last.stopped_ms)})"
        else:
            reason = f"freqtrade {fmt_duration(now_ms - (last_hb or now_ms))}dır kalp atışı yazmıyor"
        await self._update(
            self.bot, not running, now_ms, last_hb, reason,
            lambda: (f"UYARI: Bot çalışmıyor: {reason}. Son kalp atışı: {fmt_ms(last_hb)}. Şu an: {fmt_ms(now_ms)}. "
                     f"PC'de Docker Desktop'ı ve 'freqtrade' container'ını kontrol edin."),
            lambda since: f"DÜZELDİ: Bot yeniden çalışıyor. Şu an: {fmt_ms(now_ms)}.",
            lambda: f"HATIRLATMA: Bot hâlâ çalışmıyor ({reason}). Şu an: {fmt_ms(now_ms)}.",
        )

    async def _check_binance(self, now_ms: int) -> None:
        if not self.binance_enabled:
            return
        limit = float(self.cfg["binance_alert_after_s"]) * 1000
        reasons = []
        if self.status.binance_ban_until_ms > now_ms:
            reasons.append(f"HTTP 418 IP yasağı, Binance istekleri {fmt_ms(self.status.binance_ban_until_ms)} "
                           f"saatine kadar durduruldu")
        rest_down = self.status.binance_rest.down_for_ms(now_ms, self.started_ms)
        if rest_down > limit:
            reasons.append(f"REST {fmt_duration(rest_down)}dır cevap vermiyor ({self.status.binance_rest.last_err})")
        ws_since = self.status.ws_down_since_ms
        if self.status.ws_enabled and ws_since is not None and now_ms - ws_since > limit:
            reasons.append(f"likidasyon akışı {fmt_duration(now_ms - ws_since)}dır kopuk")
        text = "; ".join(reasons)
        await self._update(
            self.binance, bool(reasons), now_ms, now_ms, text,
            lambda: (f"UYARI: Binance verisi alınamıyor: {text}. Şu an: {fmt_ms(now_ms)}. Bot çalışmaya devam eder; "
                     f"29.5 günden kısa REST boşlukları sonra otomatik doldurulur, likidasyon boşlukları doldurulamaz."),
            lambda since: (f"DÜZELDİ: Binance verisi yeniden alınıyor. Kesinti: {fmt_duration(now_ms - since)} "
                           f"({fmt_ms(since)} - {fmt_ms(now_ms)})."),
            lambda: f"HATIRLATMA: Binance verisi hâlâ alınamıyor: {text}. Şu an: {fmt_ms(now_ms)}.",
        )
