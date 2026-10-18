"""Demo testi başlatma / durdurma kontrolü (10_demo_start.bat, 11_demo_stop.bat çağırır).

    python -m cyberbot.demo_status start --since <utc_ms>
    python -m cyberbot.demo_status stop  --since <utc_ms>

tools container'ında /data volume'u ile çalışır; sadece uptime veritabanını (salt okunur)
ve log dosyalarını okur, borsalara bağlanmaz.

start: "docker compose up" sonrası en fazla ~120 sn bekler: bot (freqtrade) ve kaydedici
(recorder) için since'ten sonra açılmış (ya da since'ten sonra kalp atışı gelen, zaten
çalışan) bir oturum arar. Olmazsa son log satırlarını (gizli bilgiler maskeli) rapora ekler.
stop: "docker compose stop" sonrası iki oturumun da temiz kapanış kaydı yazdığını doğrular.

Özet: reports/demo_start_<UTC>.txt / reports/demo_stop_<UTC>.txt
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from cyberbot import paths
from cyberbot.report import FAIL, INFO, OK, WARN, Report
from cyberbot.timeutil import fmt_both, from_ms
from cyberbot.uptime import HEARTBEAT_INTERVAL_S, Event, Session

COMPONENTS = ("freqtrade", "recorder")
LABELS = {"freqtrade": "bot (Freqtrade)", "recorder": "kaydedici (recorder)"}
LOG_FILES = {"freqtrade": "freqtrade.log", "recorder": "recorder.log"}
SECRET_ENV_KEYS = ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "WEEX_API_KEY", "WEEX_API_SECRET", "WEEX_API_PASSPHRASE")

START_TIMEOUT_S = 120
STOP_TIMEOUT_S = 30
POLL_S = 5
SETTLE_S = 15  # oturum bulunduktan sonra hemen çökmediğini görmek için
CLOCK_SKEW_MS = 60_000  # Windows saati (since) ile container saati arasındaki olası fark
FRESH_MS = HEARTBEAT_INTERVAL_S * 1000 * 2 + 30_000  # kalp atışı en fazla bu kadar eski olabilir
TAIL_LINES = 30


class Clock:
    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


# --------------------------------------------------------------------------
# Gizli bilgi maskeleme ve log kuyruğu
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}")
_KV_RE = re.compile(
    r"(?i)\b(token|secret|password|passphrase|api[_-]?key|apikey|jwt[_-]?secret[_-]?key|authorization|chat[_-]?id)"
    r"(\W{0,3}\s*[:=]\s*['\"]?)([^\s'\",}]+)")
_LONG_RE = re.compile(r"(?<![\w./-])[A-Za-z0-9+_=-]{40,}(?![\w./-])")


def redact_text(text: str) -> str:
    """Token'a benzeyen her şeyi maskeler (Telegram token, anahtar=değer, uzun rastgele dizgiler)."""
    text = _TOKEN_RE.sub("***", text)
    text = _KV_RE.sub(lambda m: m.group(1) + m.group(2) + "***", text)
    return _LONG_RE.sub("***", text)


def tail_lines(path: Path, n: int = TAIL_LINES, max_bytes: int = 256 * 1024) -> list[str] | None:
    """Dosyanın son n satırı (yoksa None). Büyük dosyada sadece sondaki max_bytes okunur."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read()
    except OSError:
        return None
    lines = data.decode("utf-8", errors="replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]  # yarım kalmış ilk satır
    return [redact_text(line.rstrip()) for line in lines[-n:]]


# --------------------------------------------------------------------------
# Uptime veritabanı (salt okunur)
# --------------------------------------------------------------------------


def connect_ro(path: Path) -> sqlite3.Connection | None:
    """SQLite dosyasını salt okunur açar; dosya yoksa None."""
    path = Path(path)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def safe_read_sessions(path: Path, errors: list[str]) -> dict[str, list[Session]]:
    """Kilitli/bozuk veritabanı kontrolü düşürmesin: hata errors'a yazılır, boş döner."""
    try:
        return read_sessions(path)
    except sqlite3.Error as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        return {}


