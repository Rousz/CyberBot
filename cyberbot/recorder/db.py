"""derivs.sqlite: türev verisi veritabanı (kaydedici tek yazardır).

Şema docs/ARCHITECTURE.md tablosuyla aynıdır (tablo/sütun adları değişmez; sadece
sütun/tablo eklenir). Tüm zamanlar UTC ms tamsayı. avail_ms = verinin canlıda
kullanılabildiği an; strateji sadece avail_ms <= mum kapanışı olan satırları kullanır:
- Binance /futures/data: ts_ms + period_ms + safety_ms (varsayılan 60 sn; deterministik,
  canlıda ve geçmiş doldurmada aynı)
- WEEX anlık görüntüler (premium, OI): recv_ms
- WEEX funding geçmişi: funding_ms
- Likidasyon 1 dk kovaları: kova sonu (bucket_ms + 60000)

Likidasyon kovaları seyrektir: bn_liq_1m'de sadece likidasyon olan (sembol, dakika)
satırları vardır. Her dakikanın WS kapsaması bn_liq_coverage_1m'dedir: satır yok ama
kapsama > 0 ise o dakika likidasyon 0'dır; kapsama yoksa veri yoktur (NaN, 0 değil).
Likidasyon akışı alt sınırdır: Binance sembol başına saniyede en fazla 1 emir yollar.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

MIN_MS = 60_000
DAY_MS = 86_400_000
ALL = "*"  # kaynak genelindeki boşluklar için sembol (UNIQUE'te NULL tekrar eder)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS symbol_map(
    weex_symbol TEXT PRIMARY KEY,
    weex_base TEXT NOT NULL,
    ft_pair TEXT NOT NULL,
    binance_symbol TEXT,
    multiplier REAL NOT NULL DEFAULT 1,
    method TEXT NOT NULL,
    price_ratio REAL,
    binance_onboard_ms INTEGER,
    verified_ms INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    quote_volume REAL,
    rank INTEGER,
    last_top_ms INTEGER
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bn_futures_data(
    symbol TEXT NOT NULL, period TEXT NOT NULL, ts_ms INTEGER NOT NULL,
    oi_qty REAL, oi_value REAL, cmc_supply REAL,
    gl_ratio REAL, gl_long REAL, gl_short REAL,
    ta_ratio REAL, ta_long REAL, ta_short REAL,
    tp_ratio REAL, tp_long REAL, tp_short REAL,
    tk_ratio REAL, tk_buy_vol REAL, tk_sell_vol REAL,
    avail_ms INTEGER NOT NULL,
    first_seen_ms INTEGER,
    updated_ms INTEGER NOT NULL,
    PRIMARY KEY(symbol, period, ts_ms)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_bnfd_avail ON bn_futures_data(symbol, period, avail_ms);
CREATE TABLE IF NOT EXISTS bn_liquidations(
    symbol TEXT NOT NULL, trade_ms INTEGER NOT NULL, side TEXT NOT NULL, price REAL NOT NULL, qty REAL NOT NULL,
    event_ms INTEGER NOT NULL, avg_price REAL, last_qty REAL, filled_qty REAL, status TEXT,
    order_type TEXT, tif TEXT, ps TEXT, st INTEGER, notional REAL, recv_ms INTEGER NOT NULL, conn_id INTEGER,
    PRIMARY KEY(symbol, trade_ms, side, price, qty)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_bnliq_trade ON bn_liquidations(trade_ms);
CREATE TABLE IF NOT EXISTS bn_liq_1m(
    symbol TEXT NOT NULL, bucket_ms INTEGER NOT NULL,
    long_liq_usd REAL NOT NULL, short_liq_usd REAL NOT NULL, n_long INTEGER NOT NULL, n_short INTEGER NOT NULL,
    max_usd REAL, coverage REAL NOT NULL, avail_ms INTEGER NOT NULL,
    PRIMARY KEY(symbol, bucket_ms)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS bn_liq_coverage_1m(
    bucket_ms INTEGER PRIMARY KEY, coverage REAL NOT NULL, avail_ms INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS weex_premium(
    symbol TEXT NOT NULL, bucket_ms INTEGER NOT NULL, server_ms INTEGER, recv_ms INTEGER NOT NULL,
    mark REAL, idx REAL, last_funding REAL, forecast_funding REAL, interest_rate REAL,
    next_funding_ms INTEGER, collect_cycle_min INTEGER, avail_ms INTEGER NOT NULL,
    PRIMARY KEY(symbol, bucket_ms)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS weex_funding_hist(
    symbol TEXT NOT NULL, funding_ms INTEGER NOT NULL, rate REAL, mark REAL, recv_ms INTEGER,
    avail_ms INTEGER NOT NULL,
    PRIMARY KEY(symbol, funding_ms)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS weex_oi(
    symbol TEXT NOT NULL, bucket_ms INTEGER NOT NULL, server_ms INTEGER, recv_ms INTEGER NOT NULL,
    oi_raw REAL, mark REAL, avail_ms INTEGER NOT NULL,
    PRIMARY KEY(symbol, bucket_ms)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS ws_sessions(
    conn_id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, open_ms INTEGER NOT NULL, close_ms INTEGER,
    reason TEXT, run_id INTEGER
);
CREATE TABLE IF NOT EXISTS heartbeat(
    component TEXT PRIMARY KEY, last_ok_ms INTEGER, last_err_ms INTEGER, last_err TEXT,
    consecutive_fail INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS gaps(
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT '*',
    start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL, reason TEXT, detected_ms INTEGER NOT NULL,
    state TEXT NOT NULL,
    UNIQUE(source, symbol, start_ms)
);
CREATE TABLE IF NOT EXISTS fetch_log(
    ts_ms INTEGER NOT NULL, endpoint TEXT, symbol TEXT, http INTEGER, ms INTEGER, rows INTEGER,
    used_weight INTEGER, low INTEGER
);
CREATE INDEX IF NOT EXISTS ix_fetch_log_ts ON fetch_log(ts_ms);
"""

