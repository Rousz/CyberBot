"""weex_probe için sahte ağ: WEEX ham uçları, Binance /futures/data ve likidasyon WS.

tests/fakes.FakeTransport'u genişletir (onu değiştirmez). Zaman sahte bir saatten gelir;
bekleme (sleep) anında geçer, böylece "yeni /futures/data satırı ne zaman çıktı" ölçümü
saniyeler içinde biter. Davranışlar (son mumun oluşan mum olması, historyKlines'ın ilk mi
son mu 100'ü verdiği...) parametreyle değiştirilir; testler iki yönü de dener.
"""

from __future__ import annotations

import copy
import json
import time
from urllib.parse import urlsplit

from cyberbot import connection_test as ct
from cyberbot.connection_test import HttpStatusError
from tests.fakes import FakeTransport, load
from tests.weex_router import WeexRouter

MIN_MS = 60_000
HOUR_MS = 60 * MIN_MS
DAY_MS = 24 * HOUR_MS
TF = {"5m": 5 * MIN_MS, "1h": HOUR_MS}
FUNDING_MS = 8 * HOUR_MS
BN_PERIOD = 5 * MIN_MS


class FakeClock:
    def __init__(self, start_ms: int | None = None):
        self.t = start_ms if start_ms is not None else int(time.time() * 1000)
        self.sleeps: list[float] = []

    def now_ms(self) -> int:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += int(seconds * 1000)


def bad_request(code: int, msg: str) -> HttpStatusError:
    return HttpStatusError(400, json.dumps({"code": code, "msg": msg}))


def _kline(t: int, tf: int, price: float, volume: str = "12.5") -> list:
    return [t, f"{price:.1f}", f"{price + 5:.1f}", f"{price - 5:.1f}", f"{price + 1:.1f}", volume,
            t + tf - 1, "925000.0", 10, "6", "460000"]


class ProbeRouter(WeexRouter):
    """offline_weex yönlendiricisi + fixture'daki her sembol için bookTicker (bid/ask tam)."""

    def route(self, api, path, params):
        rows = super().route(api, path, params)
        if path == "capi/v3/market/ticker/bookTicker":
            have = {r["symbol"] for r in rows}
            rows = rows + [{"symbol": "WEEXONLYUSDT", "bidPrice": "0.5", "bidQty": "100", "askPrice": "0.5001",
                            "askQty": "100", "time": self.now_ms()}] * ("WEEXONLYUSDT" not in have)
        return rows


EXTRA_TICKERS = ("WEEXONLYUSDT", "1000PEPEUSDT", "NOBASEUSDT")


