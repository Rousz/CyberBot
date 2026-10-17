"""Sahte ağ katmanı: bağlantı testini internetsiz, fixture cevaplarla çalıştırır."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from cyberbot import connection_test as ct

FIXTURES = Path(__file__).parent / "fixtures"


def load(rel: str):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def now_ms() -> int:
    return int(time.time() * 1000)


def synthetic_klines(end_ms: int, n: int, step: int = ct.FIVE_MIN_MS, price: float = 74000.0, as_text: bool = True):
    """Ardışık, boşluksuz n mum. WEEX/Binance gibi sayıları metin olarak verir."""
    start = (end_ms // step) * step - (n - 1) * step
    rows = []
    for i in range(n):
        t = start + i * step
        o = price + i * 0.5
        values = [o, o + 5, o - 5, o + 1, 12.5]
        cells = [f"{v:.1f}" for v in values] if as_text else values
        rows.append([t, *cells, t + step - 1, "925000.0"])
    return rows


class FakeTransport:
    def __init__(self, history_days: int = 400, failures: dict | None = None, ws_silent=("fstream.binance.com/ws/",)):
        self.history_days = history_days
        self.failures = failures or {}  # URL parçası -> fırlatılacak istisna
        self.ws_silent = tuple(ws_silent)  # bu parçaları içeren WS adresleri veri göndermez
        self.calls: list[tuple[str, dict]] = []
        self.ws_calls: list[tuple[str, list | None, dict | None]] = []
        self.posts: list[tuple[str, dict]] = []

    def _maybe_fail(self, url: str) -> None:
        for part, exc in self.failures.items():
            if part in url:
                raise exc

    @staticmethod
    def _ok(data, url: str) -> ct.HttpResult:
        return ct.HttpResult(data, 200, 5.0, url, now_ms())

    def get(self, url, params=None, *, expect_json=True, method="GET"):
        params = dict(params or {})
        self.calls.append((url, params))
        self._maybe_fail(url)
        parts = urlsplit(url)
        host, path = parts.netloc, parts.path

        if url == ct.WEEX_WEB:
            return self._ok("<html>weex</html>", url)
        if host == "api-contract.weex.com":
            return self._ok(self._weex_contract(path, params), url)
        if host == "api-spot.weex.com" and path == "/api/v3/time":
            return self._ok({"serverTime": now_ms()}, url)
        if host == "fapi.binance.com":
            return self._ok(self._binance(path, params), url)
        if host == "data.binance.vision":
            return self._ok("", url)
        if host == "api.telegram.org":
            if path.endswith("/getMe"):
                return self._ok({"ok": True, "result": {"id": 1, "is_bot": True, "username": "cyberbot_test_bot"}}, url)
            if path.endswith("/getUpdates"):
                return self._ok(load("telegram/getUpdates.json"), url)
        raise AssertionError(f"FakeTransport bilinmeyen adres: {url}")

    def _weex_contract(self, path, params):
        if path == "/capi/v3/market/time":
            return {"serverTime": now_ms()}
        if path == "/capi/v3/market/exchangeInfo":
            return load("weex/exchangeInfo.json")
        if path == "/capi/v3/market/ticker/24hr":
            return load("weex/ticker_24hr.json")
        if path == "/capi/v3/market/klines":
            return synthetic_klines(now_ms(), int(params.get("limit", 100)))
        if path == "/capi/v3/market/historyKlines":
            start, end = int(params["startTime"]), int(params["endTime"])
            if now_ms() - start > self.history_days * ct.DAY_MS:
                return []
            return synthetic_klines(end, ct.WEEX_HISTORY_LIMIT)
        if path == "/capi/v3/market/depth":
            return load("weex/depth.json")
        if path == "/capi/v3/market/premiumIndex":
            return load("weex/premiumIndex.json")
        if path == "/capi/v3/market/openInterest":
            return load("weex/openInterest.json")
        raise AssertionError(f"FakeTransport bilinmeyen WEEX yolu: {path}")

    def _binance(self, path, params):
        if path == "/fapi/v1/time":
            return {"serverTime": now_ms()}
        if path == "/fapi/v1/exchangeInfo":
            return load("binance/exchangeInfo.json")
        if path == "/fapi/v1/klines":
            if params.get("startTime") == 0:
                return [[1569888000000, "8300.0", "8310.0", "8290.0", "8305.0", "10.0", 1569888299999, "83000.0"]]
            return synthetic_klines(now_ms(), int(params.get("limit", 500)))
        if path.startswith("/futures/data/"):
            return load("binance/futures_data.json")[path.rsplit("/", 1)[1]]
        if path == "/fapi/v1/premiumIndex":
            return load("binance/premiumIndex.json")
        if path == "/fapi/v1/ticker/price":
            return load("binance/ticker_price.json")
        raise AssertionError(f"FakeTransport bilinmeyen Binance yolu: {path}")

    def post_json(self, url, payload):
        self.posts.append((url, dict(payload)))
        self._maybe_fail(url)
        if url.endswith("/sendMessage"):
            return self._ok({"ok": True, "result": {"message_id": 7}}, url)
        raise AssertionError(f"FakeTransport bilinmeyen POST: {url}")

    def ws(self, url, *, subscribe=None, headers=None, accept, ping_reply=None, timeout=ct.WS_TIMEOUT):
        self.ws_calls.append((url, subscribe, headers))
        self._maybe_fail(url)
        if any(part in url for part in self.ws_silent):
            return ct.WsResult(20.0, None, None)
        if "weex.com" in url:
            message = load("weex/ws_ticker.json")
        elif "kline" in url:
            message = {"e": "kline", "E": now_ms(), "s": "BTCUSDT", "k": {"t": now_ms(), "i": "5m", "c": "74000.0", "x": False}}
        elif "bookTicker" in url:
            message = {"e": "bookTicker", "s": "BTCUSDT", "b": "74000.0", "B": "3.1", "a": "74000.1", "A": "2.2"}
        elif "forceOrder" in url:
            message = {"e": "forceOrder", "E": now_ms(), "o": {"s": "BTCUSDT", "S": "SELL", "q": "0.014", "p": "73900", "X": "FILLED"}}
        else:
            raise AssertionError(f"FakeTransport bilinmeyen WS: {url}")
        if not accept(message):
            return ct.WsResult(20.0, None, None)
        return ct.WsResult(20.0, message, 35.0)


class FakeCcxt:
    """ccxt.weex yerine geçer; oluşturulan her örnek `created` listesine eklenir."""

    created: list[FakeCcxt] = []

    def __init__(self, config: dict):
        self.config = config
        FakeCcxt.created.append(self)

    def load_markets(self):
        swap = {"swap": True, "linear": True, "quote": "USDT", "active": True}
        return {
            "BTC/USDT:USDT": dict(swap, symbol="BTC/USDT:USDT"),
            "ETH/USDT:USDT": dict(swap, symbol="ETH/USDT:USDT"),
            "BTC/USDT": {"spot": True, "swap": False, "quote": "USDT", "active": True},
        }

    def fetch_ohlcv(self, symbol, timeframe, limit=None):
        return synthetic_klines(now_ms(), limit or 3, as_text=False)

    def fetch_funding_rate(self, symbol):
        return {"symbol": symbol, "fundingRate": 0.0001}

    def fetch_open_interest(self, symbol):
        return {"symbol": symbol, "openInterestAmount": 51234.5}

    def fetch_order_book(self, symbol, limit=None):
        return {"bids": [[74000.0, 1.0]], "asks": [[74000.1, 1.0]]}

    def fetch_balance(self, params=None):
        assert self.config.get("apiKey"), "özel çağrı anahtarsız yapıldı"
        return {"USDT": {"free": 10.0, "total": 10.0}}