# Binance /futures/data uç noktası -> {sütun: ham alan}. İlk sütun "veri var mı" anahtarıdır.
BN_ENDPOINTS: dict[str, dict[str, str]] = {
    "openInterestHist": {"oi_qty": "sumOpenInterest", "oi_value": "sumOpenInterestValue",
                         "cmc_supply": "CMCCirculatingSupply"},
    "globalLongShortAccountRatio": {"gl_ratio": "longShortRatio", "gl_long": "longAccount",
                                    "gl_short": "shortAccount"},
    "topLongShortAccountRatio": {"ta_ratio": "longShortRatio", "ta_long": "longAccount",
                                 "ta_short": "shortAccount"},
    "topLongShortPositionRatio": {"tp_ratio": "longShortRatio", "tp_long": "longAccount",
                                  "tp_short": "shortAccount"},
    # Bu cevapta "symbol" alanı yok: sembol istekten eklenir.
    "takerlongshortRatio": {"tk_ratio": "buySellRatio", "tk_buy_vol": "buyVol", "tk_sell_vol": "sellVol"},
}

PERIOD_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
             "4h": 14_400_000, "6h": 21_600_000, "12h": 43_200_000, "1d": 86_400_000}


def to_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def bn_avail_ms(ts_ms: int, period_ms: int, safety_ms: int) -> int:
    return ts_ms + period_ms + safety_ms


def parse_bn_rows(endpoint: str, symbol: str, raw: Any) -> list[tuple[int, dict[str, float | None]]]:
    """Ham /futures/data satırları -> [(ts_ms, {sütun: değer})]. Başka sembolün satırı atlanır."""
    mapping = BN_ENDPOINTS[endpoint]
    out = []
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        if row.get("symbol") not in (None, symbol):
            continue
        ts = to_int(row.get("timestamp"))
        if ts is None:
            continue
        out.append((ts, {col: to_float(row.get(field)) for col, field in mapping.items()}))
    return out