class ProbeTransport(FakeTransport):
    def __init__(self, clock: FakeClock, *, forming: bool = True, history_side: str = "first",
                 start_inclusive: bool = True, history_days: int = 400, bn_lag_s: int = 20,
                 liquidation: dict | list | None = "default", **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.forming = forming
        self.history_side = history_side
        self.start_inclusive = start_inclusive
        self.history_days = history_days
        self.bn_lag_ms = bn_lag_s * 1000
        if liquidation == "default":
            liquidation = {"e": "forceOrder", "E": clock.now_ms(),
                           "o": {"s": "BTCUSDT", "S": "SELL", "o": "LIMIT", "f": "IOC", "q": "0.014", "p": "73900",
                                 "ap": "73910", "X": "FILLED", "l": "0.014", "z": "0.014", "T": clock.now_ms(),
                                 "st": 1, "ps": "LONG"}}
        self.liquidation = liquidation

    # --- yönlendirme -------------------------------------------------------
    def get(self, url, params=None, *, expect_json=True, method="GET"):
        params = dict(params or {})
        parts = urlsplit(url)
        if parts.netloc == "api-contract.weex.com":
            self.calls.append((url, params))
            self._maybe_fail(url)
            return self._ok(self._weex(parts.path, params), url)
        if parts.netloc == "fapi.binance.com":
            self.calls.append((url, params))
            self._maybe_fail(url)
            return self._ok(self._bn(parts.path, params), url)
        return super().get(url, params, expect_json=expect_json, method=method)

    def _ok(self, data, url):
        return ct.HttpResult(data, 200, 5.0, url, self.clock.now_ms())

    def calls_to(self, part: str) -> list[dict]:
        return [p for u, p in self.calls if part in u]

    # --- WEEX --------------------------------------------------------------
    def _weex(self, path: str, p: dict):
        now = self.clock.now_ms()
        name = path.rsplit("/", 1)[-1]
        if name == "time":
            return {"serverTime": now}
        if name == "exchangeInfo":
            data = load("weex/exchangeInfo.json")
            pepe = copy.deepcopy(data["symbols"][0])
            pepe.update({"symbol": "1000PEPEUSDT", "baseAsset": "1000PEPE", "contractVal": "1",
                         "quantityPrecision": "0", "minOrderSize": "1", "status": "TRADING"})
            broken = copy.deepcopy(data["symbols"][0])
            broken.update({"symbol": "NOBASEUSDT", "baseAsset": None})
            data["symbols"] += [pepe, broken]
            return data
        if name == "24hr":
            rows = load("weex/ticker_24hr.json")
            have = {r["symbol"] for r in rows}
            rows += [dict(rows[-1], symbol=s, quoteVolume="1000") for s in EXTRA_TICKERS if s not in have]
            for row in rows:
                row["closeTime"] = now
            return rows
        if name == "bookTicker":
            prices = [("BTCUSDT", "74010.5", "74010.6"), ("ETHUSDT", "2081.79", "2081.81"),
                      ("SOLUSDT", "151.91", "151.93")] + [(s, "0.5", "0.5001") for s in EXTRA_TICKERS]
            return [{"symbol": s, "bidPrice": b, "bidQty": "1", "askPrice": a, "askQty": "1", "time": now}
                    for s, b, a in prices]
        if name in ("klines", "markPriceKlines", "indexPriceKlines"):
            tf = TF[p["interval"]]
            limit = int(p.get("limit", 100))
            if limit > 1000:
                raise bad_request(-1100, "limit too large")
            newest = now // tf * tf if self.forming else now // tf * tf - tf
            vol = "12.5" if name == "klines" else "0"
            return [_kline(t, tf, 74000.0, vol) for t in range(newest - (limit - 1) * tf, newest + 1, tf)]
        if name == "historyKlines":
            tf = TF[p["interval"]]
            start, end = int(p["startTime"]), int(p["endTime"])
            if start < now - self.history_days * DAY_MS:
                raise bad_request(-1170, "QUERY_TIME_OUT_OF_RANGE")
            first = -(-start // tf) * tf
            if not self.start_inclusive and first == start:
                first += tf
            times = list(range(first, min(end, now) + 1, tf))
            times = times[:100] if self.history_side == "first" else times[-100:]
            price_type = p.get("priceType")
            price = {"MARK": 74001.0, "INDEX": 74002.0}.get(price_type, 74000.0)
            return [_kline(t, tf, price, "0" if price_type else "12.5") for t in times]
        if name == "fundingRate":
            start = int(p.get("startTime", now - 30 * DAY_MS))
            end = int(p.get("endTime", now))
            limit = min(int(p.get("limit", 100)), 1000)
            oldest = now - 365 * DAY_MS
            first = -(-max(start, oldest) // FUNDING_MS) * FUNDING_MS
            times = list(range(first, min(end, now) + 1, FUNDING_MS))[:limit]
            return [{"symbol": p["symbol"], "fundingRate": "0.0001", "fundingTime": t, "markPrice": "74000"}
                    for t in times]
        if name == "premiumIndex":
            rows = load("weex/premiumIndex.json")
            eth = dict(rows[0], symbol="ETHUSDT", markPrice="2081.8")
            sol = dict(rows[0], symbol="SOLUSDT", markPrice="151.9", collectCycle=240)
            return rows + [eth, sol]
        if name == "depth":
            limit = p.get("limit")
            if limit == 50:
                raise bad_request(-1100, "Illegal characters found in parameter 'limit'")
            n = 15 if limit in (None, 15) else int(limit)
            return {"bids": [[f"{74010.5 - i:.1f}", "1"] for i in range(n)],
                    "asks": [[f"{74010.6 + i:.1f}", "1"] for i in range(n)], "lastUpdateId": 1}
        if name == "openInterest":
            row = load("weex/openInterest.json")
            row["symbol"] = p["symbol"]
            return row
        raise AssertionError(f"ProbeTransport bilinmeyen WEEX yolu: {path} {p}")

    # --- Binance -----------------------------------------------------------
    def bn_newest(self) -> int:
        # satır [ts, ts+5dk) dönemi içindir; dönem bitince bn_lag_ms sonra yayınlanır
        return (self.clock.now_ms() - self.bn_lag_ms) // BN_PERIOD * BN_PERIOD - BN_PERIOD

    def _bn(self, path: str, p: dict):
        now = self.clock.now_ms()
        if path == "/fapi/v1/time":
            return {"serverTime": now}
        if path == "/fapi/v1/exchangeInfo":
            data = load("binance/exchangeInfo.json")
            pepe = dict(data["symbols"][0], symbol="1000PEPEUSDT", baseAsset="1000PEPE")
            data["symbols"].append(pepe)
            return data
        if path.startswith("/futures/data/"):
            endpoint = path.rsplit("/", 1)[1]
            limit = int(p.get("limit", 30))
            if limit > 500:
                raise bad_request(-1130, "Data sent for parameter 'limit' is not valid.")
            newest = self.bn_newest()
            if "startTime" in p:
                start = int(p["startTime"])
                if start < now - 30 * DAY_MS:
                    raise bad_request(-1130, "startTime is invalid")
                first = -(-start // BN_PERIOD) * BN_PERIOD
                times = list(range(first, newest + 1, BN_PERIOD))[:limit]
            else:
                times = list(range(newest - (limit - 1) * BN_PERIOD, newest + 1, BN_PERIOD))
            template = load("binance/futures_data.json")[endpoint][0]
            return [dict(template, timestamp=t) for t in times]
        raise AssertionError(f"ProbeTransport bilinmeyen Binance yolu: {path}")

    # --- WebSocket -----------------------------------------------------------
    def ws(self, url, *, subscribe=None, headers=None, accept, ping_reply=None, timeout=ct.WS_TIMEOUT):
        self.ws_calls.append((url, subscribe, headers))
        self._maybe_fail(url)
        if url != ct.BINANCE_WS_MARKET:
            raise AssertionError(f"ProbeTransport bilinmeyen WS: {url}")
        if self.liquidation is None or not accept(self.liquidation):
            return ct.WsResult(20.0, None, None)
        return ct.WsResult(20.0, self.liquidation, 1500.0)
