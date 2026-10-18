"""Demo test (dry-run) raporu: 12_demo_report.bat çağırır.

    python -m cyberbot.demo_report [--days N]

tools container'ında /data volume'u ile çalışır. Okuduğu veritabanları (hepsi salt okunur):
- Freqtrade dry-run işlemleri: paths.trades_db() – tablolar `trades` ve `trade_custom_data`
  (freqtrade 2026.9 persistence/trade_model.py ve custom_data.py ile doğrulandı),
- çalışma kaydı: paths.uptime_db() (cyberbot.uptime şeması),
- türev verisi: paths.derivs_db() (varsa; docs/ARCHITECTURE.md tablo adları).

Kural: kesintili dönemleri sonuçlardan ayır. Ömrü bir kesintiyle (bot kapalı – planlı
durdurma dahil – ya da WEEX verisi bayat, 2 dakikadan uzun) kesişen işlemler ayrı listelenir
ve "temiz" istatistiklere katılmaz. Kesintiler --days penceresinden bağımsız olarak tüm
geçmişten hesaplanır (pencereden önce başlayan kesinti de sayılır).
Uptime yüzdesi planlı durdurmalar (temiz kapanış 'clean'/'reload' sonrası boşluk, ör.
11_demo_stop.bat) hariç tutularak hesaplanır; planlı durdurmalar ayrı gösterilir.
'clean'/'reload' dışındaki kapanış türleri ('stalled', 'crash:*') ve kapanış kaydı olmayan
oturumlar "temiz olmayan kapanış" sayılır.
Veritabanları boş/yoksa açık bir Türkçe mesaj yazılır, rapor yine üretilir.

Çıktı: reports/demo_report_<UTC>.txt (UTC + İstanbul saatleri).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cyberbot import paths, settings
from cyberbot.demo_status import (
    FRESH_MS,
    SectionReport,
    connect_ro,
    fmt_age,
    newest,
    read_events,
    read_sessions,
    table_exists,
)
from cyberbot.report import INFO, WARN, Outcome, describe_error
from cyberbot.timeutil import fmt_both, from_ms
from cyberbot.uptime import NORMAL_STOP_KINDS, Event, Session, summarize

DAY_MS = 86_400_000
MIN_GAP_MS = 2 * 60_000  # bundan kısa kesintiler (hızlı yeniden başlatma) işlemleri ayırmaz
UPTIME_WARN_PCT = 95.0
LIQ_COVERAGE_WARN_PCT = 90.0
DEFAULT_WALLET = 1000.0
DOWN_EVENTS = {  # kesinti başlatan olay -> bitiren olay (docs/ARCHITECTURE.md)
    "exchange_down": "exchange_recovered",
    "weex_unreachable": "weex_recovered",
}
STOP_REASONS = ("stop_loss", "trailing_stop_loss")  # raporda birlikte gösterilir
TARGET_REASONS = ("take_profit", "roi")  # strateji hedefi: custom_exit ya da custom_roi ('roi')
DERIVS_TABLES = {
    "bn_futures_data": "ts_ms",
    "bn_liquidations": "trade_ms",
    "bn_liq_1m": "bucket_ms",
    "weex_premium": "bucket_ms",
    "weex_funding_hist": "funding_ms",
    "weex_oi": "bucket_ms",
}
FEE_LINE = "WEEX komisyon/bonus: dry-run'da uygulanmaz (kâr hesabına katılmaz)"


# --------------------------------------------------------------------------
# Okuma
# --------------------------------------------------------------------------


def parse_dt_ms(value: Any) -> int | None:
    """Freqtrade (SQLAlchemy) tarihleri saat dilimsiz UTC metni olarak saklar."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


@dataclass
class TradeRow:
    id: int
    pair: str
    is_open: bool
    is_short: bool
    open_ms: int
    close_ms: int | None
    open_rate: float
    close_rate: float | None
    amount: float
    stake: float
    leverage: float
    profit_abs: float | None
    profit_ratio: float | None
    exit_reason: str | None
    funding_fees: float
    fee_open: float
    fee_close: float
    sl: float | None = None
    outages: list[str] = field(default_factory=list)

    @property
    def side(self) -> str:
        return "short" if self.is_short else "long"

    def end_ms(self, now_ms: int) -> int:
        return self.close_ms if self.close_ms is not None else now_ms

    @property
    def r_multiple(self) -> float | None:
        if self.sl is None or self.profit_abs is None:
            return None
        risk = abs(self.open_rate - self.sl) * self.amount
        return self.profit_abs / risk if risk > 0 else None


