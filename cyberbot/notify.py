"""Telegram bildirimleri (Bot HTTP API).

Freqtrade kendi Telegram bağlantısını kullanır (strateji mesajları dp.send_msg ile).
Bu modül Freqtrade dışındaki süreçler içindir: kaydedici (recorder) ve izleme
(bot çalışmıyor / WEEX'e ulaşılamıyor uyarıları). Mesajlar düz metin gider
(parse_mode yok), böylece alt çizgi gibi karakterler mesajı bozmaz.
Token hiçbir log satırına yazılmaz.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
_MARKDOWN_SPECIALS = ("\\", "_", "*", "`", "[")


def md_escape(text: str) -> str:
    """Freqtrade'in Telegram'a gönderdiği (eski Markdown) mesajlar için kaçış.
    Strateji dp.send_msg kullanırken pair adı gibi değerleri bununla sarmalı."""
    for ch in _MARKDOWN_SPECIALS:
        text = text.replace(ch, "\\" + ch)
    return text


class TelegramNotifier:
    def __init__(self, token: str | None, chat_id: str | None, *, session: Any = None, timeout: float = 10.0):
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.timeout = timeout
        self._session = session
        self._last_sent: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _redact(self, text: object) -> str:
        text = str(text)
        return text.replace(self.token, "***") if self.token else text

    def _http(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def send(self, text: str, *, dedup_key: str | None = None, dedup_window_s: float = 1800) -> bool:
        """Mesaj gönderir. Aynı dedup_key ile dedup_window_s içinde ikinci kez göndermez.
        Hata olursa loga yazar ve False döner (çağıranı asla düşürmez)."""
        if not self.enabled:
            logger.info("Telegram kapalı, mesaj gönderilmedi: %s", text[:200])
            return False
        now = time.monotonic()
        if dedup_key is not None:
            last = self._last_sent.get(dedup_key)
            if last is not None and now - last < dedup_window_s:
                return False
        try:
            response = self._http().post(
                f"{TELEGRAM_API}/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True},
                timeout=self.timeout,
            )
            ok = response.status_code == 200 and response.json().get("ok") is True
        except Exception as exc:
            logger.warning("Telegram mesajı gönderilemedi: %s", self._redact(exc))
            return False
        if not ok:
            logger.warning("Telegram mesajı reddedildi: HTTP %s %s", response.status_code,
                           self._redact(getattr(response, "text", ""))[:200])
            return False
        if dedup_key is not None:
            self._last_sent[dedup_key] = now
        return True
