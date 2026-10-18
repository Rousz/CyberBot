"""Kaydedici servisi: zamanlayıcı + kaynaklar + izleme (tek asyncio süreci).

İşler (job) ve zamanları:
- symbols      : açılışta ve saatte bir (WEEX exchangeInfo + ticker/24hr, Binance exchangeInfo + premiumIndex)
- weex_premium : her dakika + 2 sn
- weex_oi      : her 5m mum kapanışından 30 sn önce
- weex_funding : açılışta bir kez ve her ödemeden (nextFundingTime) 2 dk sonra
- bn_live      : her 5m mum sınırı + 30 sn (eksikler + 90 sn'de tekrar)
- liq_agg      : her dakika + 5 sn (son 5 dakikanın 1 dk kovaları yeniden hesaplanır)
- monitor      : 30 sn'de bir
- maintenance  : saatte bir (fetch_log 7 günden eski satırlar silinir)
Arka planda: Binance likidasyon WS'i ve Binance geçmiş doldurma işçisi.
Bir kaynağın hatası diğerlerini durdurmaz; her iş kendi hatasını yakalar. Arka plan işleri
hata verip biterse artan beklemeyle (5, 10, 20 ... 300 sn) yeniden başlatılır. Bir iş üst üste
task_alert_failures kez hata verirse izleme Telegram'a yazar (Status.jobs).
Kaydedicinin uptime kalp atışı sadece ana döngü (tick) son 5 dakikada ilerlediyse yazılır.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any, Callable

from cyberbot import __version__, paths
from cyberbot.recorder import binance_rest, symbols
from cyberbot.recorder.binance_rest import BinanceRest
from cyberbot.recorder.binance_ws import LiquidationStream
from cyberbot.recorder.db import ALL, MIN_MS, PERIOD_MS, DerivsDB
from cyberbot.recorder.limiter import AiohttpClient, Clock, HttpClient, RealClock
from cyberbot.recorder.monitor import Monitor, Status
from cyberbot.recorder.symbols import SymbolMapping
from cyberbot.recorder.weex_poll import BAR_MS, FundingSchedule, WeexRest, oi_due_ms, parse_funding, parse_oi, \
    parse_premium
from cyberbot.uptime import Heartbeat, UptimeStore

logger = logging.getLogger(__name__)

LIQ_REAGG_MS = 5 * MIN_MS
MAX_BUFFER = 100_000
LOOP_ALIVE_MS = 5 * MIN_MS


def next_aligned(now_ms: int, step_ms: int, offset_ms: int) -> int:
    """now'dan sonraki ilk k*step + offset."""
    t = now_ms - now_ms % step_ms + offset_ms
    while t <= now_ms:
        t += step_ms
    return t


class GapTracker:
    """Geri getirilemeyen kaynaklar (WEEX premium/OI) için: ardışık başarılı kovalar
    arasında atlanan kova varsa gaps'e 'unrecoverable' yazar. Açılışta DB'deki son kovadan
    başlar, böylece kaydedicinin kapalı kaldığı süre de boşluk olarak yazılır."""

    def __init__(self, db: DerivsDB, source: str, step_ms: int, last_bucket: int | None):
        self.db = db
        self.source = source
        self.step_ms = step_ms
        self.last = last_bucket

    def ok(self, bucket_ms: int, now_ms: int) -> None:
        if self.last is not None and bucket_ms - self.last >= 2 * self.step_ms:
            self.db.add_gap(self.source, ALL, self.last + self.step_ms, bucket_ms, "missed", "unrecoverable", now_ms)
        self.last = bucket_ms if self.last is None else max(self.last, bucket_ms)


def mapping_from_row(row: dict) -> SymbolMapping:
    return SymbolMapping(row["weex_symbol"], row["weex_base"], row["ft_pair"], row["binance_symbol"],
                         row["multiplier"], row["method"], row["price_ratio"], row["binance_onboard_ms"],
                         row.get("note") or "")