def read_sessions(path: Path) -> dict[str, list[Session]]:
    conn = connect_ro(path)
    if conn is None:
        return {}
    try:
        if not table_exists(conn, "sessions"):
            return {}
        rows = conn.execute(
            "SELECT id, component, started_ms, last_heartbeat_ms, stopped_ms, stop_kind, pid, host, version, detail"
            " FROM sessions ORDER BY started_ms, id").fetchall()
    finally:
        conn.close()
    out: dict[str, list[Session]] = {}
    for row in rows:
        out.setdefault(row[1], []).append(Session(*row))
    return out


def read_events(path: Path) -> list[Event]:
    conn = connect_ro(path)
    if conn is None:
        return []
    try:
        if not table_exists(conn, "events"):
            return []
        rows = conn.execute("SELECT id, component, ts_ms, kind, detail FROM events ORDER BY ts_ms, id").fetchall()
    finally:
        conn.close()
    return [Event(*row) for row in rows]


# --------------------------------------------------------------------------
# Karar mantığı (saf, birim testli)
# --------------------------------------------------------------------------


@dataclass
class State:
    status: str  # OK / WARN / FAIL
    kind: str  # new / running / none / stopped / stale / clean / unclean / already / other
    detail: str
    session: Session | None = None

    @property
    def done(self) -> bool:
        return self.status == OK


def fmt_age(ms: int) -> str:
    s = max(0, ms) / 1000
    if s < 120:
        return f"{s:.0f} sn"
    if s < 7200:
        return f"{s / 60:.0f} dk"
    if s < 2 * 86400:
        return f"{s / 3600:.1f} saat"
    return f"{s / 86400:.1f} gün"


def newest(sessions: list[Session]) -> Session | None:
    return max(sessions, key=lambda s: (s.started_ms, s.id)) if sessions else None


def classify_start(sessions: list[Session], since_ms: int, now_ms: int) -> State:
    s = newest(sessions)
    if s is None:
        return State(FAIL, "none", "henüz hiç oturum kaydı yok (açılış sürüyor ya da açılırken hata oldu)")
    age = now_ms - s.last_heartbeat_ms
    if s.stopped_ms is None and age <= FRESH_MS:
        if s.started_ms >= since_ms - CLOCK_SKEW_MS:
            return State(OK, "new", f"yeni oturum {fmt_both(from_ms(s.started_ms))} açıldı, "
                                    f"son kalp atışı {fmt_age(age)} önce", s)
        if s.last_heartbeat_ms > since_ms:
            return State(OK, "running", f"zaten çalışıyordu ({fmt_both(from_ms(s.started_ms))} oturumu, "
                                        f"yeniden başlatılmadı); son kalp atışı {fmt_age(age)} önce", s)
        return State(FAIL, "running", f"eski oturum ({fmt_both(from_ms(s.started_ms))}) var ama başlatma "
                                      "komutundan sonra kalp atışı gelmedi", s)
    if s.stopped_ms is not None:
        return State(FAIL, "stopped", f"son oturum {fmt_both(from_ms(s.stopped_ms))} kapandı "
                                      f"({s.stop_kind or '?'}); yeni oturum açılmadı", s)
    return State(FAIL, "stale", f"son kalp atışı {fmt_age(age)} önce – çalışmıyor ya da çöktü", s)


def classify_stop(sessions: list[Session], since_ms: int, now_ms: int) -> State:
    s = newest(sessions)
    if s is None:
        return State(WARN, "none", "hiç oturum kaydı yok (hiç çalışmamış)")
    if s.stopped_ms is None:
        return State(FAIL, "unclean", f"kapanış kaydı yok: son kalp atışı {fmt_both(from_ms(s.last_heartbeat_ms))} – "
                                      "Docker süresi içinde kapanmadı ve zorla durduruldu ya da daha önce çökmüştü", s)
    duration = fmt_age(s.stopped_ms - s.started_ms)
    if s.stopped_ms < since_ms - CLOCK_SKEW_MS:
        return State(WARN, "already", f"zaten durmuştu: {fmt_both(from_ms(s.stopped_ms))} ({s.stop_kind or '?'})", s)
    if (s.stop_kind or "") != "clean":
        return State(WARN, "other", f"kapandı ama kapanış türü '{s.stop_kind}' ({fmt_both(from_ms(s.stopped_ms))})", s)
    return State(OK, "clean", f"temiz kapandı {fmt_both(from_ms(s.stopped_ms))}; oturum süresi {duration}", s)


# --------------------------------------------------------------------------
# Rapor (Report + serbest metin bölümleri)
# --------------------------------------------------------------------------


