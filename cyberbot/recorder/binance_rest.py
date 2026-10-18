"""Binance USDⓈ-M REST: /futures/data (OI, long/short oranları, taker) + eşleme için
exchangeInfo ve premiumIndex.

- Ham uç noktalar (https://fapi.binance.com), ham alanlar saklanır (ccxt'nin birleşik
  metodları alanları atıyor; taker cevabında sembol yok, istekten eklenir).
- Kendi hız sınırlayıcımız: /futures/data'nın ayrı IP sınırı (1000/5dk) ccxt'de yok.
  En fazla 2 istek/sn ve kayan 300 sn'de 700 istek. 429: Retry-After kadar dur.
  418 (IP yasağı): tüm Binance REST durur, izleme uyarı yollar.
- Canlı: her 5m mum sınırı + 30 sn, startTime = son kayıtlı ts, limit 500
  (kısa kesintiler kendiliğinden dolar, upsert tekrarları zararsız). +90 sn'de en yeni
  satırı gelmeyen anahtarlar bir kez daha sorulur.
- Geçmiş doldurma (ilk açılış, yeni sembol, uzun kesinti): son 29.5 gün, düşük öncelikli
  kuyruk (BTC, ETH, sonra hacim), aynı sınırlayıcı: canlı sorgu her zaman önce gider.
  Plan son ts'den değil DB'de EKSİK olan periyotlardan yapılır (açılışta ve saatte bir), böylece
  yarıda kalan doldurma (yeniden başlatma, ağ hatası) sonra devam eder. Başarılı cevap alınan
  aralık bn_backfill_checked'e yazılır (Binance'te olmayan kısım tekrar sorulmaz). Eksik
  olan her sembol için 'open' boşluk yazılır; tümü dolunca 'backfilled' olur.
  Geçici hata (ağ, 429, 418, 5xx): görev artan beklemeyle tekrar kuyruğa; deneme hakkı bitince
  bırakılır ve bir sonraki saatlik planda yeniden denenir.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from cyberbot.recorder.db import BN_ENDPOINTS, DAY_MS, PERIOD_MS, DerivsDB, to_int
from cyberbot.recorder.limiter import Clock, HttpClient, RateLimiter, retry_after_s
from cyberbot.recorder.monitor import SourceHealth, Status

logger = logging.getLogger(__name__)

ENDPOINTS = list(BN_ENDPOINTS)
SOURCE = "bn_futures"  # gaps.source


@dataclass(order=True)
class BackfillTask:
    priority: int
    seq: int
    symbol: str = field(compare=False)
    endpoint: str = field(compare=False)
    start_ms: int = field(compare=False)
    end_ms: int = field(compare=False)
    attempts: int = field(default=0, compare=False)
    not_before_ms: int = field(default=0, compare=False)
    finished: bool = field(default=False, compare=False)


def bar_open(now_ms: int, period_ms: int) -> int:
    return now_ms - now_ms % period_ms


def live_floor(bar_ms: int, period_ms: int, limit: int) -> int:
    """Canlı sorgunun kapsadığı en eski ts (son `limit` periyot)."""
    return bar_ms - (limit - 1) * period_ms


def window_start_ms(now_ms: int, period_ms: int, backfill_days: float) -> int:
    start = now_ms - int(backfill_days * DAY_MS)
    return start + (-start % period_ms)  # periyot ızgarasına yukarı yuvarla


def chunk_ranges(ranges: list[tuple[int, int]], *, period_ms: int, limit: int) -> list[tuple[int, int]]:
    """Yarı açık [a, b) aralıkları -> tek istekte sorulacak [startTime, endTime] (en fazla limit periyot)."""
    out = []
    for a, b in ranges:
        t = a
        while t < b:
            out.append((t, min(t + (limit - 1) * period_ms, b - 1)))
            t += limit * period_ms
    return out


def plan_ranges(last_ts: int | None, now_ms: int, *, period_ms: int, limit: int,
                backfill_days: float) -> list[tuple[int, int]]:
    """Son ts'den canlı pencereye kadar doldurulacak [başlangıç, bitiş] aralıkları (her biri tek istek)."""
    window_start = window_start_ms(now_ms, period_ms, backfill_days)
    floor = live_floor(bar_open(now_ms, period_ms), period_ms, limit)
    start = window_start if last_ts is None else max(window_start, last_ts + period_ms)
    return chunk_ranges([(start, floor)], period_ms=period_ms, limit=limit)