_TRADE_COLUMNS = ("id", "pair", "is_open", "is_short", "open_date", "close_date", "open_rate", "close_rate",
                  "amount", "stake_amount", "leverage", "close_profit_abs", "close_profit", "exit_reason",
                  "funding_fees", "fee_open", "fee_close")


def read_trades(path: Path) -> list[TradeRow] | None:
    """Freqtrade işlemleri; dosya yoksa None, tablo yoksa boş liste."""
    conn = connect_ro(path)
    if conn is None:
        return None
    try:
        if not table_exists(conn, "trades"):
            return []
        have = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
        cols = [c if c in have else f"NULL AS {c}" for c in _TRADE_COLUMNS]
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM trades ORDER BY open_date, id").fetchall()
        sl: dict[int, float] = {}
        if table_exists(conn, "trade_custom_data"):
            for trade_id, value in conn.execute(
                    "SELECT ft_trade_id, cd_value FROM trade_custom_data WHERE lower(cd_key) = 'sl'"):
                try:
                    sl[int(trade_id)] = float(value)
                except (TypeError, ValueError):
                    pass
    finally:
        conn.close()
    trades = []
    for r in rows:
        trades.append(TradeRow(
            id=int(r[0]), pair=str(r[1]), is_open=bool(r[2]), is_short=bool(r[3]),
            open_ms=parse_dt_ms(r[4]) or 0, close_ms=parse_dt_ms(r[5]), open_rate=float(r[6] or 0),
            close_rate=None if r[7] is None else float(r[7]), amount=float(r[8] or 0), stake=float(r[9] or 0),
            leverage=float(r[10] or 1), profit_abs=None if r[11] is None else float(r[11]),
            profit_ratio=None if r[12] is None else float(r[12]), exit_reason=r[13],
            funding_fees=float(r[14] or 0), fee_open=float(r[15] or 0), fee_close=float(r[16] or 0),
            sl=sl.get(int(r[0])),
        ))
    return trades


# --------------------------------------------------------------------------
# Hesaplar (saf, birim testli)
# --------------------------------------------------------------------------


def session_running(s: Session, now_ms: int) -> bool:
    return s.stopped_ms is None and now_ms - s.last_heartbeat_ms <= FRESH_MS


def containing_session(ts_ms: int, sessions: list[Session]) -> Session | None:
    """ts anında çalışan (en son başlamış) oturum."""
    cands = [s for s in sessions if s.started_ms <= ts_ms]
    return max(cands, key=lambda s: (s.started_ms, s.id)) if cands else None


def event_outages(events: list[Event], sessions: dict[str, list[Session]], start_ms: int,
                  end_ms: int) -> list[tuple[int, int, str]]:
    """Olaylardan kesinti dönemleri: *_down -> aynı bileşenin AYNI oturumdaki *_recovered olayına kadar.
    Sağlık durumu yeniden başlatmada sıfırlanır; bu yüzden oturum kurtarma olayı yazmadan bittiyse
    kesinti o oturumun sonunda (çökmüşse son kalp atışı + aralık) biter, sonraki oturumun olayları
    onu kapatmaz. Oturum hâlâ çalışıyorsa pencere sonuna kadar sürer."""
    out = []
    open_: dict[tuple[str, str], tuple[int, int | None]] = {}  # (bileşen, tür) -> (başlangıç, oturum sonu)

    def session_cap(component: str, ts: int) -> int | None:
        s = containing_session(ts, sessions.get(component, []))
        if s is None or session_running(s, end_ms):
            return None
        return max(s.end_ms(), ts)

    for ev in sorted(events, key=lambda e: (e.ts_ms, e.id)):
        for key, (ts, cap) in list(open_.items()):
            if key[0] == ev.component and cap is not None and cap < ev.ts_ms:
                out.append((ts, cap, key[1]))  # oturum kurtarma olayı yazmadan bitti
                del open_[key]
        if ev.kind in DOWN_EVENTS:
            key = (ev.component, ev.kind)
            if key not in open_:
                open_[key] = (ev.ts_ms, session_cap(ev.component, ev.ts_ms))
            continue
        for down, up in DOWN_EVENTS.items():
            if ev.kind == up and (ev.component, down) in open_:
                ts, _ = open_.pop((ev.component, down))
                out.append((ts, ev.ts_ms, down))
    for (_, kind), (ts, cap) in open_.items():
        out.append((ts, end_ms if cap is None else min(cap, end_ms), kind))
    return [(max(a, start_ms), min(b, end_ms), k) for a, b, k in out
            if min(b, end_ms) - max(a, start_ms) > MIN_GAP_MS]