def coverage_per_bucket(intervals: Iterable[tuple[int, int]], start_ms: int, end_ms: int,
                        step_ms: int = MIN_MS) -> dict[int, float]:
    """Bağlantı aralıklarının birleşimi, her kovanın ne kadarını kaplıyor (0..1)."""
    merged: list[list[int]] = []
    for a, b in sorted(intervals):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    result = {}
    for bucket in range(start_ms, end_ms, step_ms):
        lo, hi = bucket, bucket + step_ms
        covered = sum(max(0, min(b, hi) - max(a, lo)) for a, b in merged)
        result[bucket] = round(covered / step_ms, 4)
    return result


class DerivsDB:
    """Tek yazar. Tek asyncio iş parçacığından kullanılır."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.create_schema()

    def create_schema(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)
            self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', '1')")

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # pragma: no cover - kapanışta önemsiz
            pass

    def query(self, sql: str, args: tuple = ()) -> list[tuple]:
        return self.conn.execute(sql, args).fetchall()

    # --- genel upsert -------------------------------------------------------

    def _upsert(self, table: str, pk: tuple[str, ...], rows: list[dict]) -> int:
        if not rows:
            return 0
        cols = list(rows[0].keys())
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in pk)
        sql = (f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
               f"ON CONFLICT({', '.join(pk)}) DO UPDATE SET {updates}")
        with self.conn:
            self.conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
        return len(rows)

    # --- Binance /futures/data ---------------------------------------------

    def upsert_bn_futures(self, endpoint: str, symbol: str, period: str, raw: Any, *, now_ms: int,
                          safety_ms: int, live: bool) -> list[int]:
        """Sadece bu uç noktanın sütunlarını yazar (diğer uçların değerleri korunur).
        first_seen_ms sadece canlı sorguda ve yeni satırlarda yazılır (gecikme istatistiği).
        Döner: yazılan ts_ms listesi."""
        period_ms = PERIOD_MS[period]
        parsed = parse_bn_rows(endpoint, symbol, raw)
        if not parsed:
            return []
        cols = list(BN_ENDPOINTS[endpoint])
        sets = ", ".join(f"{c}=excluded.{c}" for c in cols)
        sql = (f"INSERT INTO bn_futures_data(symbol, period, ts_ms, {', '.join(cols)}, avail_ms, first_seen_ms,"
               f" updated_ms) VALUES (?, ?, ?, {', '.join('?' for _ in cols)}, ?, ?, ?)"
               f" ON CONFLICT(symbol, period, ts_ms) DO UPDATE SET {sets}, avail_ms=excluded.avail_ms,"
               " updated_ms=excluded.updated_ms,"
               " first_seen_ms=COALESCE(bn_futures_data.first_seen_ms, excluded.first_seen_ms)")
        args = []
        for ts, values in parsed:
            first_seen = now_ms if live and ts >= now_ms - 2 * period_ms else None
            args.append((symbol, period, ts, *[values[c] for c in cols], bn_avail_ms(ts, period_ms, safety_ms),
                         first_seen, now_ms))
        with self.conn:
            self.conn.executemany(sql, args)
        return [ts for ts, _ in parsed]

    def bn_last_ts(self, period: str) -> dict[tuple[str, str], int]:
        """{(sembol, uç nokta): en yeni ts_ms} (o uç noktanın verisi olan satırlar)."""
        out = {}
        for endpoint, mapping in BN_ENDPOINTS.items():
            key_col = next(iter(mapping))
            for symbol, ts in self.query(
                f"SELECT symbol, MAX(ts_ms) FROM bn_futures_data WHERE period=? AND {key_col} IS NOT NULL"
                " GROUP BY symbol", (period,)):
                out[(symbol, endpoint)] = ts
        return out

    # --- likidasyonlar ------------------------------------------------------

    def insert_liquidations(self, rows: list[dict]) -> int:
        """Doğal anahtar (symbol, trade_ms, side, price, qty) tekrarları yok sayar.
        Döner: yeni eklenen satır sayısı."""
        if not rows:
            return 0
        cols = list(rows[0].keys())
        before = self.conn.total_changes
        with self.conn:
            self.conn.executemany(
                f"INSERT OR IGNORE INTO bn_liquidations({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [tuple(r[c] for c in cols) for r in rows])
        return self.conn.total_changes - before

    def ws_open(self, url: str, open_ms: int, run_id: int | None = None) -> int:
        with self.conn:
            cur = self.conn.execute("INSERT INTO ws_sessions(url, open_ms, run_id) VALUES (?, ?, ?)",
                                    (url, open_ms, run_id))
        return int(cur.lastrowid)

    def ws_close(self, conn_id: int, close_ms: int, reason: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE ws_sessions SET close_ms=?, reason=? WHERE conn_id=? AND close_ms IS NULL",
                              (close_ms, reason[:200], conn_id))

    def ws_close_dangling(self, close_ms: int | None) -> int:
        """Önceki çalışmadan açık kalmış (sert kapanış) oturumları kapatır. close_ms bilinmiyorsa
        açılış anı kullanılır (kapsama abartılmaz)."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE ws_sessions SET close_ms=MAX(open_ms, COALESCE(?, open_ms)), reason='crash'"
                " WHERE close_ms IS NULL", (close_ms,))
        return cur.rowcount

    def ws_open_sessions(self) -> int:
        return self.query("SELECT COUNT(*) FROM ws_sessions WHERE close_ms IS NULL")[0][0]

    def ws_last_close_ms(self) -> int | None:
        return self.query("SELECT MAX(close_ms) FROM ws_sessions")[0][0]

    def ws_intervals(self, start_ms: int, end_ms: int, now_ms: int) -> list[tuple[int, int]]:
        return [(a, min(b, now_ms)) for a, b in self.query(
            "SELECT open_ms, COALESCE(close_ms, ?) FROM ws_sessions WHERE open_ms < ?"
            " AND (close_ms IS NULL OR close_ms > ?)", (now_ms, end_ms, start_ms))]

    def aggregate_liq_1m(self, start_ms: int, end_ms: int, now_ms: int) -> int:
        """[start_ms, end_ms) arasındaki kapanmış dakikaları yeniden hesaplar (idempotent).
        SELL = long pozisyon likide edildi, BUY = short likide edildi."""
        start_ms -= start_ms % MIN_MS
        end_ms = min(end_ms, now_ms - now_ms % MIN_MS)
        if end_ms <= start_ms:
            return 0
        cov = coverage_per_bucket(self.ws_intervals(start_ms, end_ms, now_ms), start_ms, end_ms)
        cov_rows = [{"bucket_ms": b, "coverage": c, "avail_ms": b + MIN_MS} for b, c in cov.items() if c > 0]
        self._upsert("bn_liq_coverage_1m", ("bucket_ms",), cov_rows)
        agg = self.query(
            "SELECT symbol, (trade_ms / 60000) * 60000 AS b,"
            " SUM(CASE WHEN side='SELL' THEN notional ELSE 0 END), SUM(CASE WHEN side='BUY' THEN notional ELSE 0 END),"
            " SUM(side='SELL'), SUM(side='BUY'), MAX(notional)"
            " FROM bn_liquidations WHERE trade_ms >= ? AND trade_ms < ? GROUP BY symbol, b", (start_ms, end_ms))
        rows = [{"symbol": s, "bucket_ms": b, "long_liq_usd": lu or 0.0, "short_liq_usd": su or 0.0,
                 "n_long": nl or 0, "n_short": ns or 0, "max_usd": mx, "coverage": cov.get(b, 0.0),
                 "avail_ms": b + MIN_MS} for s, b, lu, su, nl, ns, mx in agg]
        self._upsert("bn_liq_1m", ("symbol", "bucket_ms"), rows)
        return len(rows)

    # --- WEEX ---------------------------------------------------------------

    def upsert_weex_premium(self, rows: list[dict]) -> int:
        return self._upsert("weex_premium", ("symbol", "bucket_ms"), rows)

    def upsert_weex_oi(self, rows: list[dict]) -> int:
        return self._upsert("weex_oi", ("symbol", "bucket_ms"), rows)

    def upsert_weex_funding(self, rows: list[dict]) -> int:
        return self._upsert("weex_funding_hist", ("symbol", "funding_ms"), rows)

    def weex_last_funding(self) -> dict[str, int]:
        return dict(self.query("SELECT symbol, MAX(funding_ms) FROM weex_funding_hist GROUP BY symbol"))

    def max_value(self, table: str, column: str) -> int | None:
        return self.query(f"SELECT MAX({column}) FROM {table}")[0][0]

    # --- sağlık, boşluklar, istek günlüğü ----------------------------------

    def heartbeat_ok(self, component: str, now_ms: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO heartbeat(component, last_ok_ms, consecutive_fail) VALUES (?, ?, 0)"
                " ON CONFLICT(component) DO UPDATE SET last_ok_ms=excluded.last_ok_ms, consecutive_fail=0",
                (component, now_ms))

    def heartbeat_err(self, component: str, now_ms: int, err: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO heartbeat(component, last_err_ms, last_err, consecutive_fail) VALUES (?, ?, ?, 1)"
                " ON CONFLICT(component) DO UPDATE SET last_err_ms=excluded.last_err_ms,"
                " last_err=excluded.last_err, consecutive_fail=heartbeat.consecutive_fail + 1",
                (component, now_ms, err[:300]))

    def heartbeat(self, component: str) -> tuple | None:
        rows = self.query("SELECT last_ok_ms, last_err_ms, last_err, consecutive_fail FROM heartbeat"
                          " WHERE component=?", (component,))
        return rows[0] if rows else None

    def add_gap(self, source: str, symbol: str | None, start_ms: int, end_ms: int, reason: str, state: str,
                now_ms: int) -> None:
        if end_ms <= start_ms:
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO gaps(source, symbol, start_ms, end_ms, reason, detected_ms, state)"
                " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(source, symbol, start_ms) DO UPDATE SET"
                " end_ms=MAX(gaps.end_ms, excluded.end_ms), reason=excluded.reason, state=excluded.state",
                (source, symbol or ALL, start_ms, end_ms, reason, now_ms, state))

    def set_gap_state(self, source: str, symbol: str, from_state: str, to_state: str) -> int:
        with self.conn:
            cur = self.conn.execute("UPDATE gaps SET state=? WHERE source=? AND symbol=? AND state=?",
                                    (to_state, source, symbol, from_state))
        return cur.rowcount

    def gaps(self, source: str | None = None) -> list[tuple]:
        sql = "SELECT source, symbol, start_ms, end_ms, reason, state FROM gaps"
        if source:
            return self.query(sql + " WHERE source=? ORDER BY start_ms", (source,))
        return self.query(sql + " ORDER BY source, start_ms")

    def log_fetches(self, rows: list[tuple]) -> None:
        """rows: (ts_ms, endpoint, symbol, http, ms, rows, used_weight, low)"""
        if rows:
            with self.conn:
                self.conn.executemany("INSERT INTO fetch_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def prune_fetch_log(self, now_ms: int, days: float) -> int:
        with self.conn:
            cur = self.conn.execute("DELETE FROM fetch_log WHERE ts_ms < ?", (now_ms - int(days * DAY_MS),))
        return cur.rowcount

    # --- sembol eşleme ------------------------------------------------------

    def save_symbol_map(self, rows: list[dict]) -> None:
        self._upsert("symbol_map", ("weex_symbol",), rows)

    def load_symbol_map(self) -> list[dict]:
        cur = self.conn.execute("SELECT * FROM symbol_map")
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]
