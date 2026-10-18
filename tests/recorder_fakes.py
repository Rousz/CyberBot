"""Kaydedici testleri için sahte saat, sahte HTTP (Binance + WEEX) ve sahte WS (internet yok)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from cyberbot import settings
from cyberbot.recorder.defaults import MONITOR_DEFAULTS, RECORDER_DEFAULTS
from cyberbot.recorder.limiter import HttpResponse

FIXTURES = Path(__file__).parent / "fixtures"
MIN = 60_000
BAR = 300_000
HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_776_000_000_000 - 1_776_000_000_000 % DAY  # bir gün başı (UTC 00:00)


def load(rel: str):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


class FakeClock:
    """Elle ilerleyen saat. sleep() süreyi sanal olarak ilerletir (gerçekte beklemez)."""

    def __init__(self, now_ms: int = T0):
        self.t = now_ms
        self.sleeps: list[float] = []

    def now_ms(self) -> int:
        return int(self.t)

    def set(self, ms: int) -> None:
        self.t = ms

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += max(0.0, seconds) * 1000
        await asyncio.sleep(0)


def cfg(**sections) -> dict:
    """RECORDER_DEFAULTS + iç içe değişiklikler: cfg(binance={"max_rps": 100})."""
    return settings.deep_merge(RECORDER_DEFAULTS, sections)


def mon_cfg(**overrides) -> dict:
    return settings.deep_merge(MONITOR_DEFAULTS, overrides)


# WEEX evreni (fixture + test sembolleri) ve fiyatlar
WEEX_EXTRA = [
    {"symbol": "PEPEUSDT", "baseAsset": "PEPE", "quoteAsset": "USDT", "marginAsset": "USDT"},
    {"symbol": "COLLUSDT", "baseAsset": "COLL", "quoteAsset": "USDT", "marginAsset": "USDT"},
    {"symbol": "USDCUSDT", "baseAsset": "USDC", "quoteAsset": "USDT", "marginAsset": "USDT"},
]
WEEX_MARKS = {"BTCUSDT": 74011.0, "ETHUSDT": 2081.8, "SOLUSDT": 151.93, "WEEXONLYUSDT": 0.0101,
              "PEPEUSDT": 0.0000105, "COLLUSDT": 1.0, "USDCUSDT": 1.0}
WEEX_VOLUME = {"BTCUSDT": 3e9, "ETHUSDT": 1.3e9, "SOLUSDT": 3.6e8, "WEEXONLYUSDT": 1.2e6, "PEPEUSDT": 2e8,
               "COLLUSDT": 5e7, "USDCUSDT": 9e9}
BN_EXTRA = [
    {"symbol": "1000PEPEUSDT", "pair": "1000PEPEUSDT", "contractType": "PERPETUAL", "status": "TRADING",
     "baseAsset": "1000PEPE", "quoteAsset": "USDT", "marginAsset": "USDT", "onboardDate": 1683000000000},
    {"symbol": "COLLUSDT", "pair": "COLLUSDT", "contractType": "PERPETUAL", "status": "TRADING",
     "baseAsset": "COLL", "quoteAsset": "USDT", "marginAsset": "USDT", "onboardDate": 1700000000000},
]
BN_MARKS = {"BTCUSDT": 74001.1, "ETHUSDT": 2081.5, "SOLUSDT": 151.9, "1000PEPEUSDT": 0.01051, "COLLUSDT": 5.0}
FUNDING_STEP = 8 * HOUR


class FakeHttp:
    """URL yoluna göre cevap üretir. fail: {yol parçası: durum kodu | istisna | (durum, başlıklar)}."""

    def __init__(self, clock: FakeClock, *, newest_lag_ms: int = BAR):
        self.clock = clock
        self.newest_lag_ms = newest_lag_ms  # Binance en yeni satır ts'i = mum açılışı - lag
        self.calls: list[tuple[str, dict]] = []
        self.times: list[int] = []  # her isteğin (sahte) saati
        self.fail: dict[str, object] = {}
        self.closed = False

    def calls_to(self, part: str) -> list[dict]:
        return [p for u, p in self.calls if part in u]

    async def close(self) -> None:
        self.closed = True

    async def get(self, url: str, params: dict | None = None) -> HttpResponse:
        params = dict(params or {})
        self.calls.append((url, params))
        self.times.append(self.clock.now_ms())
        await asyncio.sleep(0)
        for part, what in self.fail.items():
            if part in url:
                if isinstance(what, BaseException):
                    raise what
                if isinstance(what, tuple):
                    return HttpResponse(what[0], {"code": -1, "msg": "fail"}, dict(what[1]))
                return HttpResponse(int(what), {"code": -1, "msg": "fail"}, {})
        path = urlsplit(url).path
        return HttpResponse(200, self.route(path, params), {"x-mbx-used-weight-1m": "5"}, 3.0)

    # --- yönlendirme ---------------------------------------------------------

    def route(self, path: str, p: dict):
        now = self.clock.now_ms()
        if path == "/capi/v3/market/exchangeInfo":
            info = load("weex/exchangeInfo.json")
            info["symbols"] += WEEX_EXTRA
            return info
        if path == "/capi/v3/market/ticker/24hr":
            return [{"symbol": s, "quoteVolume": str(v), "lastPrice": str(WEEX_MARKS[s])}
                    for s, v in WEEX_VOLUME.items()]
        if path == "/capi/v3/market/premiumIndex":
            nf = now - now % FUNDING_STEP + FUNDING_STEP
            return [{"symbol": s, "markPrice": str(m), "indexPrice": str(m), "forecastFundingRate": "0.0001",
                     "lastFundingRate": "0.00005", "interestRate": "0.001", "nextFundingTime": nf,
                     "time": now, "collectCycle": 480} for s, m in WEEX_MARKS.items()]
        if path == "/capi/v3/market/openInterest":
            return {"symbol": p["symbol"], "openInterest": "1234.5", "time": now}
        if path == "/capi/v3/market/fundingRate":
            start = int(p.get("startTime", now - 30 * DAY))
            start += -start % FUNDING_STEP
            rows = [{"symbol": p["symbol"], "fundingRate": "0.0001", "fundingTime": str(t), "markPrice": "100"}
                    for t in range(start, now + 1, FUNDING_STEP)]
            return rows[-int(p.get("limit", 100)):]
        if path == "/fapi/v1/exchangeInfo":
            info = load("binance/exchangeInfo.json")
            info["symbols"] += BN_EXTRA
            return info
        if path == "/fapi/v1/premiumIndex":
            return [{"symbol": s, "markPrice": str(m)} for s, m in BN_MARKS.items()]
        if path.startswith("/futures/data/"):
            return self._futures(path.rsplit("/", 1)[-1], p)
        raise AssertionError(f"FakeHttp: yönlendirilmemiş {path} {p}")

    def _futures(self, endpoint: str, p: dict) -> list[dict]:
        now = self.clock.now_ms()
        newest = now - now % BAR - self.newest_lag_ms
        limit = int(p.get("limit", 30))
        end = min(int(p.get("endTime", newest)), newest)
        oldest = now - 30 * DAY
        start = max(int(p.get("startTime", end - (limit - 1) * BAR)), oldest)
        start += -start % BAR
        times = list(range(start, end + 1, BAR))[:limit]
        sym = p["symbol"]
        out = []
        for t in times:
            if endpoint == "openInterestHist":
                out.append({"symbol": sym, "sumOpenInterest": "100", "sumOpenInterestValue": "7400000",
                            "CMCCirculatingSupply": "19950000", "timestamp": t})
            elif endpoint == "takerlongshortRatio":
                out.append({"buySellRatio": "1.05", "buyVol": "10", "sellVol": "9.5", "timestamp": t})
            else:
                out.append({"symbol": sym, "longShortRatio": "1.5", "longAccount": "0.6", "shortAccount": "0.4",
                            "timestamp": t})
        return out


def force_order(symbol="BTCUSDT", side="SELL", t=T0, price="74000", qty="0.5", ap="73990", z="0.5", st=1, **kw):
    msg = {"e": "forceOrder", "E": t + 5,
           "o": {"s": symbol, "S": side, "o": "LIMIT", "f": "IOC", "q": qty, "p": price, "ap": ap, "X": "FILLED",
                 "l": z, "z": z, "T": t}}
    if st is not None:
        msg["st"] = st
        msg["ps"] = "BOTH"
    msg.update(kw)
    return msg


class FakeWsClosed(Exception):
    pass


class FakeWsConnection:
    """websockets ClientConnection yerine: send/recv/close/async for.
    ack=True: SUBSCRIBE gelince Binance gibi {"result": null, "id": n} cevabı kuyruğa eklenir
    (betik zaten bir cevap içeriyorsa eklenmez). ack="error": hata cevabı."""

    def __init__(self, messages: list, ack: bool | str = True):
        self.sent: list[str] = []
        self.ack = ack
        self._queue: asyncio.Queue = asyncio.Queue()
        self._scripted_reply = any(isinstance(m, dict) and "id" in m and ("result" in m or "error" in m)
                                   for m in messages)
        for m in messages:
            self._queue.put_nowait(json.dumps(m) if not isinstance(m, str) else m)
        self.closed = False

    async def send(self, text: str) -> None:
        self.sent.append(text)
        msg = json.loads(text)
        if msg.get("method") == "SUBSCRIBE" and self.ack and not self._scripted_reply:
            reply = {"error": {"code": 2, "msg": "Invalid request"}, "id": msg["id"]} if self.ack == "error" \
                else {"result": None, "id": msg["id"]}
            self._queue.put_nowait(json.dumps(reply))

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(None)

    async def recv(self):
        item = await self._queue.get()
        if item is None:
            raise FakeWsClosed("kapandı")
        return item

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item


class FakeWsFactory:
    def __init__(self, scripts: list[list], ack: bool | str = True):
        self.scripts = list(scripts)
        self.ack = ack
        self.connections: list[FakeWsConnection] = []

    async def __call__(self, url: str, **kwargs) -> FakeWsConnection:
        conn = FakeWsConnection(self.scripts.pop(0) if self.scripts else [], ack=self.ack)
        self.connections.append(conn)
        return conn