def preceding_session(ts_ms: int, sessions: list[Session]) -> Session | None:
    """ts'de başlayan boşluktan hemen önce biten oturum."""
    cands = [s for s in sessions if s.end_ms() <= ts_ms]
    return max(cands, key=lambda s: (s.end_ms(), s.id)) if cands else None


def is_planned_gap(gap_start_ms: int, sessions: list[Session]) -> bool:
    """Boşluk temiz kapanışla ('clean'/'reload', ör. 11_demo_stop.bat) başladıysa planlı durdurmadır."""
    s = preceding_session(gap_start_ms, sessions)
    return s is not None and s.stopped_ms is not None and s.stop_kind in NORMAL_STOP_KINDS


def abnormal_stops(sessions: list[Session], start_ms: int, now_ms: int) -> list[Session]:
    """Dönem içinde biten ve normal kapanmayan oturumlar: kapanış kaydı yok, 'stalled', 'crash:*'..."""
    out = []
    for s in sessions:
        if session_running(s, now_ms) or not start_ms <= s.end_ms() <= now_ms:
            continue
        if s.stopped_ms is None or s.stop_kind not in NORMAL_STOP_KINDS:
            out.append(s)
    return out


def stop_label(s: Session) -> str:
    kind = s.stop_kind or ""
    if s.stopped_ms is None:
        return "kapanış kaydı yok (elektrik kesintisi, çökme ya da zorla durdurma)"
    if kind == "stalled":
        return "ana döngü durdu/takıldı (stalled; ör. hata sonrası STOPPED ya da Telegram /stop)"
    if kind.startswith("crash:"):
        return f"Freqtrade hatayla kapandı ({kind.split(':', 1)[1] or '?'})"
    return f"kapanış türü '{kind or '?'}'"


def mark_outages(trades: list[TradeRow], periods: list[tuple[int, int, str]], now_ms: int) -> None:
    for t in trades:
        t.outages = sorted({label for a, b, label in periods if t.open_ms < b and t.end_ms(now_ms) > a})


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


@dataclass
class Stats:
    n: int
    wins: int
    losses: int
    total: float
    gross_profit: float
    gross_loss: float
    max_dd_abs: float
    max_dd_pct: float
    avg_r: float | None
    n_r: int

    @property
    def win_rate(self) -> float:
        return 100.0 * self.wins / self.n if self.n else 0.0

    @property
    def profit_factor(self) -> float | None:
        if self.gross_loss < 0:
            return self.gross_profit / -self.gross_loss
        return None


def trade_stats(trades: list[TradeRow], wallet: float) -> Stats:
    closed = sorted((t for t in trades if t.close_ms is not None and t.profit_abs is not None),
                    key=lambda t: (t.close_ms, t.id))
    pnl = [t.profit_abs for t in closed]
    equity = peak = wallet
    max_dd_abs = max_dd_pct = 0.0
    for p in pnl:
        equity += p
        peak = max(peak, equity)
        dd = peak - equity
        if dd > max_dd_abs:
            max_dd_abs, max_dd_pct = dd, (100.0 * dd / peak if peak > 0 else 0.0)
    rs = [t.r_multiple for t in closed if t.r_multiple is not None]
    return Stats(
        n=len(closed), wins=sum(1 for p in pnl if p > 0), losses=sum(1 for p in pnl if p <= 0), total=sum(pnl),
        gross_profit=sum(p for p in pnl if p > 0), gross_loss=sum(p for p in pnl if p < 0),
        max_dd_abs=max_dd_abs, max_dd_pct=max_dd_pct, avg_r=sum(rs) / len(rs) if rs else None, n_r=len(rs),
    )


def reason_label(reason: str | None) -> str:
    if reason in STOP_REASONS:
        return "stop_loss + trailing_stop_loss"
    if reason in TARGET_REASONS:
        return "hedef (take profit)"
    return reason or "?"


def fmt_usdt(v: float) -> str:
    return f"{v:+,.2f} USDT"