def interleave_tasks(symbols: list[str], ranges_for: Callable[[str, str], list[tuple[int, int]]], *,
                     endpoints: list[str] = ENDPOINTS, first_priority: int = 0) -> list[BackfillTask]:
    """symbols öncelik sırasında; ranges_for(sembol, uç) -> [startTime, endTime] listesi."""
    tasks = []
    seq = itertools.count()
    for rank, symbol in enumerate(symbols):
        per_endpoint = {e: ranges_for(symbol, e) for e in endpoints}
        # aynı zaman dilimi tüm uçlar için art arda: satırlar birlikte tamamlanır
        for i in range(max((len(r) for r in per_endpoint.values()), default=0)):
            for endpoint, ranges in per_endpoint.items():
                if i < len(ranges):
                    start, end = ranges[i]
                    tasks.append(BackfillTask(first_priority + rank, next(seq), symbol, endpoint, start, end))
    return tasks


def plan_backfill(symbols: list[str], last_ts: dict[tuple[str, str], int], now_ms: int, *, period_ms: int,
                  limit: int, backfill_days: float, endpoints: list[str] = ENDPOINTS,
                  first_priority: int = 0) -> list[BackfillTask]:
    """Son ts'ye göre plan (canlı turdaki uzun kesinti için). symbols öncelik sırasında."""
    return interleave_tasks(
        symbols, lambda s, e: plan_ranges(last_ts.get((s, e)), now_ms, period_ms=period_ms, limit=limit,
                                          backfill_days=backfill_days),
        endpoints=endpoints, first_priority=first_priority)


def retry_delay_s(attempt: int, cap_s: float = 600.0) -> float:
    """Geçici hatadan sonra doldurma görevinin bekleme süresi: 30, 60, 120 ... en fazla 10 dk."""
    return min(cap_s, 30.0 * 2 ** max(0, attempt - 1))


