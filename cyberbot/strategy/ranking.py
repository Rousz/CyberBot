"""Aynı mumda birden çok parite sinyal verirse: en yüksek puan önce.

Freqtrade'de sıralama kancası yok; bu yüzden strateji confirm_trade_entry içinde, sinyal
mumundaki (signal_date) tüm adayları puana göre sıralar ve sadece boş slot sayısı kadar
en üsttekini kabul eder. Backtest ve dry-run aynı çalışır (sadece o mumun değerleri okunur).

Binance önceliği: binance_perps.json'daki paritelere sıralamada +bonus puan (eşiği etkilemez).
Dosya yoksa, bozuksa veya 48 saatten eskiyse bonus uygulanmaz.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


def rank(candidates: dict[str, float], bonus_pairs: frozenset[str] | set[str] = frozenset(),
         bonus: float = 0.0) -> list[str]:
    """Pariteleri (puan + bonus) azalan, eşitlikte parite adına göre sıralar."""
    def key(pair: str) -> tuple[float, str]:
        return (-(candidates[pair] + (bonus if pair in bonus_pairs else 0.0)), pair)

    return sorted(candidates, key=key)


def is_selected(pair: str, candidates: dict[str, float], free_slots: float,
                bonus_pairs: frozenset[str] | set[str] = frozenset(), bonus: float = 0.0) -> bool:
    """pair, boş slot sayısı kadar en üstteki adaylardan biri mi?"""
    if free_slots <= 0:
        return False
    if pair not in candidates:
        return True  # sıralama bilgisi yok: engelleme (Freqtrade'in kendi kararı geçerli)
    ordered = rank(candidates, bonus_pairs, bonus)
    return ordered.index(pair) < free_slots


class BinancePerps:
    """binance_perps.json önbelleği: en fazla refresh_s'de bir okunur; yaş her çağrıda denetlenir."""

    def __init__(self, path_fn: Callable[[], Path], *, refresh_s: float = 3600, max_age_hours: float = 48,
                 clock_ms: Callable[[], int] | None = None):
        self.path_fn = path_fn
        self.refresh_ms = int(refresh_s * 1000)
        self.max_age_ms = int(max_age_hours * 3_600_000)
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._loaded_ms: int | None = None
        self._generated_ms: int | None = None
        self._pairs: frozenset[str] = frozenset()

    def _load(self) -> None:
        path = self.path_fn()
        self._generated_ms, self._pairs = None, frozenset()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self._generated_ms = int(data["generated_ms"])
            self._pairs = frozenset(str(k) for k in (data.get("pairs") or {}))
        except FileNotFoundError:
            logger.info("binance_perps.json yok; Binance öncelik bonusu uygulanmıyor.")
        except Exception as exc:  # bozuk dosya: bonus yok, bot devam eder
            logger.warning("binance_perps.json okunamadı (%s); Binance öncelik bonusu uygulanmıyor.", exc)

    def pairs(self) -> frozenset[str]:
        now = self.clock_ms()
        if self._loaded_ms is None or now - self._loaded_ms >= self.refresh_ms:
            self._load()
            self._loaded_ms = now
        if self._generated_ms is None or now - self._generated_ms > self.max_age_ms:
            return frozenset()
        return self._pairs
