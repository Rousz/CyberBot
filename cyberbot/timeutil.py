"""Zaman yardımcıları.

Kural: her şey UTC tutulur. Raporlarda İstanbul saati de yazılır.
VM ABD saatinde, PC İstanbul saatinde olduğu için yerel saat hiç kullanılmaz.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    ISTANBUL = ZoneInfo("Europe/Istanbul")
except Exception:  # saat dilimi veritabanı yoksa: Türkiye 2016'dan beri sabit UTC+3
    ISTANBUL = timezone(timedelta(hours=3), "TRT")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def from_ms(ms: int | float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_istanbul(dt: datetime) -> str:
    return dt.astimezone(ISTANBUL).strftime("%Y-%m-%d %H:%M:%S")


def fmt_both(dt: datetime) -> str:
    """'2026-10-17 18:30:05 UTC (İstanbul 21:30:05)'; gün farklıysa İstanbul tarihi de yazılır."""
    utc = dt.astimezone(timezone.utc)
    ist = dt.astimezone(ISTANBUL)
    ist_txt = ist.strftime("%H:%M:%S") if ist.date() == utc.date() else ist.strftime("%Y-%m-%d %H:%M:%S")
    return f"{fmt_utc(utc)} (İstanbul {ist_txt})"


def file_stamp(dt: datetime) -> str:
    """Dosya adları için: 20261017_183005Z"""
    return dt.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
