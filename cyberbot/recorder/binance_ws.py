"""Binance USDⓈ-M likidasyon akışı: wss://fstream.binance.com/market/ws + SUBSCRIBE '!forceOrder@arr'
(ccxt'nin yaptığı gibi; websockets 17 asyncio istemcisi).

- Sadece UM yükleri saklanır: 'st' alanı varsa st == 1 (CM birleşmesinden sonra akış COIN-M de taşır).
- Ham alanlar + notional = ap * z (ortalama fiyat x dolan miktar).
- Veri ALT SINIRDIR: Binance sembol başına 1000 ms'de sadece son likidasyonu yollar.
- Geçmişi yoktur: bağlı olunmayan an kaybolur. Her bağlantı ws_sessions'a yazılır; dakika
  kapsaması (coverage) mesaj gelip gelmemesinden değil bağlantı süresinden hesaplanır.
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

    async def open(self) -> bool:
        s = self.s
        try:
            self.ws = await asyncio.wait_for(
                s.connect(s.url, open_timeout=s.open_timeout_s, ping_interval=60, ping_timeout=60,
                          max_size=2**20, additional_headers={"User-Agent": USER_AGENT}),
                timeout=s.open_timeout_s + 1)
            await self.ws.send(json.dumps({"method": "SUBSCRIBE", "params": [STREAM], "id": self.number}))
        except Exception as exc:
            logger.warning("Binance likidasyon WS bağlanamadı: %s: %s", type(exc).__name__, str(exc)[:200])
            if self.ws is not None:
                with contextlib.suppress(Exception):
                    await self.ws.close()
            return False
        self.conn_id = s.db.ws_open(s.url, s.clock.now_ms(), s.run_id)
        self.task = asyncio.create_task(self._reader(), name=f"bn-liq-ws-{self.number}")
        logger.info("Binance likidasyon WS bağlandı (oturum %s)", self.conn_id)
        return True

    async def _reader(self) -> None:
        try:
            async for raw in self.ws:
                recv_ms = self.s.clock.now_ms()
                rows = []
                for msg in iter_payloads(raw):
                    if isinstance(msg, dict) and "result" in msg and "id" in msg:
                        continue  # abonelik onayı
                    row = parse_force_order(msg, recv_ms, self.conn_id)
                    if row is not None:
                        rows.append(row)
                self.messages += 1
                if rows:
                    self.s.on_rows(rows)
            self.reason = self.reason or "server_closed"
        except asyncio.CancelledError:
            self.reason = self.reason or "cancelled"
            raise
        except Exception as exc:
            self.reason = self.reason or f"error: {type(exc).__name__}: {str(exc)[:150]}"
        finally:
            self.closed_ms = self.closed_ms or self.s.clock.now_ms()
            self.closed.set()

    async def close(self, reason: str) -> None:
        if not self.closed.is_set():
            self.reason = reason
            self.closed_ms = self.s.clock.now_ms()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.ws.close(), timeout=5)
        if self.task is not None and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(BaseException):
                await self.task
        if self.conn_id is not None:
            self.s.db.ws_close(self.conn_id, self.closed_ms or self.s.clock.now_ms(), self.reason or reason)
            logger.info("Binance likidasyon WS kapandı (oturum %s, %s)", self.conn_id, self.reason or reason)


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
        self.gap_min_ms = int(float(cfg["ws_gap_min_s"]) * 1000)
        self.connections_opened = 0
        self.rotations = 0

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

    async def run(self, stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        self.status.ws_enabled = True
        if self.status.ws_down_since_ms is None:
            self.status.ws_down_since_ms = self.clock.now_ms()
        current: _Connection | None = None
        attempt = 0
        rotate_at = 0.0
        try:
            while not stop.is_set():
                if current is None:
                    conn = self._new()
                    if not await conn.open():
                        attempt += 1
                        await _sleep_or_stop(stop, backoff_s(attempt, self.backoff_max_s, self.rng))
                        continue
                    self._after_open(conn)
                    current, attempt, rotate_at = conn, 0, loop.time() + self.rotate_s
                waiters = [asyncio.create_task(current.closed.wait()), asyncio.create_task(stop.wait())]
                try:
                    await asyncio.wait(waiters, timeout=max(0.0, rotate_at - loop.time()),
                                       return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for w in waiters:
                        w.cancel()
                if stop.is_set():
                    break
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
                        self._after_open(new)
                        await _sleep_or_stop(stop, self.overlap_s)
                        await current.close("rotate")
                        current, rotate_at = new, loop.time() + self.rotate_s
                        self.rotations += 1
                    else:
                        rotate_at = loop.time() + min(60.0, self.rotate_s)
        finally:
            if current is not None:
                await current.close("shutdown")
