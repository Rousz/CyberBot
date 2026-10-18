"""Çalışma süresi (uptime) kaydı.

Her bileşen ("freqtrade", "recorder") açılışta bir oturum satırı yazar, çalışırken
dakikada bir kalp atışı günceller, düzgün kapanışta kapanış zamanını yazar.
Sert kapanmada (elektrik, çökme, Docker'ın zorla durdurması) kapanış kaydı olmaz;
oturum son kalp atışı + aralık kadar sürmüş sayılır.

Rapor, oturumlardan uptime yüzdesini ve kesinti dönemlerini hesaplar; kesinti
dönemlerine denk gelen işlemler sonuçlardan ayrı gösterilir.
Tüm zamanlar UTC milisaniye.
"""

from __future__ import annotations

import logging
import os
import socket
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT NOT NULL,
    started_ms INTEGER NOT NULL,
    last_heartbeat_ms INTEGER NOT NULL,
    stopped_ms INTEGER,
    stop_kind TEXT,
    pid INTEGER,
    host TEXT,
    version TEXT,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_component ON sessions(component, started_ms);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_component ON events(component, ts_ms);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Session:
    id: int
    component: str
    started_ms: int
    last_heartbeat_ms: int
    stopped_ms: int | None
    stop_kind: str | None
    pid: int | None = None
    host: str | None = None
    version: str | None = None
    detail: str | None = None

    def end_ms(self, heartbeat_interval_ms: int = HEARTBEAT_INTERVAL_S * 1000) -> int:
        if self.stopped_ms is not None:
            return self.stopped_ms
        return self.last_heartbeat_ms + heartbeat_interval_ms


@dataclass
class Event:
    id: int
    component: str
    ts_ms: int
    kind: str
    detail: str | None


class UptimeStore:
    def __init__(self, path: str | Path, component: str):
        self.path = Path(path)
        self.component = component
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _write(self, sql: str, args: tuple) -> int:
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(sql, args)
                return cur.lastrowid
        finally:
            conn.close()

    # --- yazma ------------------------------------------------------------

    def start_session(self, *, version: str = "", detail: str = "", at_ms: int | None = None) -> int:
        ts = at_ms or now_ms()
        return self._write(
            "INSERT INTO sessions(component, started_ms, last_heartbeat_ms, pid, host, version, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.component, ts, ts, os.getpid(), socket.gethostname(), version, detail),
        )

    def heartbeat(self, session_id: int, at_ms: int | None = None) -> None:
        self._write("UPDATE sessions SET last_heartbeat_ms=? WHERE id=?", (at_ms or now_ms(), session_id))

    def stop_session(self, session_id: int, kind: str = "clean", at_ms: int | None = None) -> None:
        ts = at_ms or now_ms()
        self._write(
            "UPDATE sessions SET stopped_ms=?, stop_kind=?, last_heartbeat_ms=? WHERE id=? AND stopped_ms IS NULL",
            (ts, kind, ts, session_id),
        )

    def add_event(self, kind: str, detail: str = "", at_ms: int | None = None) -> None:
        self._write(
            "INSERT INTO events(component, ts_ms, kind, detail) VALUES (?, ?, ?, ?)",
            (self.component, at_ms or now_ms(), kind, detail),
        )

    # --- okuma ------------------------------------------------------------

    def sessions(self, component: str | None = None) -> list[Session]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, component, started_ms, last_heartbeat_ms, stopped_ms, stop_kind, pid, host, version,"
                " detail FROM sessions WHERE component=? ORDER BY started_ms",
                (component or self.component,),
            ).fetchall()
        finally:
            conn.close()
        return [Session(*row) for row in rows]

    def events(self, component: str | None = None) -> list[Event]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, component, ts_ms, kind, detail FROM events WHERE component=? ORDER BY ts_ms",
                (component or self.component,),
            ).fetchall()
        finally:
            conn.close()
        return [Event(*row) for row in rows]

    def last_heartbeat_ms(self, component: str | None = None) -> int | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT MAX(last_heartbeat_ms) FROM sessions WHERE component=?", (component or self.component,)
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None