def fmt_pf(pf: float | None, stats: Stats) -> str:
    if pf is not None:
        return f"{pf:.2f}"
    return "∞ (zarar yok)" if stats.gross_profit > 0 else "-"


def fmt_period(a: int, b: int) -> str:
    return f"{fmt_both(from_ms(a))} → {fmt_both(from_ms(b))} ({fmt_age(b - a)})"


def stats_lines(stats: Stats, wallet: float) -> list[str]:
    if not stats.n:
        return ["kapanmış işlem yok"]
    lines = [
        f"işlem sayısı: {stats.n} (kazanan {stats.wins}, kaybeden {stats.losses})",
        f"kazanma oranı: %{stats.win_rate:.1f}",
        f"toplam kâr/zarar: {fmt_usdt(stats.total)} (başlangıç {wallet:,.0f} USDT'nin %{100 * stats.total / wallet:+.2f}'i)"
        if wallet else f"toplam kâr/zarar: {fmt_usdt(stats.total)}",
        f"kâr faktörü: {fmt_pf(stats.profit_factor, stats)}",
        f"ortalama R: {stats.avg_r:+.2f} ({stats.n_r} işlemde stop kaydı var)" if stats.avg_r is not None
        else "ortalama R: - (stratejinin 'sl' kaydı olan işlem yok)",
        f"en büyük düşüş (kapanmış işlemlerin bakiye eğrisi): {stats.max_dd_abs:,.2f} USDT (%{stats.max_dd_pct:.2f})",
    ]
    return lines


def group_lines(trades: list[TradeRow], key, wallet: float) -> list[str]:
    groups: dict[str, list[TradeRow]] = defaultdict(list)
    for t in trades:
        groups[key(t)].append(t)
    lines = []
    for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s = trade_stats(items, wallet)
        lines.append(f"{name}: {s.n} işlem, kazanma %{s.win_rate:.0f}, {fmt_usdt(s.total)}")
    return lines or ["-"]


def pair_lines(trades: list[TradeRow], n: int = 3) -> list[str]:
    totals: dict[str, float] = defaultdict(float)
    counts: Counter = Counter()
    for t in trades:
        totals[t.pair] += t.profit_abs or 0.0
        counts[t.pair] += 1
    if not totals:
        return ["-"]
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    best = ", ".join(f"{p} {fmt_usdt(v)} ({counts[p]})" for p, v in ranked[:n] if v > 0)
    worst = ", ".join(f"{p} {fmt_usdt(v)} ({counts[p]})" for p, v in reversed(ranked[-n:]) if v < 0)
    return [f"en iyi: {best or '-'}", f"en kötü: {worst or '-'}"]


def trade_line(t: TradeRow, now_ms: int) -> str:
    end = f"→ {fmt_both(from_ms(t.close_ms))}" if t.close_ms is not None else "(açık)"
    pnl = f", {fmt_usdt(t.profit_abs)}" if t.profit_abs is not None and t.close_ms is not None else ""
    reason = f", {t.exit_reason}" if t.exit_reason else ""
    why = f" [kesinti: {', '.join(t.outages)}]" if t.outages else ""
    return (f"#{t.id} {t.pair} {t.side} {t.leverage:g}x, {fmt_both(from_ms(t.open_ms))} {end}, "
            f"teminat {t.stake:,.2f} USDT{pnl}{reason}{why}")


# --------------------------------------------------------------------------
# Rapor
# --------------------------------------------------------------------------


OUTAGE_LABELS = {"bot": "bot kapalı", "bot_planned": "bot kapalı (planlı durdurma)",
                 "exchange_down": "WEEX verisi bayat", "weex_unreachable": "WEEX'e ulaşılamıyor"}