class BinanceRest:
    def __init__(self, http: HttpClient, db: DerivsDB, cfg: dict, clock: Clock, status: Status,
                 log_sink: list | None = None):
        self.http = http
        self.db = db
        self.cfg = cfg
        self.clock = clock
        self.status = status
        self.health: SourceHealth = status.binance_rest
        self.log_sink = log_sink if log_sink is not None else []
        self.base = cfg["rest_url"].rstrip("/")
        self.period = cfg["period"]
        self.period_ms = PERIOD_MS[self.period]
        self.limit = int(cfg["limit"])
        self.limiter = RateLimiter(clock, max_rps=float(cfg["max_rps"]), window_s=float(cfg["window_s"]),
                                   window_max=int(cfg["window_max"]), name="Binance REST")
        self.last_ts: dict[tuple[str, str], int] = db.bn_last_ts(self.period)
        self.queue: list[BackfillTask] = []
        self.delayed: list[BackfillTask] = []           # geçici hatadan sonra not_before_ms bekleyenler
        self._seq = itertools.count(1_000_000)
        self.pending: dict[tuple[str, str], int] = {}   # anahtar -> kuyruktaki (bekleyen dahil) görev sayısı
        self._queue_event = asyncio.Event()
        self.priority: dict[str, int] = {}
        self.open_gaps: set[str] = set(db.open_gap_symbols(SOURCE))  # 'open' boşluğu olan semboller
        self.failed: set[str] = set()        # doldurma görevi bırakılan semboller (sonraki planda tekrar)
        self.done_count = 0                  # tamamlanan doldurma görevleri (ilerleme kontrolü)
        self._done_at_plan = 0
        self._plan_ms: int | None = None

    # --- düşük seviye -------------------------------------------------------

    async def get(self, path: str, params: dict | None = None, *, low: bool = False, label: str = "",
                  symbol: str = "") -> tuple[int, Any]:
        """(http durum, veri). Ağ hatası: (0, None). Hiçbir zaman istisna fırlatmaz."""
        await self.limiter.acquire(low)
        now = self.clock.now_ms()
        try:
            resp = await self.http.get(self.base + path, params)
        except Exception as exc:  # ağ hatası, zaman aşımı
            self.health.fail(now, f"{type(exc).__name__}: {exc}"[:200])
            self.log_sink.append((now, label or path, symbol, 0, None, None, None, int(low)))
            return 0, None
        used = to_int(resp.headers.get("x-mbx-used-weight-1m"))
        rows = len(resp.data) if isinstance(resp.data, list) else None
        self.log_sink.append((now, label or path, symbol, resp.status, int(resp.ms), rows, used, int(low)))
        if resp.status == 429:
            self.limiter.pause(retry_after_s(resp.headers, float(self.cfg["rate_limit_pause_s"])), now, "HTTP 429")
            self.health.fail(now, "HTTP 429 (hız sınırı)")
            return 429, None
        if resp.status == 418:
            self.limiter.pause(retry_after_s(resp.headers, float(self.cfg["ban_pause_s"])), now, "HTTP 418")
            self.status.binance_ban_until_ms = self.limiter.paused_until_ms
            self.health.fail(now, "HTTP 418 (IP yasağı)")
            return 418, None
        if resp.status >= 500 or resp.status in (401, 403, 451):
            self.health.fail(now, f"HTTP {resp.status}")
            return resp.status, None
        self.health.ok(now)  # sunucu cevap verdi: erişim var
        if resp.status >= 400:
            logger.warning("Binance %s %s: HTTP %s %s", path, symbol, resp.status, str(resp.data)[:200])
            return resp.status, None
        return resp.status, resp.data

    async def exchange_info(self) -> Any:
        status, data = await self.get("/fapi/v1/exchangeInfo", label="exchangeInfo")
        return data if status == 200 else None

    async def premium_index(self) -> Any:
        status, data = await self.get("/fapi/v1/premiumIndex", label="premiumIndex")
        return data if status == 200 else None

    def _store(self, endpoint: str, symbol: str, data: Any, live: bool) -> list[int]:
        ts = self.db.upsert_bn_futures(endpoint, symbol, self.period, data, now_ms=self.clock.now_ms(),
                                       safety_ms=int(self.cfg["safety_ms"]), live=live)
        if ts:
            key = (symbol, endpoint)
            self.last_ts[key] = max(self.last_ts.get(key, 0), max(ts))
        return ts

    # --- canlı --------------------------------------------------------------

    async def poll_live(self, symbol: str, endpoint: str, bar_ms: int) -> bool:
        """True: en yeni beklenen satır (ts >= bar - period) geldi."""
        if self.limiter.paused(self.clock.now_ms()):  # tur ortasında 418/429: yasak bitene kadar bekleme
            return False
        key = (symbol, endpoint)
        floor = live_floor(bar_ms, self.period_ms, self.limit)
        last = self.last_ts.get(key)
        if last is not None and last < floor - self.period_ms and key not in self.pending:
            # canlı pencereden (500 periyot) uzun kesinti: aradaki kısım doldurma kuyruğuna
            self.db.open_gap(SOURCE, symbol, last + self.period_ms, floor, "outage", self.clock.now_ms())
            self.open_gaps.add(symbol)
            if self.cfg.get("backfill", True):
                self.enqueue(plan_backfill([symbol], {key: last}, bar_ms, period_ms=self.period_ms,
                                           limit=self.limit, backfill_days=float(self.cfg["backfill_days"]),
                                           endpoints=[endpoint], first_priority=self.priority.get(symbol, 999)))
        start = floor if last is None else max(last, floor)
        status, data = await self.get(f"/futures/data/{endpoint}",
                                      {"symbol": symbol, "period": self.period, "startTime": start,
                                       "limit": self.limit}, label=endpoint, symbol=symbol)
        if status != 200:
            return False
        self._store(endpoint, symbol, data, live=True)
        self._maybe_close_gap(symbol)
        return self.last_ts.get(key, 0) >= bar_ms - self.period_ms

    async def live_cycle(self, bar_ms: int, symbols: list[str], retry_at_ms: int) -> dict:
        """Tüm sembol x uç nokta; retry_at_ms'de eksikler bir kez daha."""
        if self.limiter.paused(self.clock.now_ms()):  # 418/429: bu tur atlanır; sonra startTime ile dolar
            logger.info("Binance istekleri durdurulmuş (%s); %s turu atlandı", self.limiter.pause_reason, bar_ms)
            return {"requests": 0, "missing": 0, "still_missing": 0, "skipped": True}
        missing = []
        with self.limiter.high_section():
            for symbol in symbols:
                for endpoint in ENDPOINTS:
                    if not await self.poll_live(symbol, endpoint, bar_ms):
                        missing.append((symbol, endpoint))
        wait_s = (retry_at_ms - self.clock.now_ms()) / 1000
        if missing and wait_s > 0:
            await self.clock.sleep(wait_s)
        still = []
        if missing:
            with self.limiter.high_section():
                for symbol, endpoint in missing:
                    if not await self.poll_live(symbol, endpoint, bar_ms):
                        still.append((symbol, endpoint))
        if still:
            logger.info("Binance %s mumu: %d anahtar hâlâ eksik (ör. %s)", bar_ms, len(still), still[:3])
        return {"requests": len(symbols) * len(ENDPOINTS) + len(missing), "missing": len(missing),
                "still_missing": len(still)}

    # --- boşluklar ----------------------------------------------------------

    def record_startup_gaps(self, symbols: list[str], now_ms: int) -> None:
        """Kaydedici kapalıyken kaçan Binance verisi: son 29.5 gün içindeki kısım 'open'
        (doldurulunca 'backfilled'; sembolün açık boşluğu varsa o genişler), daha eskisi
        'unrecoverable'. Yeni sembolün geçmişi plan() içinde 'open' boşluk olarak yazılır."""
        bar = bar_open(now_ms, self.period_ms)
        window_start = now_ms - int(float(self.cfg["backfill_days"]) * DAY_MS)
        for symbol in symbols:
            known = [t for e in ENDPOINTS if (t := self.last_ts.get((symbol, e))) is not None]
            if not known:
                continue
            last = min(known)
            if bar - last <= 2 * self.period_ms:
                continue
            start = last + self.period_ms
            if start < window_start:
                self.db.add_gap(SOURCE, symbol, start, window_start, "downtime", "unrecoverable", now_ms)
                start = window_start
            self.db.open_gap(SOURCE, symbol, start, bar, "downtime", now_ms)
            self.open_gaps.add(symbol)

    def _maybe_close_gap(self, symbol: str) -> None:
        if symbol not in self.open_gaps or symbol in self.failed:
            return
        if any((symbol, e) in self.pending for e in ENDPOINTS):
            return
        need = bar_open(self.clock.now_ms(), self.period_ms) - 2 * self.period_ms
        if all(self.last_ts.get((symbol, e), 0) >= need for e in ENDPOINTS):
            if self.db.set_gap_state(SOURCE, symbol, "open", "backfilled"):
                logger.info("Binance %s boşluğu dolduruldu", symbol)
            self.open_gaps.discard(symbol)

    # --- geçmiş doldurma ----------------------------------------------------

    def set_priority(self, symbols_in_order: list[str]) -> None:
        self.priority = {s: i for i, s in enumerate(symbols_in_order)}

    def set_low_cap(self, n_symbols: int) -> None:
        """Pencerenin canlı tura yetecek kısmı ayrılır; kalanını doldurma kullanır."""
        live = len(ENDPOINTS) * n_symbols
        reserve = min(self.limiter.window_max - 50, int(live * 1.3) + 10)
        self.limiter.low_cap = max(0, self.limiter.window_max - reserve)

    def plan(self, symbols_in_order: list[str], now_ms: int) -> int:
        """DB'de eksik olan (ve kuyrukta olmayan) periyotlar için doldurma görevleri ekler.
        Açılışta ve saatte bir çağrılır; yarıda kalan doldurma böylece devam eder."""
        if not self.cfg.get("backfill", True):
            return 0
        self._check_progress(now_ms)
        self.failed.clear()  # bırakılan görevler bu planda yeniden denenir
        window_start = window_start_ms(now_ms, self.period_ms, float(self.cfg["backfill_days"]))
        floor = live_floor(bar_open(now_ms, self.period_ms), self.period_ms, self.limit)
        self.db.prune_backfill_checked(window_start - DAY_MS)
        missing: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for endpoint in ENDPOINTS:
            free = [s for s in symbols_in_order if (s, endpoint) not in self.pending]
            for symbol, ranges in self.db.bn_missing(endpoint, self.period, free, window_start, floor).items():
                missing[(symbol, endpoint)] = ranges
        tasks = interleave_tasks(symbols_in_order, lambda s, e: chunk_ranges(missing.get((s, e), []),
                                                                             period_ms=self.period_ms,
                                                                             limit=self.limit))
        for t in tasks:
            t.priority = self.priority.get(t.symbol, t.priority)
        for symbol in symbols_in_order:
            ranges = [r for e in ENDPOINTS for r in missing.get((symbol, e), [])]
            if ranges:
                history = all(self.last_ts.get((symbol, e)) is None for e in ENDPOINTS)
                self.db.open_gap(SOURCE, symbol, min(a for a, _ in ranges), max(b for _, b in ranges),
                                 "history" if history else "missing", now_ms)
                self.open_gaps.add(symbol)
        self.enqueue(tasks)
        return len(tasks)

    def _check_progress(self, now_ms: int) -> None:
        """Saatlik planda: kuyrukta iş varken son plandan beri hiç görev bitmediyse uyarır."""
        waiting = len(self.queue) + len(self.delayed)
        done = self.done_count - self._done_at_plan
        if self._plan_ms is not None and waiting and now_ms - self._plan_ms >= 30 * 60_000:
            if done == 0:
                logger.warning("Binance geçmiş doldurma ilerlemiyor: %d istek bekliyor, son %d dakikada hiçbiri"
                               " tamamlanmadı (hız sınırı/erişim?)", waiting, (now_ms - self._plan_ms) // 60_000)
            else:
                logger.info("Binance geçmiş doldurma: son planda beri %d istek tamamlandı, %d bekliyor", done,
                            waiting)
        self._plan_ms, self._done_at_plan = now_ms, self.done_count

    def enqueue(self, tasks: list[BackfillTask]) -> None:
        for t in tasks:
            t.seq = next(self._seq)
            heapq.heappush(self.queue, t)
            key = (t.symbol, t.endpoint)
            self.pending[key] = self.pending.get(key, 0) + 1
        if tasks:
            self._queue_event.set()

    def _task_done(self, task: BackfillTask, ok: bool) -> None:
        if task.finished:
            return
        task.finished = True
        key = (task.symbol, task.endpoint)
        if ok:
            self.done_count += 1
        else:
            self.failed.add(task.symbol)
        self.pending[key] -= 1
        if self.pending[key] <= 0:
            del self.pending[key]
            self._maybe_close_gap(task.symbol)

    def _release_delayed(self, now_ms: int) -> None:
        ready = [t for t in self.delayed if t.not_before_ms <= now_ms]
        if ready:
            self.delayed = [t for t in self.delayed if t.not_before_ms > now_ms]
            for t in ready:
                heapq.heappush(self.queue, t)

    async def backfill_once(self) -> bool:
        """Kuyruktan bir görev işler. Şu an işlenecek görev yoksa False (bekleyenler sonra döner)."""
        self._release_delayed(self.clock.now_ms())
        if not self.queue:
            return False
        task = heapq.heappop(self.queue)
        try:
            await self._run_task(task)
        except Exception:  # ör. DB hatası: görev kaybolmasın, anahtar sonraki planda tekrar planlanır
            self._task_done(task, False)
            raise
        return True

    async def _run_task(self, task: BackfillTask) -> None:
        status, data = await self.get(
            f"/futures/data/{task.endpoint}",
            {"symbol": task.symbol, "period": self.period, "startTime": task.start_ms, "endTime": task.end_ms,
             "limit": self.limit}, low=True, label=task.endpoint, symbol=task.symbol)
        if status == 200:
            self._store(task.endpoint, task.symbol, data, live=False)
            # sorulan aralık (periyot ızgarasında yarı açık) bitti: gelmeyen periyotlar Binance'te yok
            end = task.end_ms - task.end_ms % self.period_ms + self.period_ms
            self.db.bn_mark_checked(task.symbol, task.endpoint, task.start_ms, end, self.clock.now_ms())
            self._task_done(task, True)
        elif (status in (0, 429, 418) or status >= 500) and task.attempts + 1 < int(self.cfg["backfill_attempts"]):
            task.attempts += 1
            task.not_before_ms = self.clock.now_ms() + int(retry_delay_s(task.attempts) * 1000)
            self.delayed.append(task)  # hemen değil, artan beklemeyle tekrar
        else:
            logger.warning("Binance doldurma bırakıldı (sonraki saatlik planda tekrar): %s %s %s HTTP %s",
                           task.symbol, task.endpoint, task.start_ms, status)
            self._task_done(task, False)

    async def backfill_worker(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                if not await self.backfill_once():
                    self._queue_event.clear()
                    try:
                        await asyncio.wait_for(self._queue_event.wait(), timeout=5)
                    except TimeoutError:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:  # bir görev hatası işçiyi düşürmesin
                logger.exception("Binance doldurma hatası")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=5)