class Heartbeat:
    """Arka planda dakikada bir kalp atışı yazan iş parçacığı.

    is_alive verilirse kalp atışı sadece o True dönerken yazılır (ör. Freqtrade'in ana
    döngüsü son dakikalarda ilerlediyse). Böylece süreç ayakta ama bot durmuş/takılmışsa
    kalp atışı kesilir, izleme uyarır ve rapor bunu kesinti sayar. Takılma bitince eski
    oturum "stalled" olarak kapanır ve yeni oturum açılır; aradaki boşluk raporda görünür.
    Güncel oturum kimliği her zaman self.session_id'dedir."""

    def __init__(
        self,
        store: UptimeStore,
        session_id: int,
        interval_s: float = HEARTBEAT_INTERVAL_S,
        *,
        is_alive=None,
        version: str = "",
    ):
        self.store = store
        self.session_id = session_id
        self.interval_s = interval_s
        self.is_alive = is_alive
        self.version = version
        self.stalled = False
        self._last_ok_ms = now_ms()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{store.component}", daemon=True)

    def start(self) -> Heartbeat:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def beat(self) -> None:
        """Tek kalp atışı turu (iş parçacığı dakikada bir çağırır; testler doğrudan çağırabilir)."""
        alive = True
        if self.is_alive is not None:
            try:
                alive = bool(self.is_alive())
            except Exception as exc:
                logger.warning("uptime is_alive kontrolü hata verdi: %s", exc)
                alive = False
        if not alive:
            if not self.stalled:
                logger.warning("uptime: ana döngü ilerlemiyor, kalp atışı durduruldu")
            self.stalled = True
            return
        if self.stalled:
            # takılma bitti: eski oturumu son sağlıklı kalp atışından sonra kapat, yenisini aç
            self.store.stop_session(self.session_id, kind="stalled",
                                    at_ms=self._last_ok_ms + int(self.interval_s * 1000))
            self.session_id = self.store.start_session(version=self.version, detail="takılma sonrası devam")
            self.stalled = False
            logger.warning("uptime: ana döngü yeniden ilerliyor, yeni oturum %s", self.session_id)
        self.store.heartbeat(self.session_id)
        self._last_ok_ms = now_ms()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.beat()
            except Exception as exc:  # disk dolu, kilit vb.: bir sonraki turda tekrar dene
                logger.warning("uptime heartbeat yazılamadı: %s", exc)


@dataclass
class UptimeSummary:
    window_start_ms: int
    window_end_ms: int
    up_ms: int
    uptime_pct: float
    downtime: list[tuple[int, int]] = field(default_factory=list)  # (başlangıç, bitiş) UTC ms
    sessions: int = 0
    unclean_stops: int = 0


def summarize(
    sessions: list[Session],
    window_start_ms: int,
    window_end_ms: int,
    heartbeat_interval_ms: int = HEARTBEAT_INTERVAL_S * 1000,
    min_gap_ms: int = 0,
) -> UptimeSummary:
    """Pencere içindeki çalışma süresi ve kesinti dönemleri.
    Kapanış kaydı olmayan oturum, son kalp atışı + aralık sonunda bitmiş sayılır
    (pencere sonundan sonrasına taşmaz). up_ms gerçek çalışma süresidir; min_gap_ms'den
    kısa boşluklar (ör. hızlı yeniden başlatma) sadece kesinti listesine yazılmaz."""
    if window_end_ms <= window_start_ms:
        return UptimeSummary(window_start_ms, window_end_ms, 0, 0.0)
    intervals = []
    unclean = 0
    for s in sessions:
        end = s.end_ms(heartbeat_interval_ms)
        start, stop = max(s.started_ms, window_start_ms), min(end, window_end_ms)
        if stop <= start:
            continue
        intervals.append((start, stop))
        running = s.stopped_ms is None and end >= window_end_ms
        if s.stopped_ms is None and not running:
            unclean += 1
    intervals.sort()
    merged: list[list[int]] = []
    for start, stop in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], stop)
        else:
            merged.append([start, stop])
    up = sum(stop - start for start, stop in merged)
    gaps = []
    cursor = window_start_ms
    for start, stop in merged:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, stop)
    if window_end_ms > cursor:
        gaps.append((cursor, window_end_ms))
    downtime = [(a, b) for a, b in gaps if b - a > min_gap_ms]
    total = window_end_ms - window_start_ms
    return UptimeSummary(window_start_ms, window_end_ms, up, 100.0 * up / total, downtime, len(intervals), unclean)