class DemoReport:
    def __init__(self, rep: SectionReport, *, now_ms: int, days: float | None, wallet: float,
                 trades_path: Path, uptime_path: Path, derivs_path: Path):
        self.rep = rep
        self.now = now_ms
        self.days = days
        self.wallet = wallet
        self.trades_path, self.uptime_path, self.derivs_path = trades_path, uptime_path, derivs_path
        self.sessions: dict[str, list[Session]] = {}
        self.events: list[Event] = []
        self.trades: list[TradeRow] | None = None
        self.outages: list[tuple[int, int, str]] = []
        self.start = now_ms

    def build(self) -> None:
        r = self.rep
        r.run("Veri", "uptime_db", self.load_uptime, critical=False)
        r.run("Veri", "islem_db", self.load_trades, critical=False)
        self.start = self.window_start()
        r.add("Genel", "donem", INFO, fmt_period(self.start, self.now))
        r.run("Çalışma", "bot_uptime", lambda: self.uptime("freqtrade"), critical=False)
        r.run("Çalışma", "kaydedici_uptime", lambda: self.uptime("recorder"), critical=False)
        r.run("Çalışma", "saglik_olaylari", self.health_events, critical=False)
        r.run("İşlemler", "ozet", self.trade_summary, critical=False)
        r.run("Türev", "kapsama", self.derivs_coverage, critical=False)
        warnings = [f"{c.group}/{c.name}: {c.detail}" for c in r.checks if c.status == WARN]
        r.section("Uyarılar", warnings or ["uyarı yok"])

    # --- veri ---------------------------------------------------------------

    def load_uptime(self):
        if not self.uptime_path.exists():
            return info("çalışma kaydı yok (bot henüz hiç başlatılmamış): " + self.uptime_path.as_posix())
        self.sessions = read_sessions(self.uptime_path)
        self.events = read_events(self.uptime_path)
        n = {c: len(self.sessions.get(c, [])) for c in ("freqtrade", "recorder")}
        return f"oturum: bot {n['freqtrade']}, kaydedici {n['recorder']}; olay {len(self.events)}"

    def load_trades(self):
        self.trades = read_trades(self.trades_path)
        if self.trades is None:
            return info("işlem veritabanı yok (bot henüz hiç çalışmamış): " + self.trades_path.as_posix())
        return f"{len(self.trades)} işlem kaydı ({sum(1 for t in self.trades if t.is_open)} açık)"

    def window_start(self) -> int:
        if self.days:
            return int(self.now - self.days * DAY_MS)
        starts = [s.started_ms for s in self.sessions.get("freqtrade", [])]
        starts += [t.open_ms for t in self.trades or [] if t.open_ms]
        return min(starts) if starts else self.now

    # --- çalışma süresi -----------------------------------------------------

    def uptime(self, component: str):
        sessions = self.sessions.get(component, [])
        label = "bot" if component == "freqtrade" else "kaydedici"
        if not sessions:
            return Outcome(WARN, f"{label} için çalışma kaydı yok")
        first = min(s.started_ms for s in sessions)
        if component == "freqtrade":
            # işlem ayırma: pencereden bağımsız, tüm geçmişteki boşluklar (planlı durdurmalar dahil)
            for a, b in summarize(sessions, first, self.now).downtime:
                if b - a > MIN_GAP_MS:
                    self.outages.append((a, b, "bot_planned" if is_planned_gap(a, sessions) else "bot"))
        start = max(self.start, first)
        if self.now <= start:
            return Outcome(INFO, f"{label}: dönem çok kısa")
        summ = summarize(sessions, start, self.now)  # tüm boşluklar (kısa olanlar dahil)
        planned = [(a, b) for a, b in summ.downtime if is_planned_gap(a, sessions)]
        outages = [(a, b) for a, b in summ.downtime if (a, b) not in planned]
        planned_ms = sum(b - a for a, b in planned)
        expected_ms = self.now - start - planned_ms  # planlı çalışma süresi
        shown_out = [(a, b) for a, b in outages if b - a > MIN_GAP_MS]
        shown_planned = [(a, b) for a, b in planned if b - a > MIN_GAP_MS]
        abnormal = abnormal_stops(sessions, start, self.now)
        restarts = max(0, summ.sessions - 1)
        latest = newest(sessions)
        running = session_running(latest, self.now)
        state = "şu an çalışıyor" if running else (
            f"şu an kapalı (son kayıt {fmt_both(from_ms(latest.end_ms()))})")
        since = f" ({fmt_both(from_ms(start))} itibarıyla)" if start != self.start else ""
        pct = 100.0 * summ.up_ms / expected_ms if expected_ms > 0 else None
        pct_text = f"%{pct:.2f}" if pct is not None else "- (dönem boyunca planlı olarak kapalı)"
        text = (f"{pct_text}{since} (planlı durdurmalar hariç); kesinti {len(shown_out)} "
                f"(toplam {fmt_age(sum(b - a for a, b in shown_out))}), planlı durdurma {len(shown_planned)} "
                f"(toplam {fmt_age(sum(b - a for a, b in shown_planned))}), yeniden başlatma {restarts}, "
                "temiz olmayan kapanış "
                f"{len(abnormal)}; {state}")
        self.rep.section(f"Kesinti dönemleri – {label}", [fmt_period(a, b) for a, b in shown_out]
                         or ["2 dakikadan uzun kesinti yok"], echo=False)
        self.rep.section(f"Planlı durdurmalar – {label} (uptime'a sayılmaz, işlemler yine ayrılır)",
                         [fmt_period(a, b) for a, b in shown_planned] or ["yok"], echo=False)
        if abnormal:
            self.rep.section(f"Temiz olmayan kapanışlar – {label}",
                             [f"{fmt_both(from_ms(s.end_ms()))}: {stop_label(s)}" for s in abnormal], echo=False)
        warn = []
        if pct is not None and pct < UPTIME_WARN_PCT:
            warn.append(f"%{UPTIME_WARN_PCT:.0f}'in altında")
        if abnormal:
            kinds = Counter("kapanış kaydı yok" if s.stopped_ms is None else (s.stop_kind or "?").split(":")[0]
                            for s in abnormal)
            warn.append("temiz olmayan kapanış: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
        return Outcome(WARN, text + " – " + "; ".join(warn)) if warn else text

    def health_events(self):
        events = [e for e in self.events if self.start <= e.ts_ms <= self.now]
        # işlem ayırma için tüm geçmiş: pencereden önce başlayan kesinti de sayılır
        self.outages += event_outages(self.events, self.sessions, 0, self.now)
        if not events:
            return "dönemde sağlık olayı yok (WEEX/Binance kesintisi kaydedilmedi)"
        counts = Counter(e.kind for e in events)
        lines = [f"{fmt_both(from_ms(e.ts_ms))} {e.component} {e.kind}" + (f" – {e.detail}" if e.detail else "")
                 for e in events[-20:]]
        self.rep.section(f"Sağlık olayları (son {len(lines)})", lines, echo=False)
        return ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))

    # --- işlemler -----------------------------------------------------------

    def trade_summary(self):
        trades = self.trades or []
        closed = [t for t in trades if not t.is_open and t.close_ms is not None and t.close_ms >= self.start]
        open_trades = [t for t in trades if t.is_open]
        mark_outages(closed + open_trades, self.outages, self.now)
        for t in closed + open_trades:
            t.outages = [OUTAGE_LABELS.get(o, o) for o in t.outages]
        clean = [t for t in closed if not t.outages]
        dirty = [t for t in closed if t.outages]
        stats = trade_stats(clean, self.wallet)
        all_stats = trade_stats(closed, self.wallet)

        self.rep.section("Temiz işlemlerin sonuçları (kesintili işlemler hariç)", stats_lines(stats, self.wallet))
        self.rep.section("Long / short (temiz)", group_lines(clean, lambda t: t.side, self.wallet), echo=False)
        self.rep.section("Çıkış nedenleri (temiz)", group_lines(clean, lambda t: reason_label(t.exit_reason),
                                                                self.wallet), echo=False)
        self.rep.section("Pariteler (temiz)", pair_lines(clean), echo=False)
        self.rep.section("Kesintili dönemle kesişen işlemler (istatistik dışı)",
                         [trade_line(t, self.now) for t in dirty] or ["yok"], echo=False)
        self.rep.section("Açık işlemler", [trade_line(t, self.now) for t in open_trades] or ["yok"], echo=False)
        funding = sum(t.funding_fees for t in closed + open_trades)
        fee_rates = sorted({f"%{100 * t.fee_open:.3f}" for t in closed + open_trades if t.fee_open})
        self.rep.add("İşlemler", "komisyon", INFO, FEE_LINE)
        if fee_rates:
            self.rep.add("İşlemler", "tahmini_ucret", INFO,
                         f"Freqtrade dry-run kendi tahmini ücretini düşer: emir başına {', '.join(fee_rates)} "
                         "(kâr/zarara dahil)")
        self.rep.add("İşlemler", "funding", INFO,
                     f"funding toplamı {fmt_usdt(funding)} (kâr/zarara dahil; + alındı, − ödendi)")
        if dirty:
            self.rep.finding("Kesintili işlemler", f"{len(dirty)} işlem kesintiyle kesişti, toplam "
                             f"{fmt_usdt(trade_stats(dirty, self.wallet).total)}; temiz sonuçlara katılmadı")
        if self.trades is None:
            return Outcome(WARN, "henüz işlem yok (işlem veritabanı oluşmamış)")
        if not closed:
            return Outcome(WARN, f"dönemde kapanmış işlem yok (açık {len(open_trades)}) – bot sinyal bekliyor olabilir")
        pf = fmt_pf(stats.profit_factor, stats)
        self.rep.finding("Temiz sonuç", f"{stats.n} işlem, kazanma %{stats.win_rate:.1f}, {fmt_usdt(stats.total)}, "
                         f"kâr faktörü {pf}, en büyük düşüş %{stats.max_dd_pct:.2f}")
        return (f"kapanmış {len(closed)} (temiz {len(clean)}, kesintili {len(dirty)}), açık {len(open_trades)}; "
                f"tümü {fmt_usdt(all_stats.total)}, temiz {fmt_usdt(stats.total)}")

    # --- türev verisi -------------------------------------------------------

    def derivs_coverage(self):
        conn = connect_ro(self.derivs_path)
        if conn is None:
            return info("türev veritabanı yok (kaydedici henüz veri yazmamış)")
        since = self.now - DAY_MS
        lines, warn = [], []
        try:
            for table, col in DERIVS_TABLES.items():
                if table_exists(conn, table):
                    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} >= ?", (since,)).fetchone()[0]
                    lines.append(f"{table}: {n:,} satır")
                else:
                    lines.append(f"{table}: tablo yok")
            gaps = []
            if table_exists(conn, "gaps"):
                gaps = conn.execute("SELECT source, COUNT(*) FROM gaps WHERE state = 'open' GROUP BY source"
                                    " ORDER BY source").fetchall()
            ws = []
            if table_exists(conn, "ws_sessions"):
                ws = conn.execute("SELECT url, open_ms, close_ms FROM ws_sessions WHERE close_ms IS NULL OR "
                                  "close_ms >= ?", (since,)).fetchall()
        finally:
            conn.close()
        gap_text = ", ".join(f"{s} {n}" for s, n in gaps) or "yok"
        lines.append(f"açık boşluklar (kaynak başına): {gap_text}")
        rec = self.sessions.get("recorder", [])
        latest = newest(rec)
        cap = self.now if latest is None or session_running(latest, self.now) else latest.end_ms()
        start = max(since, min((s.started_ms for s in rec), default=since))
        if any(u and "binance" in u for u, _, _ in ws):
            ws = [row for row in ws if row[0] and "binance" in row[0]]
        intervals = merge_intervals([(max(o, start), min(c if c is not None else cap, self.now)) for _, o, c in ws])
        cov = 100.0 * sum(b - a for a, b in intervals) / (self.now - start) if self.now > start else 0.0
        lines.append(f"likidasyon WS kapsaması: %{cov:.1f} ({fmt_period(start, self.now)})")
        self.rep.section("Türev verisi (son 24 saat)", lines, echo=False)
        if cov < LIQ_COVERAGE_WARN_PCT:
            warn.append(f"likidasyon WS kapsaması %{cov:.1f}")
        text = f"likidasyon WS %{cov:.1f}, açık boşluk {sum(n for _, n in gaps)}"
        return Outcome(WARN, text + " – " + ", ".join(warn)) if warn else text