class Recorder:
    def __init__(self, cfg: dict, mon_cfg: dict, *, clock: Clock | None = None, http_binance: HttpClient | None = None,
                 http_weex: HttpClient | None = None, ws_connect: Callable | None = None, notifier: Any = None,
                 send: Callable | None = None, db_path: str | Path | None = None,
                 uptime_path: str | Path | None = None, perps_json_path: str | Path | None = None):
        self.cfg = cfg
        self.mon_cfg = mon_cfg
        self.bcfg = cfg["binance"]
        self.wcfg = cfg["weex"]
        self.scfg = cfg["symbols"]
        self.clock = clock or RealClock()
        timeout = float(cfg["http_timeout_s"])
        self.http_binance = http_binance or AiohttpClient(timeout)
        self.http_weex = http_weex or AiohttpClient(timeout)
        self.ws_connect = ws_connect
        self.perps_json_path = Path(perps_json_path or paths.binance_perps_json())
        self.db = DerivsDB(db_path or paths.derivs_db())
        self.status = Status()
        self.status.attach_db(self.db)
        self.fetch_log: list[tuple] = []
        self.liq_buffer: list[dict] = []
        self.weex = WeexRest(self.http_weex, self.wcfg, self.clock, self.status, self.fetch_log)
        self.binance = BinanceRest(self.http_binance, self.db, self.bcfg, self.clock, self.status, self.fetch_log)
        uptime_path = uptime_path or paths.uptime_db()
        self.uptime = UptimeStore(uptime_path, "recorder")
        self.bot_store = UptimeStore(uptime_path, "freqtrade")
        self.notifier = notifier
        self.send = send
        self.monitor: Monitor | None = None
        self.funding = FundingSchedule(int(float(self.wcfg["funding_delay_s"]) * 1000))
        self.premium_gaps = GapTracker(self.db, "weex_premium", MIN_MS, self.db.max_value("weex_premium", "bucket_ms"))
        self.oi_gaps = GapTracker(self.db, "weex_oi", BAR_MS, self.db.max_value("weex_oi", "bucket_ms"))
        self.tracked: list[str] = []                 # WEEX sembolleri, öncelik sırasıyla
        self.mappings: dict[str, SymbolMapping] = {}
        self.latest_premium: list | None = None
        self.weex_marks: dict[str, float] = {}
        self.due: dict[str, int] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.background: list[asyncio.Task] = []
        self.stop_event = asyncio.Event()
        self.session_id: int | None = None
        self.heartbeat: Heartbeat | None = None
        self.started_ms = 0
        self.ws: LiquidationStream | None = None
        self._funding_due: list[str] = []
        self._weex_snapshot: tuple[int, Any, Any] | None = None
        self._closed = False
        self._last_tick_ms = 0

    # --- yardımcı -----------------------------------------------------------

    @property
    def binance_on(self) -> bool:
        return bool(self.bcfg.get("enabled", True))

    @property
    def weex_on(self) -> bool:
        return bool(self.wcfg.get("enabled", True))

    def binance_symbols(self) -> list[str]:
        out = []
        for w in self.tracked:
            m = self.mappings.get(w)
            if m and m.binance_symbol and m.binance_symbol not in out:
                out.append(m.binance_symbol)
        return out

    def request_stop(self) -> None:
        self.stop_event.set()

    # --- açılış -------------------------------------------------------------

    async def start(self, *, background: bool = True, heartbeat: bool = True) -> None:
        now = self.clock.now_ms()
        self.started_ms = self._last_tick_ms = now
        self.session_id = self.uptime.start_session(version=__version__, detail="derivs recorder", at_ms=now)
        if heartbeat:
            self.heartbeat = Heartbeat(self.uptime, self.session_id, is_alive=self.loop_alive,
                                       version=__version__).start()
        hb = self.db.heartbeat("binance_ws")
        closed = self.db.ws_close_dangling(hb[0] if hb else None)
        if closed:
            logger.info("Önceki çalışmadan açık kalan %d WS oturumu kapatıldı", closed)
        self.monitor = Monitor(self.mon_cfg, status=self.status, notifier=self.notifier, events=self.uptime,
                               bot_store=self.bot_store, started_ms=now, binance_enabled=self.binance_on,
                               weex_enabled=self.weex_on, send=self.send)
        for row in self.db.load_symbol_map():  # önceki çalışmanın eşlemesi (yedek)
            self.mappings[row["weex_symbol"]] = mapping_from_row(row)
        prev_active = sorted(r["weex_symbol"] for r in self.db.load_symbol_map() if r["active"])
        self.tracked = prev_active or list(self.scfg["always_track"])
        try:
            ok = await self.refresh_symbols()
        except Exception:  # açılış hatası kaydediciyi düşürmesin: sembol işi sonra tekrar dener
            logger.exception("Açılışta sembol listesi yenilenemedi")
            ok = False
        now = self.clock.now_ms()
        if self.binance_on:
            self.binance.set_priority(self.binance_symbols())
            self.binance.set_low_cap(len(self.binance_symbols()))
            try:
                self.binance.record_startup_gaps(self.binance_symbols(), now)
                n = self.binance.plan(self.binance_symbols(), now)
            except Exception:
                logger.exception("Binance geçmiş doldurma planlanamadı (saatlik yenilemede tekrar)")
                n = 0
            if n:
                logger.info("Binance geçmiş doldurma: %d istek kuyrukta (öncelik BTC, ETH, hacim)", n)
        period_ms = PERIOD_MS[self.bcfg["period"]]
        self.due = {
            "symbols": now + int(float(self.scfg["refresh_s" if ok else "retry_s"]) * 1000),
            "weex_premium": next_aligned(now, MIN_MS, int(float(self.wcfg["premium_offset_s"]) * 1000)),
            "weex_oi": oi_due_ms(now, float(self.wcfg["oi_lead_s"])),
            "bn_live": next_aligned(now, period_ms, int(float(self.bcfg["poll_offset_s"]) * 1000)),
            "liq_agg": next_aligned(now, MIN_MS, 5_000),
            "monitor": now + int(float(self.mon_cfg["check_interval_s"]) * 1000),
            "maintenance": now,
        }
        if not self.weex_on:
            for name in ("weex_premium", "weex_oi"):
                self.due.pop(name)
        if not self.binance_on:
            for name in ("bn_live", "liq_agg"):
                self.due.pop(name)
        if background:
            self.start_background()
        logger.info("Kaydedici başladı: %d WEEX sembolü, %d Binance sembolü izleniyor", len(self.tracked),
                    len(self.binance_symbols()))

    def loop_alive(self) -> bool:
        """Uptime kalp atışı için: ana döngü son 5 dakikada ilerledi mi."""
        return self.clock.now_ms() - self._last_tick_ms <= LOOP_ALIVE_MS

    def start_background(self, *, ws: bool = True, backfill: bool = True) -> None:
        if self.binance_on and ws:
            self.ws = LiquidationStream(self.bcfg["ws_url"], self.db, self.clock, self.bcfg, self.status,
                                        self.liq_buffer.extend, connect=self.ws_connect, run_id=self.session_id)
            self.background.append(asyncio.create_task(
                self._supervise("binance_ws", lambda: self.ws.run(self.stop_event), on_error=self._ws_failed),
                name="binance_ws"))
        if self.binance_on and backfill:
            self.background.append(asyncio.create_task(
                self._supervise("backfill", lambda: self.binance.backfill_worker(self.stop_event)), name="backfill"))

    def _ws_failed(self) -> None:
        """WS işi hatayla bitti: izleme kopukluğu görsün, açık kalan oturum kapsama saymasın."""
        now = self.clock.now_ms()
        if self.status.ws_down_since_ms is None:
            self.status.ws_down_since_ms = now
        try:
            self.db.ws_close_dangling(now, reason="error")
        except Exception as exc:
            logger.warning("WS oturumları kapatılamadı: %s", exc)

    async def _sleep_or_stop(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stop_event.wait(), timeout=max(0.0, seconds))

    async def _supervise(self, name: str, factory: Callable[[], Any], on_error: Callable[[], None] | None = None):
        """Arka plan işini çalıştırır; hata verip biterse (veya beklenmedik şekilde biterse) artan
        beklemeyle yeniden başlatır. task_stable_s hatasız çalışınca iş sağlıklı sayılır."""
        base = float(self.cfg.get("task_restart_base_s", 5))
        cap = float(self.cfg.get("task_restart_max_s", 300))
        stable_s = float(self.cfg.get("task_stable_s", 120))
        while not self.stop_event.is_set():
            task = asyncio.ensure_future(factory())
            try:
                done, _ = await asyncio.wait({task}, timeout=stable_s)
                if not done:
                    self.status.job_ok(name, self.clock.now_ms())
                    await task
                else:
                    task.result()
                if self.stop_event.is_set():
                    return
                raise RuntimeError("iş beklenmedik şekilde bitti")
            except asyncio.CancelledError:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task
                raise
            except Exception as exc:
                now = self.clock.now_ms()
                n = self.status.job_fail(name, now, f"{type(exc).__name__}: {exc}")
                logger.exception("'%s' işi hata verdi (%d. kez üst üste); yeniden başlatılacak", name, n)
                with contextlib.suppress(Exception):
                    self.db.heartbeat_err(name, now, f"{type(exc).__name__}: {exc}")
                if on_error is not None:
                    with contextlib.suppress(Exception):
                        on_error()
                await self._sleep_or_stop(min(cap, base * 2 ** (n - 1)))

    # --- işler --------------------------------------------------------------

    async def refresh_symbols(self) -> bool:
        """İzlenen semboller + Binance eşlemesi. Başarısızsa önceki liste korunur."""
        if not self.weex_on:
            return False
        now = self.clock.now_ms()
        snap = self._weex_snapshot
        if snap is None or now - snap[0] >= (float(self.scfg["refresh_s"]) - 60) * 1000:
            # ticker/24hr pahalı (WEEX ağırlığı 40): saatte en fazla bir kez; sadece Binance
            # eşlemesi tekrar deneniyorsa önceki WEEX görüntüsü kullanılır.
            info = await self.weex.exchange_info()
            tickers = await self.weex.ticker_24hr() if info is not None else None
            if info is None or tickers is None:
                logger.warning("Sembol listesi yenilenemedi (WEEX); önceki liste kullanılıyor (%d sembol)",
                               len(self.tracked))
                return False
            snap = self._weex_snapshot = (now, info, tickers)
        info, tickers = snap[1], snap[2]
        perps = symbols.weex_usdt_perps(info)
        regexes = list(self.scfg["exclude_regexes"])
        ranked = symbols.rank_by_volume(tickers, perps, regexes)
        volume = dict(ranked)
        rows_prev = {r["weex_symbol"]: r for r in self.db.load_symbol_map()}
        prev_top = {s: r["last_top_ms"] for s, r in rows_prev.items() if r["active"]}
        always = list(self.scfg["always_track"])
        tracked = symbols.select_tracked(ranked, prev_top, now, top_n=int(self.scfg["track_top_n"]),
                                         keep_hours=float(self.scfg["keep_hours"]), always=always,
                                         available=set(perps))
        order = symbols.priority_order(tracked, ranked, always)
        if self.latest_premium is None:
            await self.poll_premium(tracked_override=order)
        self.weex_marks = symbols.marks(self.latest_premium)

        fresh = False
        if self.binance_on and self.binance.limiter.paused(now):
            logger.warning("Binance istekleri durdurulmuş (%s); eşleme sonra yenilenecek",
                           self.binance.limiter.pause_reason)
        elif self.binance_on:
            bn_info = await self.binance.exchange_info()
            bn_prem = await self.binance.premium_index() if bn_info is not None else None
            if not self.weex_marks:  # WEEX fiyatı yok: doğrulanamaz, eski eşleme/dosya korunur
                logger.warning("WEEX fiyatları alınamadı; Binance eşlemesi yenilenmedi")
            elif bn_info is not None and bn_prem is not None:
                self.mappings = symbols.map_all(perps, self.weex_marks, symbols.binance_usdt_perps(bn_info),
                                                symbols.marks(bn_prem), tolerance=float(self.scfg["price_tolerance"]),
                                                overrides=self.scfg.get("overrides") or {})
                fresh = True
            else:
                logger.warning("Binance eşlemesi yenilenemedi; önceki eşleme kullanılıyor")
        for sym, base in perps.items():  # Binance kapalı/erişilemez: eşlemesiz kayıt
            if sym not in self.mappings:
                self.mappings[sym] = SymbolMapping(sym, base, symbols.ft_pair(base), None, 1.0, "none", None, None,
                                                   "unverified")
        rank = {s: i + 1 for i, (s, _) in enumerate(ranked)}
        rows = []
        for sym in perps:
            m = self.mappings[sym]
            prev = rows_prev.get(sym, {})
            rows.append({**m.as_dict(), "verified_ms": now if fresh else (prev.get("verified_ms") or now),
                         "active": int(sym in tracked), "quote_volume": volume.get(sym),
                         "rank": rank.get(sym), "last_top_ms": tracked.get(sym, prev.get("last_top_ms"))})
        self.db.save_symbol_map(rows)
        if fresh:
            symbols.write_json_atomic(self.perps_json_path, symbols.perps_json(
                {s: self.mappings[s] for s in perps}, now))
        self.tracked = order
        if self.binance_on:
            bn = self.binance_symbols()
            self.binance.set_priority(bn)
            self.binance.set_low_cap(len(bn))
            if self.due:  # açılışta plan start() içinde yapılır
                self.binance.plan(bn, now)
        mapped = sum(1 for s in order if self.mappings[s].binance_symbol)
        logger.info("Semboller: %d izleniyor (%d Binance karşılıklı), %d WEEX vadelisi", len(order), mapped,
                    len(perps))
        return fresh or not self.binance_on

    async def poll_premium(self, tracked_override: list[str] | None = None) -> None:
        recv, rows = await self.weex.premium_index()
        if rows is None:
            return
        self.latest_premium = rows if isinstance(rows, list) else [rows]
        self.weex_marks = symbols.marks(self.latest_premium)
        parsed = parse_premium(self.latest_premium, recv, set(tracked_override or self.tracked))
        self.db.upsert_weex_premium(parsed)
        for r in parsed:
            self.funding.observe(r["symbol"], r["next_funding_ms"])
        if parsed:
            self.premium_gaps.ok(parsed[0]["bucket_ms"], recv)

    async def poll_oi(self) -> None:
        rows = []
        for sym in list(self.tracked):
            recv, data = await self.weex.open_interest(sym)
            row = parse_oi(data, sym, recv, self.weex_marks.get(sym)) if data is not None else None
            if row:
                rows.append(row)
        self.db.upsert_weex_oi(rows)
        if rows:
            self.oi_gaps.ok(min(r["bucket_ms"] for r in rows), self.clock.now_ms())

    async def poll_funding(self, syms: list[str]) -> None:
        last = self.db.weex_last_funding()
        limit = int(self.wcfg["funding_limit"])
        for sym in syms:
            start = last[sym] + 1 if sym in last else None
            recv, data = await self.weex.funding_history(sym, start, limit)
            if data is not None:
                self.db.upsert_weex_funding(parse_funding(data, sym, recv, self.funding.delay_ms))
            self.funding.mark(sym, self.clock.now_ms(), data is not None)

    async def bn_live(self, due_ms: int) -> None:
        period_ms = PERIOD_MS[self.bcfg["period"]]
        bar_ms = binance_rest.bar_open(due_ms, period_ms)
        retry_at = bar_ms + int(float(self.bcfg["retry_offset_s"]) * 1000)
        syms = self.binance_symbols()
        if syms:
            await self.binance.live_cycle(bar_ms, syms, retry_at)

    def liq_agg(self) -> None:
        now = self.clock.now_ms()
        self.flush()
        start = now - LIQ_REAGG_MS
        reagg = self.ws.pop_reagg_from() if self.ws is not None else None
        if reagg is not None:  # sessiz bağlantı geriye dönük kapandı: o andan beri yeniden hesapla
            start = min(start, reagg)
        self.db.aggregate_liq_1m(start, now, now)
        if self.status.ws_enabled and self.status.ws_down_since_ms is None:
            self.db.heartbeat_ok("binance_ws", now)

    def maintenance(self) -> None:
        n = self.db.prune_fetch_log(self.clock.now_ms(), float(self.cfg["fetch_log_days"]))
        if n:
            logger.info("fetch_log: %d eski satır silindi", n)

    def flush(self) -> None:
        """Tamponları yazar. DB kilitliyse sonraki turda tekrar dener (bellek sınırlı)."""
        for buffer, write in ((self.liq_buffer, self.db.insert_liquidations), (self.fetch_log, self.db.log_fetches)):
            if not buffer:
                continue
            rows = list(buffer)
            try:
                write(rows)
            except Exception as exc:
                logger.warning("Tampon yazılamadı (%d satır): %s", len(rows), exc)
                if len(buffer) > MAX_BUFFER:
                    del buffer[: len(buffer) - MAX_BUFFER]
                continue
            del buffer[: len(rows)]

    # --- zamanlayıcı --------------------------------------------------------

    def _next_due(self, name: str, now: int) -> int:
        if name == "symbols":
            return now + int(float(self.scfg["refresh_s"]) * 1000)
        if name == "weex_premium":
            return next_aligned(now, MIN_MS, int(float(self.wcfg["premium_offset_s"]) * 1000))
        if name == "weex_oi":
            return oi_due_ms(now, float(self.wcfg["oi_lead_s"]))
        if name == "bn_live":
            return next_aligned(now, PERIOD_MS[self.bcfg["period"]], int(float(self.bcfg["poll_offset_s"]) * 1000))
        if name == "liq_agg":
            return next_aligned(now, MIN_MS, 5_000)
        if name == "monitor":
            return now + int(float(self.mon_cfg["check_interval_s"]) * 1000)
        return now + 3_600_000  # maintenance

    async def _run_job(self, name: str, due_ms: int) -> None:
        if name == "symbols":
            ok = await self.refresh_symbols()
            if not ok:
                self.due["symbols"] = self.clock.now_ms() + int(float(self.scfg["retry_s"]) * 1000)
        elif name == "weex_premium":
            await self.poll_premium()
        elif name == "weex_oi":
            await self.poll_oi()
        elif name == "weex_funding":
            await self.poll_funding(self._funding_due)
        elif name == "bn_live":
            await self.bn_live(due_ms)
        elif name == "liq_agg":
            self.liq_agg()
        elif name == "monitor":
            try:
                self.db.heartbeat_ok("recorder", self.clock.now_ms())
            except Exception as exc:  # DB hatası izlemeyi durdurmasın
                logger.warning("recorder heartbeat yazılamadı: %s", exc)
            if self.monitor is not None:
                await self.monitor.check(self.clock.now_ms())
        elif name == "maintenance":
            self.maintenance()

    async def _guarded(self, name: str, coro) -> None:
        """Zamanlanmış iş: hatası yakalanır (iş bir sonraki zamanında tekrar çalışır), üst üste
        hata sayısı izlemeye bildirilir."""
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            now = self.clock.now_ms()
            n = self.status.job_fail(name, now, f"{type(exc).__name__}: {exc}")
            logger.exception("'%s' işi hata verdi (%d. kez üst üste)", name, n)
            with contextlib.suppress(Exception):
                self.db.heartbeat_err(name, now, f"{type(exc).__name__}: {exc}")
        else:
            self.status.job_ok(name, self.clock.now_ms())

    def _spawn(self, name: str, due_ms: int) -> None:
        self.tasks[name] = asyncio.create_task(self._guarded(name, self._run_job(name, due_ms)), name=name)

    def _busy(self, name: str) -> bool:
        task = self.tasks.get(name)
        return task is not None and not task.done()

    async def tick(self) -> None:
        """Zamanı gelen işleri başlatır (beklemeden). Uzun süren iş bitmeden tekrar başlatılmaz."""
        now = self.clock.now_ms()
        self._last_tick_ms = now
        self.flush()
        for name, due in list(self.due.items()):
            if now >= due:
                if self._busy(name):
                    if name not in ("monitor", "liq_agg"):
                        logger.warning("'%s' işi hâlâ sürüyor; bu tur atlandı", name)
                else:
                    self._spawn(name, due)
                self.due[name] = self._next_due(name, now)  # başarısız sembol işi kendi tekrar zamanını yazar
        if self.weex_on and not self._busy("weex_funding"):
            due_syms = self.funding.due(now, self.tracked)
            if due_syms:
                self._funding_due = due_syms
                self._spawn("weex_funding", now)

    async def drain(self) -> None:
        """Testler için: çalışan işlerin bitmesini bekler."""
        while any(not t.done() for t in self.tasks.values()):
            await asyncio.gather(*[t for t in self.tasks.values() if not t.done()], return_exceptions=True)

    async def run(self) -> None:
        try:
            await self.start()
            tick_s = float(self.cfg["tick_s"])
            while not self.stop_event.is_set():
                try:
                    await self.tick()
                except Exception:  # zamanlayıcı asla durmasın
                    logger.exception("zamanlayıcı turu hata verdi")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop_event.wait(), timeout=tick_s)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Düzgün kapanış: WS kapanır, tamponlar yazılır, uptime oturumu 'clean' kapanır."""
        if self._closed:
            return
        self._closed = True
        self.stop_event.set()
        for task in self.background:  # WS stop_event ile kendi kapanır
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(asyncio.shield(task), timeout=8)
        for task in [*self.background, *self.tasks.values()]:
            if not task.done():
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
        self.flush()
        for client in (self.http_binance, self.http_weex):
            with contextlib.suppress(Exception):
                await client.close()
        session_id = self.session_id
        if self.heartbeat is not None:
            self.heartbeat.stop()
            session_id = self.heartbeat.session_id  # takılmadan sonra yeni oturum açılmış olabilir
        if session_id is not None:
            with contextlib.suppress(Exception):
                self.uptime.stop_session(session_id, "clean", at_ms=self.clock.now_ms())
        self.db.close()
        logger.info("Kaydedici düzgün kapandı")
