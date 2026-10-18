"""Binance USDⓈ-M likidasyon akışı: wss://fstream.binance.com/market/ws + SUBSCRIBE '!forceOrder@arr'
(ccxt'nin yaptığı gibi; websockets 17 asyncio istemcisi).

- Sadece UM yükleri saklanır: 'st' alanı varsa st == 1 (CM birleşmesinden sonra akış COIN-M de taşır).
- Ham alanlar + notional = ap * z (ortalama fiyat x dolan miktar).
- Veri ALT SINIRDIR: Binance sembol başına 1000 ms'de sadece son likidasyonu yollar.
- Geçmişi yoktur: bağlı olunmayan an kaybolur. Her bağlantı ws_sessions'a yazılır; dakika
  kapsaması (coverage) bağlantı süresinden hesaplanır. Oturum ancak SUBSCRIBE onayı
  ({"result": null, "id": n}) ws_ack_timeout_s içinde gelince açılır; hata cevabı veya onaysızlık
  = bağlanamadı (bekleyip tekrar). Bağlantı açık ama ws_silence_s boyunca hiç forceOrder mesajı
  gelmezse (sessiz/kırık abonelik) oturum son mesaj anında kapatılır (o süre kapsanmamış sayılır,
  "0 likidasyon" değil) ve yeniden bağlanılır.
- Sunucu bağlantıyı 24 saatte keser: 23 saatte bir örtüşmeli yenilenir (önce yeni bağlantı
  açılır, overlap_s sonra eskisi kapanır; tekrarları doğal anahtar eler).
- Kopunca titreşimli üstel bekleme (1, 2, 4 ... 60 sn) ile yeniden bağlanır.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
from typing import Any, Callable

from cyberbot.recorder.db import ALL, DerivsDB, to_float, to_int
from cyberbot.recorder.limiter import USER_AGENT, Clock
from cyberbot.recorder.monitor import Status

logger = logging.getLogger(__name__)

STREAM = "!forceOrder@arr"
SOURCE = "bn_liq"  # gaps.source


def parse_force_order(msg: Any, recv_ms: int, conn_id: int | None) -> dict | None:
    """forceOrder yükü -> bn_liquidations satırı (UM değilse veya bozuksa None)."""
    if not isinstance(msg, dict):
        return None
    if isinstance(msg.get("data"), dict):  # birleşik akış zarfı {"stream":..., "data":...}
        msg = msg["data"]
    if msg.get("e") != "forceOrder":
        return None
    if "st" in msg and to_int(msg.get("st")) != 1:
        return None
    o = msg.get("o")
    if not isinstance(o, dict):
        return None
    symbol, side = o.get("s"), o.get("S")
    trade_ms, price, qty = to_int(o.get("T")), to_float(o.get("p")), to_float(o.get("q"))
    if not symbol or side not in ("BUY", "SELL") or trade_ms is None or price is None or qty is None:
        return None
    ap, z = to_float(o.get("ap")), to_float(o.get("z"))
    return {
        "symbol": str(symbol), "trade_ms": trade_ms, "side": side, "price": price, "qty": qty,
        "event_ms": to_int(msg.get("E")) or recv_ms, "avg_price": ap, "last_qty": to_float(o.get("l")),
        "filled_qty": z, "status": o.get("X"), "order_type": o.get("o"), "tif": o.get("f"),
        "ps": msg.get("ps"), "st": to_int(msg.get("st")),
        "notional": ap * z if ap is not None and z is not None else None,
        "recv_ms": recv_ms, "conn_id": conn_id,
    }


def iter_payloads(raw: Any) -> list:
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return msg if isinstance(msg, list) else [msg]


def is_force_order(msg: Any) -> bool:
    if isinstance(msg, dict) and isinstance(msg.get("data"), dict):
        msg = msg["data"]
    return isinstance(msg, dict) and msg.get("e") == "forceOrder"


class SubscribeError(Exception):
    pass


def backoff_s(attempt: int, cap_s: float, rng: Callable[[], float] = random.random) -> float:
    """Titreşimli üstel bekleme: taban 1, 2, 4 ... cap; [taban/2, taban] arası rastgele."""
    base = min(cap_s, 2.0 ** max(0, attempt - 1))
    return base * (0.5 + 0.5 * rng())


async def default_connect(url: str, **kwargs):
    from websockets.asyncio.client import connect

    return await connect(url, **kwargs)


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=max(0.0, seconds))


class _Connection:
    def __init__(self, stream: LiquidationStream, number: int):
        self.s = stream
        self.number = number
        self.ws = None
        self.conn_id: int | None = None
        self.closed = asyncio.Event()
        self.closed_ms: int | None = None
        self.reason = ""
        self.task: asyncio.Task | None = None
        self.messages = 0
        self.last_data_ms = 0                     # son forceOrder mesajı (sessizlik kontrolü)
        self._early: list[tuple[int, Any]] = []   # onaydan önce gelen mesajlar

    async def _wait_ack(self) -> None:
        """SUBSCRIBE cevabını bekler. Hata cevabı veya zaman aşımı: istisna."""
        s = self.s
        loop = asyncio.get_running_loop()
        deadline = loop.time() + s.ack_timeout_s
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise SubscribeError(f"abonelik onayı {s.ack_timeout_s:.0f} sn içinde gelmedi")
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
            except TimeoutError:
                raise SubscribeError(f"abonelik onayı {s.ack_timeout_s:.0f} sn içinde gelmedi") from None
            reply = next((m for m in iter_payloads(raw)
                          if isinstance(m, dict) and m.get("id") == self.number and ("result" in m or "error" in m)),
                         None)
            if reply is None:
                if len(self._early) < 10_000:
                    self._early.append((s.clock.now_ms(), raw))
                continue
            if reply.get("error") is not None or reply.get("result") is not None:
                raise SubscribeError(f"abonelik reddedildi: {str(reply)[:200]}")
            return

    async def open(self) -> bool:
        s = self.s
        try:
            self.ws = await asyncio.wait_for(
                s.connect(s.url, open_timeout=s.open_timeout_s, ping_interval=60, ping_timeout=60,
                          max_size=2**20, additional_headers={"User-Agent": USER_AGENT}),
                timeout=s.open_timeout_s + 1)
            await self.ws.send(json.dumps({"method": "SUBSCRIBE", "params": [STREAM], "id": self.number}))
            await self._wait_ack()
        except Exception as exc:
            logger.warning("Binance likidasyon WS bağlanamadı: %s: %s", type(exc).__name__, str(exc)[:200])
            if self.ws is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.ws.close(), timeout=5)
            return False
        now = s.clock.now_ms()
        self.last_data_ms = now
        try:
            self.conn_id = s.db.ws_open(s.url, now, s.run_id)
        except Exception:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.ws.close(), timeout=5)
            raise
        self.task = asyncio.create_task(self._reader(), name=f"bn-liq-ws-{self.number}")
        logger.info("Binance likidasyon WS bağlandı (oturum %s)", self.conn_id)
        return True

    def _handle(self, raw: Any, recv_ms: int) -> None:
        rows = []
        for msg in iter_payloads(raw):
            if isinstance(msg, dict) and "id" in msg and ("result" in msg or "error" in msg):
                continue  # abonelik cevabı
            if is_force_order(msg):
                self.last_data_ms = max(self.last_data_ms, recv_ms)
            row = parse_force_order(msg, recv_ms, self.conn_id)
            if row is not None:
                rows.append(row)
        self.messages += 1
        if rows:
            self.s.on_rows(rows)

    async def _reader(self) -> None:
        try:
            early, self._early = self._early, []
            for recv_ms, raw in early:
                self._handle(raw, recv_ms)
            async for raw in self.ws:
                self._handle(raw, self.s.clock.now_ms())
            self.reason = self.reason or "server_closed"
        except asyncio.CancelledError:
            self.reason = self.reason or "cancelled"
            raise
        except Exception as exc:
            self.reason = self.reason or f"error: {type(exc).__name__}: {str(exc)[:150]}"
        finally:
            self.closed_ms = self.closed_ms or self.s.clock.now_ms()
            self.closed.set()

    async def close(self, reason: str, at_ms: int | None = None) -> None:
        """at_ms: oturumun kapanmış sayılacağı an (sessizlikte son mesaj anı)."""
        if not self.closed.is_set():
            self.reason = reason
            self.closed_ms = at_ms or self.s.clock.now_ms()
        self.closed.set()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.ws.close(), timeout=5)
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(BaseException):
                await self.task
        if self.conn_id is not None:
            conn_id, self.conn_id = self.conn_id, None
            try:
                self.s.db.ws_close(conn_id, self.closed_ms or self.s.clock.now_ms(), self.reason or reason)
            except Exception as exc:  # açık kalan satırı kaydedici (ws_close_dangling) kapatır
                logger.warning("WS oturumu %s kapanışı yazılamadı: %s", conn_id, exc)
                return
            logger.info("Binance likidasyon WS kapandı (oturum %s, %s)", conn_id, self.reason or reason)


class LiquidationStream:
    def __init__(self, url: str, db: DerivsDB, clock: Clock, cfg: dict, status: Status,
                 on_rows: Callable[[list[dict]], None], *, connect: Callable | None = None,
                 run_id: int | None = None, rng: Callable[[], float] = random.random):
        self.url = url
        self.db = db
        self.clock = clock
        self.status = status
        self.on_rows = on_rows
        self.connect = connect or default_connect
        self.run_id = run_id
        self.rng = rng
        self.rotate_s = float(cfg["ws_rotate_s"])
        self.overlap_s = float(cfg["ws_overlap_s"])
        self.backoff_max_s = float(cfg["ws_backoff_max_s"])
        self.open_timeout_s = float(cfg["ws_open_timeout_s"])
        self.ack_timeout_s = float(cfg.get("ws_ack_timeout_s", 10))
        self.silence_ms = int(float(cfg.get("ws_silence_s", 600)) * 1000)
        self.gap_min_ms = int(float(cfg["ws_gap_min_s"]) * 1000)
        self.connections_opened = 0
        self.rotations = 0
        self.silent_closes = 0
        self.reagg_from_ms: int | None = None  # geriye dönük kapanış: kovalar buradan yeniden hesaplanmalı

    def pop_reagg_from(self) -> int | None:
        value, self.reagg_from_ms = self.reagg_from_ms, None
        return value

    def _new(self) -> _Connection:
        self.connections_opened += 1
        return _Connection(self, self.connections_opened)

    def _after_open(self, conn: _Connection) -> None:
        now = self.clock.now_ms()
        self.status.ws_down_since_ms = None
        if self.db.ws_open_sessions() <= 1:  # örtüşen bağlantı yok: önceki kapanıştan beri boşluk var
            last_close = self.db.query("SELECT MAX(close_ms) FROM ws_sessions WHERE conn_id <> ?",
                                       (conn.conn_id,))[0][0]
            if last_close is not None and now - last_close > self.gap_min_ms:
                self.db.add_gap(SOURCE, ALL, last_close, now, "ws_down", "unrecoverable", now)

    def _silent(self, conn: _Connection) -> bool:
        return bool(self.silence_ms) and self.clock.now_ms() - conn.last_data_ms > self.silence_ms

    async def run(self, stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        self.status.ws_enabled = True
        if self.status.ws_down_since_ms is None:
            self.status.ws_down_since_ms = self.clock.now_ms()
        current: _Connection | None = None
        opened: list[_Connection] = []  # kapanışta hepsi kapanır (hata olsa bile)
        attempt = 0
        rotate_at = 0.0
        check_s = min(30.0, self.silence_ms / 4000) if self.silence_ms else None
        try:
            while not stop.is_set():
                if current is None:
                    conn = self._new()
                    if not await conn.open():
                        attempt += 1
                        await _sleep_or_stop(stop, backoff_s(attempt, self.backoff_max_s, self.rng))
                        continue
                    opened = [c for c in opened if c.conn_id is not None] + [conn]
                    current, attempt, rotate_at = conn, 0, loop.time() + self.rotate_s
                    self._after_open(conn)
                waiters = [asyncio.create_task(current.closed.wait()), asyncio.create_task(stop.wait())]
                timeout = max(0.0, rotate_at - loop.time())
                if check_s is not None:
                    timeout = min(timeout, check_s)
                try:
                    await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for w in waiters:
                        w.cancel()
                if stop.is_set():
                    break
                if not current.closed.is_set() and self._silent(current):
                    logger.warning("Binance likidasyon akışı %d sn'dir mesaj göndermiyor (abonelik bozuk olabilir);"
                                   " yeniden bağlanılıyor, sessiz süre kapsanmamış sayılır",
                                   (self.clock.now_ms() - current.last_data_ms) // 1000)
                    await current.close("silent", at_ms=current.last_data_ms)
                    self.silent_closes += 1
                    self.reagg_from_ms = min(self.reagg_from_ms or current.closed_ms, current.closed_ms)
                if current.closed.is_set():
                    await current.close(current.reason)
                    self.status.ws_down_since_ms = current.closed_ms
                    current = None
                    attempt += 1
                    await _sleep_or_stop(stop, backoff_s(attempt, self.backoff_max_s, self.rng))
                    continue
                if loop.time() >= rotate_at:  # örtüşmeli yenileme
                    new = self._new()
                    if await new.open():
                        opened.append(new)
                        self._after_open(new)
                        await _sleep_or_stop(stop, self.overlap_s)
                        await current.close("rotate")
                        current, rotate_at = new, loop.time() + self.rotate_s
                        self.rotations += 1
                        opened = [c for c in opened if c.conn_id is not None]
                    else:
                        rotate_at = loop.time() + min(60.0, self.rotate_s)
        finally:
            reason = "shutdown" if stop.is_set() else "error"
            for conn in opened:
                if conn.conn_id is not None or not conn.closed.is_set():
                    await conn.close(reason)