def info(detail: str) -> Outcome:
    return Outcome(INFO, detail)


def load_wallet() -> float:
    try:
        return float(settings.load_config().get("dry_run_wallet", DEFAULT_WALLET))
    except Exception:
        return DEFAULT_WALLET


def main(argv: list[str] | None = None, *, now_ms: int | None = None, reports_dir: Path | None = None,
         wallet: float | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cyberbot.demo_report", description="Demo test (dry-run) raporu")
    parser.add_argument("--days", type=float, default=None, help="sadece son N gün (varsayılan: tümü)")
    args = parser.parse_args(argv)
    rep = SectionReport("Demo test raporu (dry-run)", "demo_report", reports_dir or paths.reports_dir())
    print("Demo test raporu hazırlanıyor (sadece okunur, bot etkilenmez)...\n")
    try:
        demo = DemoReport(rep, now_ms=now_ms or int(time.time() * 1000), days=args.days,
                          wallet=load_wallet() if wallet is None else wallet,
                          trades_path=paths.trades_db(), uptime_path=paths.uptime_db(),
                          derivs_path=paths.derivs_db())
        demo.build()
    except Exception as exc:
        rep.log.exception("beklenmeyen hata")
        rep.add("Genel", "script_hatasi", WARN, describe_error(exc))
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
