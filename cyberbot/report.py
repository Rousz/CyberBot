"""Script raporlama.

Her script aynı düzeni kullanır:
- çalışırken ekrana kontrol satırları basılır,
- sonda net bir "SONUÇ: BAŞARILI / HATA" kutusu çıkar,
- reports/<ad>_<UTC zaman>.txt  -> kısa özet (repoya girer, bana geri getirilir),
- reports/logs/<ad>_<UTC zaman>.log -> ayrıntılı log (repoya GİRMEZ).

Gizli değerler (token, API anahtarı) add_secret() ile kaydedilir; ekranda,
özette ve logda "***" ile maskelenir.
"""

from __future__ import annotations

import logging
import platform
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple

from cyberbot import __version__
from cyberbot.timeutil import file_stamp, fmt_both, utc_now

OK, WARN, FAIL, SKIP, INFO = "OK", "WARN", "FAIL", "SKIP", "INFO"
LABELS = {OK: "OK", WARN: "UYARI", FAIL: "HATA", SKIP: "ATLANDI", INFO: "BİLGİ"}

VERDICT_OK = "BAŞARILI"
VERDICT_WARN = "BAŞARILI (uyarılarla)"
VERDICT_FAIL = "HATA"


class UserFacingError(Exception):
    """Mesajı olduğu gibi kullanıcıya gösterilebilen hata (sınıf adı eklenmez)."""


class Outcome(NamedTuple):
    status: str
    detail: str


@dataclass
class Check:
    group: str
    name: str
    status: str
    detail: str
    ms: float | None = None


def describe_error(exc: BaseException, limit: int = 300) -> str:
    text = str(exc).strip()
    if not isinstance(exc, UserFacingError):
        text = f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class _RedactFilter(logging.Filter):
    def __init__(self, report: Report):
        super().__init__()
        self.report = report

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.report.redact(record.getMessage())
        record.args = ()
        return True


class Report:
    def __init__(self, title: str, slug: str, reports_dir: str | Path = "reports"):
        self.title = title
        self.slug = slug
        self.started = utc_now()
        self.reports_dir = Path(reports_dir)
        self.logs_dir = self.reports_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = file_stamp(self.started)
        self.summary_path = self.reports_dir / f"{slug}_{stamp}.txt"
        self.log_path = self.logs_dir / f"{slug}_{stamp}.log"
        self.checks: list[Check] = []
        self.findings: list[tuple[str, str]] = []
        self.versions: dict[str, str] = {"cyberbot": __version__, "python": platform.python_version()}
        self._secrets: list[str] = []
        self.log = self._make_logger()

    def _make_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"cyberbot.{self.slug}.{id(self)}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s UTC %(levelname)s %(message)s")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        handler.addFilter(_RedactFilter(self))
        logger.addHandler(handler)
        return logger

    def close(self) -> None:
        for handler in list(self.log.handlers):
            handler.close()
            self.log.removeHandler(handler)

    # --- gizli değerler ---------------------------------------------------

    def add_secret(self, value: str | None) -> None:
        if value and len(value.strip()) >= 4:
            self._secrets.append(value.strip())

    def redact(self, text: object) -> str:
        text = str(text)
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    # --- kontroller -------------------------------------------------------

    def add(self, group: str, name: str, status: str, detail: str, ms: float | None = None) -> Check:
        check = Check(group, name, status, self.redact(detail), ms)
        self.checks.append(check)
        line = self._line(check)
        print(line, flush=True)
        self.log.info(line)
        return check

    def run(self, group: str, name: str, fn: Callable[[], str | Outcome], critical: bool = True) -> Check:
        """fn'i çalıştırır. str dönerse OK, Outcome dönerse o durum.
        İstisna olursa: kritikse HATA, değilse UYARI (ayrıntı loga yazılır)."""
        t0 = time.perf_counter()
        try:
            result = fn()
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            self.log.debug("%s/%s istisna:\n%s", group, name, traceback.format_exc())
            return self.add(group, name, FAIL if critical else WARN, describe_error(exc), ms)
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(result, Outcome):
            return self.add(group, name, result.status, result.detail, ms)
        return self.add(group, name, OK, str(result), ms)

    def finding(self, label: str, value: str) -> None:
        self.findings.append((label, self.redact(value)))
        self.log.info("BULGU %s: %s", label, value)

    def screen_only(self, text: str) -> None:
        """Sadece ekrana yazılır; özete ve loga GİRMEZ (ör. Telegram chat id)."""
        print(text, flush=True)

    # --- sonuç ------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(LABELS, 0)
        for check in self.checks:
            counts[check.status] += 1
        return counts

    def counts_text(self) -> str:
        c = self.counts()
        return f"OK {c[OK]}, UYARI {c[WARN]}, HATA {c[FAIL]}, ATLANDI {c[SKIP]}, BİLGİ {c[INFO]}"

    def verdict(self) -> str:
        c = self.counts()
        if c[FAIL]:
            return VERDICT_FAIL
        if c[WARN]:
            return VERDICT_WARN
        return VERDICT_OK

    def exit_code(self) -> int:
        return 1 if self.counts()[FAIL] else 0

    @staticmethod
    def _line(check: Check) -> str:
        ms = f" ({check.ms:.0f} ms)" if check.ms is not None else ""
        return f"  [{LABELS[check.status]:<7}] {check.group:<13} {check.name:<20} {check.detail}{ms}"

    def render(self) -> str:
        lines = [
            f"CyberBot – {self.title}",
            f"Başlangıç: {fmt_both(self.started)}",
            f"Bitiş:     {fmt_both(utc_now())}",
            f"SONUÇ: {self.verdict()}   ({self.counts_text()})",
            "",
        ]
        groups = list(dict.fromkeys(check.group for check in self.checks))
        for group in groups:
            lines.append(f"[{group}]")
            lines += [self._line(check) for check in self.checks if check.group == group]
            lines.append("")
        if self.findings:
            lines.append("Önemli bulgular:")
            lines += [f"  - {label}: {value}" for label, value in self.findings]
            lines.append("")
        lines.append("Sürümler: " + ", ".join(f"{k} {v}" for k, v in self.versions.items()))
        lines.append(f"Ayrıntılı log (repoya girmez): {self.log_path.as_posix()}")
        return self.redact("\n".join(lines)) + "\n"

    def save(self) -> Path:
        self.summary_path.write_text(self.render(), encoding="utf-8", newline="\n")
        return self.summary_path

    def finish(self) -> int:
        """Özeti kaydeder, SONUÇ kutusunu basar, çıkış kodunu döner (0 = başarılı)."""
        path = self.save()
        verdict = self.verdict()
        bar = "=" * 50
        print()
        print(bar)
        print(f"  SONUÇ: {verdict}")
        print(f"  {self.counts_text()}")
        print(bar)
        print(f"Özet dosyası: {path.as_posix()}")
        if verdict != VERDICT_OK:
            print("HATA / UYARI satırlarının açıklaması yukarıda ve özet dosyasında.")
        self.log.info("SONUÇ: %s (%s)", verdict, self.counts_text())
        # .bat dosyası bu işaretle scriptin gerçekten çalışıp bittiğini anlar
        (self.logs_dir / f"{self.slug}_last.txt").write_text(f"{verdict}\n{path.as_posix()}\n", encoding="utf-8")
        self.close()
        return self.exit_code()