class SectionReport(Report):
    """Report'a çok satırlı bölümler ekler (log kuyruğu, işlem tabloları). Bölümler
    özette "Sürümler" satırından önce yer alır; ekranda finish()'ten önce basılır."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sections: list[tuple[str, list[str]]] = []

    def section(self, title: str, lines: list[str], *, echo: bool = True) -> None:
        lines = [self.redact(redact_text(str(line))) for line in lines]
        self.sections.append((title, lines))
        for line in lines:
            self.log.info("%s | %s", title, line)
        if echo:
            print(f"\n{title}:")
            for line in lines:
                print(f"  {line}")

    def render(self) -> str:
        text = super().render()
        if not self.sections:
            return text
        block: list[str] = []
        for title, lines in self.sections:
            block += [f"{title}:", *[f"  {line}" for line in lines], ""]
        head, sep, tail = text.rpartition("Sürümler: ")
        body = self.redact("\n".join(block)) + "\n"
        return head + body + sep + tail if sep else text + body


def new_report(title: str, slug: str, reports_dir: Path | None, env: dict) -> SectionReport:
    rep = SectionReport(title, slug, reports_dir or paths.reports_dir())
    for key in SECRET_ENV_KEYS:
        rep.add_secret(env.get(key))
    return rep


def add_log_tails(rep: SectionReport, logs_dir: Path, components) -> None:
    for comp in components:
        path = logs_dir / LOG_FILES[comp]
        lines = tail_lines(path)
        if lines is None:
            rep.section(f"Son log satırları – {LOG_FILES[comp]}", [f"dosya yok: {path.as_posix()}"])
        else:
            rep.section(f"Son {len(lines)} log satırı – {LOG_FILES[comp]}", lines or ["(boş)"])


START_HINTS = {
    "freqtrade": [
        "Bot açılmadı veya hemen kapandı. Sık nedenler: WEEX'e ulaşılamıyor (piyasalar yüklenemedi),",
        "config hatası ya da Docker imajı derlenemedi. Aşağıdaki freqtrade.log satırlarına bak.",
        "Docker Desktop -> Containers -> cyberbot -> freqtrade satırında durum 'Restarting' olabilir;",
        "bu durumda bot birkaç saniyede bir yeniden denemeye devam eder.",
    ],
    "recorder": [
        "Kaydedici açılmadı. Bot işlem yapmaya devam edebilir ama türev verisi ve bot çalışmıyor",
        "uyarıları gelmez. Aşağıdaki recorder.log satırlarına bak.",
    ],
}


def run_start(since_ms: int, *, timeout_s: float = START_TIMEOUT_S, poll_s: float = POLL_S,
              settle_s: float = SETTLE_S, clock: Clock | None = None, uptime_path: Path | None = None,
              logs_dir: Path | None = None, reports_dir: Path | None = None, env: dict | None = None) -> int:
    clock = clock or Clock()
    env = dict(os.environ) if env is None else env
    uptime_path = uptime_path or paths.uptime_db()
    logs_dir = logs_dir or paths.repo_dir() / "user_data" / "logs"
    rep = new_report("Demo test başlatma kontrolü", "demo_start", reports_dir, env)
    print(f"Bot ve kaydedicinin açılması bekleniyor (en fazla {timeout_s:.0f} sn)...")
    rep.add("Genel", "baslatma_zamani", INFO, fmt_both(from_ms(since_ms)))
    telegram = bool((env.get("TELEGRAM_TOKEN") or "").strip() and (env.get("TELEGRAM_CHAT_ID") or "").strip())
    rep.add("Genel", "telegram", INFO if telegram else WARN,
            "açık: bot Telegram'dan mesaj atar ve komut alır" if telegram else
            ".env'de TELEGRAM_TOKEN veya TELEGRAM_CHAT_ID boş – Telegram kapalı (setup_env.bat)")

    deadline = clock.now_ms() + int(timeout_s * 1000)
    states: dict[str, State] = {}
    db_errors: list[str] = []
    while True:
        sessions = safe_read_sessions(uptime_path, db_errors)
        now = clock.now_ms()
        states = {c: classify_start(sessions.get(c, []), since_ms, now) for c in COMPONENTS}
        if all(s.done for s in states.values()) or now >= deadline:
            break
        clock.sleep(poll_s)
    if all(s.done for s in states.values()) and settle_s > 0:
        clock.sleep(settle_s)
        sessions = safe_read_sessions(uptime_path, db_errors)
        for comp in COMPONENTS:
            latest = newest(sessions.get(comp, []))
            first = states[comp].session
            if latest is None or first is None or latest.id != first.id or latest.stopped_ms is not None:
                states[comp] = State(FAIL, "crashed", "açıldı ama hemen kapandı/yeniden başladı", latest)

    for comp in COMPONENTS:
        rep.add("Durum", comp, states[comp].status, f"{LABELS[comp]}: {states[comp].detail}")
    if db_errors:
        rep.add("Durum", "uptime_db", WARN, f"çalışma kaydı okunamadı ({len(db_errors)} kez): {db_errors[-1][:200]}")
    failed = [c for c in COMPONENTS if states[c].status == FAIL]
    if failed:
        for comp in failed:
            rep.section(f"Açıklama – {LABELS[comp]}", START_HINTS[comp])
        add_log_tails(rep, logs_dir, failed)
        rep.finding("Ne yapmalı", "Bu özet dosyasını (reports klasöründe) bana getir; Docker Desktop açık kalsın.")
    else:
        rep.finding("Durum", "demo test arka planda çalışıyor. Pencereyi kapatabilirsin; bot çalışmaya devam eder.")
    return rep.finish()


def run_stop(since_ms: int, *, timeout_s: float = STOP_TIMEOUT_S, poll_s: float = POLL_S,
             clock: Clock | None = None, uptime_path: Path | None = None, logs_dir: Path | None = None,
             reports_dir: Path | None = None, env: dict | None = None) -> int:
    clock = clock or Clock()
    env = dict(os.environ) if env is None else env
    uptime_path = uptime_path or paths.uptime_db()
    logs_dir = logs_dir or paths.repo_dir() / "user_data" / "logs"
    rep = new_report("Demo test durdurma kontrolü", "demo_stop", reports_dir, env)
    rep.add("Genel", "durdurma_zamani", INFO, fmt_both(from_ms(since_ms)))
    if not Path(uptime_path).exists():
        rep.add("Durum", "uptime_db", WARN, "çalışma kaydı veritabanı yok: demo test hiç başlatılmamış")
        return rep.finish()

    deadline = clock.now_ms() + int(timeout_s * 1000)
    db_errors: list[str] = []
    while True:
        sessions = safe_read_sessions(uptime_path, db_errors)
        now = clock.now_ms()
        states = {c: classify_stop(sessions.get(c, []), since_ms, now) for c in COMPONENTS}
        if all(s.kind != "unclean" for s in states.values()) or now >= deadline:
            break
        clock.sleep(poll_s)
    for comp in COMPONENTS:
        rep.add("Durum", comp, states[comp].status, f"{LABELS[comp]}: {states[comp].detail}")
    if db_errors:
        rep.add("Durum", "uptime_db", WARN, f"çalışma kaydı okunamadı ({len(db_errors)} kez): {db_errors[-1][:200]}")
    unclean = [c for c in COMPONENTS if states[c].kind == "unclean"]
    if unclean:
        rep.section("Açıklama", [
            "Kapanış kaydı olmayan oturum raporda kesinti olarak sayılır; işlem verisi kaybolmaz.",
            "Tekrarlarsa bana bildir (docker-compose.yml'deki kapanma süresi artırılabilir).",
        ])
        add_log_tails(rep, logs_dir, unclean)
    rep.finding("Durum", "bot ve kaydedici durduruldu; bilgisayar yeniden açılsa da kendiliğinden başlamazlar. "
                         "Tekrar başlatmak için 10_demo_start.bat")
    return rep.finish()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cyberbot.demo_status", description="Demo test başlat/durdur kontrolü")
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--since", type=int, default=None, help="komutun verildiği an (UTC ms)")
    parser.add_argument("--timeout", type=float, default=None, help="en fazla bekleme (sn)")
    args = parser.parse_args(argv)
    since = args.since if args.since is not None else Clock().now_ms()
    if args.action == "start":
        return run_start(since, timeout_s=args.timeout or START_TIMEOUT_S)
    return run_stop(since, timeout_s=args.timeout or STOP_TIMEOUT_S)


if __name__ == "__main__":
    sys.exit(main())
