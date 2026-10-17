"""Faz 0 bağlantı testi: WEEX (web + REST + WebSocket + ccxt), Binance vadeli
(herkese açık REST + 2026'da bölünen yeni WebSocket adresleri) ve Telegram.

SADECE PC'de çalışır: 01_connection_test.bat -> Docker.
VM'de ÇALIŞTIRILMAZ (borsalara istek atar). VM'deki birim testleri ağ
katmanını sahte (fixture) cevaplarla değiştirir.

Bu test sadece okur: emir göndermez, hiçbir ayarı değiştirmez.

Adresler ezberden değil, kütüphanelerin güncel kaynak kodundan alındı
(ccxt 4.5.84 / 4.5.88, Ekim 2026):
- WEEX vadeli REST : https://api-contract.weex.com/capi/v3/...
- WEEX vadeli WS   : wss://ws-contract.weex.com/v3/ws/public (User-Agent başlığı şart, JSON ping -> PONG)
- Binance USDⓈ-M WS: /public (depth, bookTicker, trade), /market (kline, aggTrade,
  markPrice, forceOrder), /private (kullanıcı verisi). Eski wss://fstream.binance.com/ws kapandı.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from cyberbot.report import (
    FAIL,
    INFO,
    OK,
    SKIP,
    WARN,
    Outcome,
    Report,
    UserFacingError,
    describe_error,
)
from cyberbot.timeutil import fmt_both, from_ms, utc_now

WEEX_WEB = "https://www.weex.com/"
WEEX_CONTRACT = "https://api-contract.weex.com"
WEEX_SPOT = "https://api-spot.weex.com"
WEEX_WS_PUBLIC = "wss://ws-contract.weex.com/v3/ws/public"

BINANCE_FAPI = "https://fapi.binance.com"
BINANCE_WS_PUBLIC = "wss://fstream.binance.com/public/ws"
BINANCE_WS_MARKET = "wss://fstream.binance.com/market/ws"
BINANCE_WS_LEGACY = "wss://fstream.binance.com/ws"
BINANCE_VISION = "https://data.binance.vision"
BINANCE_FUTURES_DATA = (
    "openInterestHist",
    "globalLongShortAccountRatio",
    "topLongShortAccountRatio",
    "topLongShortPositionRatio",
    "takerlongshortRatio",
)

TELEGRAM_API = "https://api.telegram.org"

SECRET_ENV_KEYS = ("TELEGRAM_TOKEN", "WEEX_API_KEY", "WEEX_API_SECRET", "WEEX_API_PASSPHRASE")

USER_AGENT = "CyberBot-connection-test/0.1"
HTTP_TIMEOUT = 15
WS_TIMEOUT = 15.0
LIQUIDATION_WAIT = 30.0
FIVE_MIN_MS = 5 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
HISTORY_PROBE_DAYS = (3, 7, 14, 30, 60, 90, 180, 365, 730, 1095)
WEEX_HISTORY_LIMIT = 100  # historyKlines istek başına en fazla 100 mum
CLOCK_WARN_MS = 1000
TOP_N = 40
REQUEST_PAUSE = 0.25  # art arda isteklerde bekleme (rate limit'e saygı); testlerde 0

# --------------------------------------------------------------------------
# Ağ katmanı (testlerde sahtesiyle değiştirilir)
# --------------------------------------------------------------------------

_HTTP_HINTS = {
    451: "bölge engeli: bu IP'nin bulunduğu ülkeye hizmet verilmiyor",
    403: "erişim reddedildi: IP/bölge engeli ya da bot koruması olabilir",
    418: "IP geçici olarak yasaklandı (çok fazla istek)",
    429: "istek sınırı aşıldı (rate limit)",
}


class HttpStatusError(UserFacingError):
    def __init__(self, status: int, body: str = ""):
        self.status = status
        hint = _HTTP_HINTS.get(status)
        message = f"HTTP {status}" + (f" – {hint}" if hint else "")
        body = " ".join((body or "").split())
        if body and not body.lstrip().startswith("<"):
            message += f" | {body[:150]}"
        super().__init__(message)


@dataclass
class HttpResult:
    data: Any
    status: int
    ms: float
    url: str  # yönlendirmelerden sonraki son adres
    t_local_ms: int  # isteğin ortasındaki yerel saat (saat farkı ölçümü için)


@dataclass
class WsResult:
    ms_open: float
    first: Any | None  # kabul edilen ilk veri mesajı; süre dolduysa None
    ms_first: float | None


class Transport:
    """Gerçek ağ erişimi: requests (REST) + websockets (WS)."""

    def __init__(self) -> None:
        import requests

        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def get(self, url: str, params: dict | None = None, *, expect_json: bool = True, method: str = "GET") -> HttpResult:
        wall0 = time.time()
        t0 = time.perf_counter()
        response = self.session.request(method, url, params=params, timeout=HTTP_TIMEOUT, allow_redirects=True)
        elapsed = time.perf_counter() - t0
        if response.status_code >= 400:
            raise HttpStatusError(response.status_code, response.text)
        data = response.json() if expect_json else response.text
        return HttpResult(data, response.status_code, elapsed * 1000, response.url, int((wall0 + elapsed / 2) * 1000))

    def post_json(self, url: str, payload: dict) -> HttpResult:
        wall0 = time.time()
        t0 = time.perf_counter()
        response = self.session.post(url, json=payload, timeout=HTTP_TIMEOUT)
        elapsed = time.perf_counter() - t0
        if response.status_code >= 400:
            raise HttpStatusError(response.status_code, response.text)
        return HttpResult(response.json(), response.status_code, elapsed * 1000, response.url, int((wall0 + elapsed / 2) * 1000))

    def ws(
        self,
        url: str,
        *,
        subscribe: list[dict] | None = None,
        headers: dict | None = None,
        accept: Callable[[Any], bool],
        ping_reply: Callable[[Any], dict | None] | None = None,
        timeout: float = WS_TIMEOUT,
    ) -> WsResult:
        return asyncio.run(ws_probe(url, subscribe, headers, accept, ping_reply, timeout))


async def ws_probe(
    url: str,
    subscribe: list[dict] | None,
    headers: dict | None,
    accept: Callable[[Any], bool],
    ping_reply: Callable[[Any], dict | None] | None,
    timeout: float,
) -> WsResult:
    """Bağlanır, abonelik mesajlarını yollar, accept() kabul edene kadar ya da
    süre dolana kadar mesaj okur. JSON ping'lere ping_reply() ile cevap verir."""
    try:
        from websockets.asyncio.client import connect

        header_kw = {"additional_headers": headers or {}}
    except ImportError:  # websockets < 13
        from websockets import connect

        header_kw = {"extra_headers": headers or {}}

    t0 = time.perf_counter()
    deadline = t0 + timeout
    async with connect(url, open_timeout=timeout, max_size=2**23, **header_kw) as ws:
        ms_open = (time.perf_counter() - t0) * 1000
        for message in subscribe or []:
            await ws.send(json.dumps(message))
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return WsResult(ms_open, None, None)
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except TimeoutError:
                return WsResult(ms_open, None, None)
            try:
                message = json.loads(raw)
            except (TypeError, ValueError):
                continue
            reply = ping_reply(message) if ping_reply else None
            if reply is not None:
                await ws.send(json.dumps(reply))
                continue
            if accept(message):
                return WsResult(ms_open, message, (time.perf_counter() - t0) * 1000)


# --------------------------------------------------------------------------
# Saf yardımcılar (VM'de birim testli)
# --------------------------------------------------------------------------


def as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    return [value] if value else []


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def weex_ping_reply(message: Any) -> dict | None:
    if isinstance(message, dict) and (message.get("event") == "ping" or message.get("type") == "ping"):
        return {"id": int(time.time() * 1000) % 1_000_000, "method": "PONG"}
    return None


def event_is(name: str) -> Callable[[Any], bool]:
    return lambda message: isinstance(message, dict) and message.get("e") == name


def weex_usdt_perps(exchange_info: Any) -> list[str]:
    symbols = exchange_info.get("symbols", []) if isinstance(exchange_info, dict) else []
    return sorted(
        s["symbol"]
        for s in symbols
        if s.get("symbol") and s.get("quoteAsset") == "USDT" and s.get("marginAsset", "USDT") == "USDT"
    )


def binance_usdt_perps(exchange_info: Any) -> list[str]:
    symbols = exchange_info.get("symbols", []) if isinstance(exchange_info, dict) else []
    return sorted(
        s["symbol"]
        for s in symbols
        if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING"
    )


def top_by_quote_volume(tickers: Any, n: int) -> list[tuple[str, float]]:
    rows = [(t.get("symbol"), to_float(t.get("quoteVolume"))) for t in as_list(tickers) if isinstance(t, dict)]
    rows = [(s, v) for s, v in rows if s and v is not None]
    return sorted(rows, key=lambda row: row[1], reverse=True)[:n]


def book_stats(depth: Any, band: float = 0.005) -> dict[str, float]:
    """Spread (baz puan) ve orta fiyatın ±band içindeki alış/satış derinliği (USDT)."""
    bids = [(float(p), float(q)) for p, q, *_ in depth.get("bids", [])]
    asks = [(float(p), float(q)) for p, q, *_ in depth.get("asks", [])]
    if not bids or not asks:
        raise ValueError("emir defteri boş")
    best_bid = max(p for p, _ in bids)
    best_ask = min(p for p, _ in asks)
    mid = (best_bid + best_ask) / 2
    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_bps": (best_ask - best_bid) / mid * 10_000,
        "bid_usdt": sum(p * q for p, q in bids if p >= mid * (1 - band)),
        "ask_usdt": sum(p * q for p, q in asks if p <= mid * (1 + band)),
    }


def klines_stats(rows: Any, step_ms: int) -> tuple[int, int, int, int]:
    """(adet, ilk açılış ms, son açılış ms, boşluk sayısı). Biçim bozuksa ValueError."""
    rows = as_list(rows)
    if not rows:
        raise ValueError("mum gelmedi")
    times = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise ValueError(f"beklenmeyen mum biçimi: {str(row)[:80]}")
        times.append(int(row[0]))
    times.sort()
    gaps = sum(1 for a, b in zip(times, times[1:]) if b - a != step_ms)
    return len(times), times[0], times[-1], gaps


def probe_history_depth(
    has_data: Callable[[int], bool],
    probe_days: tuple[int, ...] = HISTORY_PROBE_DAYS,
    resolution_days: int = 2,
) -> tuple[int, bool]:
    """Geçmişte kaç gün geriye veri olduğunu bulur: (gün, en_uzak_noktada_bile_var_mı).
    Önce kaba adımlarla, sonra son başarılı ile ilk başarısız arasında ikili aramayla."""
    last_ok, first_fail = 0, None
    for days in probe_days:
        if has_data(days):
            last_ok = days
        else:
            first_fail = days
            break
    if first_fail is None:
        return last_ok, True
    lo, hi = last_ok, first_fail
    while hi - lo > resolution_days:
        mid = (lo + hi) // 2
        if has_data(mid):
            lo = mid
        else:
            hi = mid
    return lo, False


def pct_diff(a: float, b: float) -> float:
    return (a - b) / b * 100


def trim_sample(obj: Any, n: int = 3) -> Any:
    """Örnek cevabı küçültür: konteyner listelerinden ilk n eleman kalır,
    sayı listelerine (ör. bir mum satırı) dokunulmaz."""
    if isinstance(obj, dict):
        return {k: trim_sample(v, n) for k, v in obj.items()}
    if isinstance(obj, list):
        if any(isinstance(x, (list, dict)) for x in obj):
            return [trim_sample(x, n) for x in obj[:n]]
        return obj
    return obj


def lib_versions() -> dict[str, str]:
    versions = {}
    for name in ("freqtrade", "ccxt", "websockets", "requests"):
        try:
            versions[name] = str(__import__(name).__version__)
        except Exception:
            versions[name] = "yok"
    return versions


def previous_month(now=None) -> str:
    now = now or utc_now()
    first = now.replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


# --------------------------------------------------------------------------
# Test adımları
# --------------------------------------------------------------------------


def save_sample(rep: Report, name: str, data: Any) -> None:
    """Herkese açık cevaplardan küçük örnekler: VM'deki birim testleri için fixture olur."""
    try:
        folder = rep.reports_dir / "samples"
        folder.mkdir(parents=True, exist_ok=True)
        text = json.dumps(trim_sample(data), indent=1, ensure_ascii=False)
        (folder / f"{name}.json").write_text(rep.redact(text) + "\n", encoding="utf-8", newline="\n")
    except Exception as exc:  # örnek kaydı testin sonucunu etkilemez
        rep.log.warning("örnek kaydedilemedi (%s): %s", name, exc)


def clock_outcome(rep: Report, label: str, server_ms: int, result: HttpResult) -> str | Outcome:
    offset = server_ms - result.t_local_ms
    rep.finding(f"Saat farkı ({label} sunucusu − bu bilgisayar)", f"{offset:+d} ms")
    detail = f"sunucu saati {fmt_both(from_ms(server_ms))}, fark {offset:+d} ms"
    if abs(offset) > CLOCK_WARN_MS:
        return Outcome(WARN, detail + " – Windows saatini eşitle; düzelmezse Docker Desktop'ı yeniden başlat")
    return detail


def run_weex(rep: Report, t: Transport, ctx: dict) -> None:
    g = "WEEX"

    def web():
        try:
            r = t.get(WEEX_WEB, expect_json=False)
        except HttpStatusError as exc:
            return Outcome(WARN, f"{exc} – tarayıcıdan https://www.weex.com adresini açıp kontrol et")
        final = r.url.lower()
        suspicious = [w for w in ("restrict", "forbidden", "unavailable", "not-available", "blocked", "compliance") if w in final]
        if suspicious:
            return Outcome(WARN, f"açıldı ama şüpheli yönlendirme: {r.url}")
        return f"açıldı (HTTP {r.status}) → {r.url}"

    rep.run(g, "web_sitesi", web, critical=False)

    def server_time():
        r = t.get(f"{WEEX_CONTRACT}/capi/v3/market/time")
        return clock_outcome(rep, "WEEX", int(r.data["serverTime"]), r)

    if rep.run(g, "rest_saat", server_time).status == FAIL:
        rep.add(g, "rest_diger", SKIP, "WEEX vadeli REST'e ulaşılamadı; diğer REST testleri atlandı")
    else:
        run_weex_rest(rep, t, ctx)

    def spot_time():
        r = t.get(f"{WEEX_SPOT}/api/v3/time")
        return f"spot API erişilebilir (ccxt piyasa listesi için gerekli), sunucu {fmt_both(from_ms(int(r.data['serverTime'])))}"

    rep.run(g, "rest_spot", spot_time, critical=False)

    def ws():
        res = t.ws(
            WEEX_WS_PUBLIC,
            subscribe=[{"id": 1, "method": "SUBSCRIBE", "params": ["BTCUSDT@ticker"]}],
            headers={"User-Agent": USER_AGENT},
            accept=event_is("ticker"),
            ping_reply=weex_ping_reply,
        )
        if res.first is None:
            return Outcome(FAIL, f"bağlandı ({res.ms_open:.0f} ms) ama {WS_TIMEOUT:.0f} sn içinde fiyat gelmedi")
        save_sample(rep, "weex_ws_ticker", res.first)
        return f"bağlandı {res.ms_open:.0f} ms, ilk BTCUSDT fiyatı {res.ms_first:.0f} ms"

    rep.run(g, "websocket", ws)


def run_weex_rest(rep: Report, t: Transport, ctx: dict) -> None:
    g = "WEEX"

    def contracts():
        r = t.get(f"{WEEX_CONTRACT}/capi/v3/market/exchangeInfo")
        save_sample(rep, "weex_exchangeInfo", r.data)
        perps = weex_usdt_perps(r.data)
        ctx["weex_perps"] = perps
        if "BTCUSDT" not in perps:
            return Outcome(FAIL, f"{len(perps)} USDT kontratı var ama BTCUSDT yok – cevap biçimi değişmiş olabilir")
        rep.finding("WEEX USDT-M perpetual sayısı", str(len(perps)))
        return f"{len(perps)} USDT-M perpetual kontrat"

    rep.run(g, "rest_kontratlar", contracts)

    def tickers():
        r = t.get(f"{WEEX_CONTRACT}/capi/v3/market/ticker/24hr")
        rows = [x for x in as_list(r.data) if isinstance(x, dict)]
        save_sample(rep, "weex_ticker_24hr", rows)
        ctx["weex_last"] = {x["symbol"]: to_float(x.get("lastPrice")) for x in rows if x.get("symbol")}
        top = top_by_quote_volume(rows, TOP_N)
        ctx["weex_top"] = [s for s, _ in top]
        if not top:
            return Outcome(FAIL, "24 saatlik hacim verisi okunamadı")
        rep.finding(
            f"WEEX hacimde ilk {TOP_N}",
            f"en büyük {top[0][0]} {top[0][1] / 1e6:,.0f}M$, {len(top)}. sıradaki {top[-1][0]} {top[-1][1] / 1e6:,.1f}M$",
        )
        first5 = ", ".join(f"{s} {v / 1e6:,.0f}M$" for s, v in top[:5])
        return f"{len(rows)} parite; ilk 5: {first5}"

    rep.run(g, "rest_24s_hacim", tickers)

    def klines():
        r = t.get(f"{WEEX_CONTRACT}/capi/v3/market/klines", {"symbol": "BTCUSDT", "interval": "5m", "limit": 1000})
        save_sample(rep, "weex_klines_5m", as_list(r.data)[:5])
        n, first, last, gaps = klines_stats(r.data, FIVE_MIN_MS)
        return f"{n} adet 5m mum: {fmt_both(from_ms(first))} → {fmt_both(from_ms(last))}, boşluk {gaps}"

    rep.run(g, "rest_mum_5m", klines)

    def history():
        now_ms = int(time.time() * 1000)

        def has_data(days: int) -> bool:
            start = now_ms - days * DAY_MS
            end = start + WEEX_HISTORY_LIMIT * FIVE_MIN_MS
            try:
                r = t.get(
                    f"{WEEX_CONTRACT}/capi/v3/market/historyKlines",
                    {"symbol": "BTCUSDT", "interval": "5m", "startTime": start, "endTime": end},
                )
            except HttpStatusError as exc:
                if exc.status in (400, 404):
                    return False
                raise
            finally:
                time.sleep(REQUEST_PAUSE)
            rows = [row for row in as_list(r.data) if isinstance(row, (list, tuple)) and row]
            if days == HISTORY_PROBE_DAYS[0]:
                save_sample(rep, "weex_historyKlines_5m", rows[:5])
            # API pencere dışından (ör. en yeni) mum döndürürse "veri yok" sayılır
            return any(start - FIVE_MIN_MS <= int(row[0]) <= end for row in rows)

        days, open_ended = probe_history_depth(has_data)
        ctx["weex_history_days"] = days
        if days == 0:
            rep.finding("WEEX 5m mum geçmişi", "alınamadı → backtest Binance verisiyle yapılacak")
            return Outcome(WARN, "geçmiş mum uç noktası veri vermedi → backtest Binance verisiyle yapılacak")
        oldest = (utc_now() - timedelta(days=days)).strftime("%Y-%m-%d")
        text = f"en az {days} gün" + (" (daha eskisi de olabilir)" if open_ended else f" (yaklaşık {oldest} tarihine kadar)")
        requests_needed = days * 288 // WEEX_HISTORY_LIMIT
        rep.finding(
            "WEEX 5m mum geçmişi",
            f"{text}; tamamını indirmek parite başına ≈{requests_needed:,} istek ({TOP_N} parite ≈{requests_needed * TOP_N:,})",
        )
        if days < 90:
            return Outcome(WARN, f"5m geçmişi {text} – backtest için kısa, Binance verisi kullanılacak")
        return f"5m geçmişi {text}"

    rep.run(g, "rest_mum_gecmisi", history, critical=False)

    def depth():
        r = t.get(f"{WEEX_CONTRACT}/capi/v3/market/depth", {"symbol": "BTCUSDT", "limit": 200})
        save_sample(rep, "weex_depth", r.data)
        s = book_stats(r.data)
        return (
            f"BTCUSDT spread {s['spread_bps']:.2f} baz puan, ±%0.5 derinlik: "
            f"alış {s['bid_usdt'] / 1e3:,.0f}k$, satış {s['ask_usdt'] / 1e3:,.0f}k$"
        )

    rep.run(g, "rest_emir_defteri", depth)

    def funding():
        r = t.get(f"{WEEX_CONTRACT}/capi/v3/market/premiumIndex", {"symbol": "BTCUSDT"})
        save_sample(rep, "weex_premiumIndex", r.data)
        row = as_list(r.data)[0]
        rate = float(row["lastFundingRate"])
        cycle = to_float(row.get("collectCycle"))
        period = f"{cycle / 60:g} saat" if cycle else "?"
        return f"BTCUSDT son funding %{rate * 100:.4f}, sonraki {fmt_both(from_ms(int(row['nextFundingTime'])))}, periyot {period}"

    rep.run(g, "rest_funding", funding, critical=False)

    def open_interest():
        r = t.get(f"{WEEX_CONTRACT}/capi/v3/market/openInterest", {"symbol": "BTCUSDT"})
        save_sample(rep, "weex_openInterest", r.data)
        row = as_list(r.data)[0]
        return f"BTCUSDT açık pozisyon (OI) {float(row['openInterest']):,.0f} – geçmişi yok, kendimiz kaydedeceğiz"

    rep.run(g, "rest_open_interest", open_interest, critical=False)


def run_weex_ccxt(rep: Report, ctx: dict, secrets: dict, factory: Callable[[dict], Any] | None) -> None:
    """Freqtrade'in kullanacağı yol: ccxt.weex. Ağ erişimi ccxt'nin kendisi üzerinden."""
    g = "WEEX-ccxt"
    if factory is None:
        try:
            import ccxt
        except ImportError:
            rep.add(g, "ccxt", FAIL, "ccxt kütüphanesi bulunamadı")
            return
        if not hasattr(ccxt, "weex"):
            rep.add(g, "ccxt", FAIL, f"bu ccxt sürümünde ({ccxt.__version__}) weex yok")
            return
        factory = ccxt.weex
    base = {"enableRateLimit": True, "timeout": HTTP_TIMEOUT * 1000, "options": {"defaultType": "swap"}}
    symbol = "BTC/USDT:USDT"
    holder: dict[str, Any] = {}

    def markets():
        ex = factory(dict(base))
        holder["ex"] = ex
        loaded = ex.load_markets()
        swaps = [
            m
            for m in loaded.values()
            if m.get("swap") and m.get("linear") and m.get("quote") == "USDT" and m.get("active") is not False
        ]
        if symbol not in loaded:
            return Outcome(FAIL, f"{len(swaps)} USDT-M perpetual var ama {symbol} yok")
        return f"{len(swaps)} USDT-M perpetual (sembol biçimi: {symbol})"

    if rep.run(g, "load_markets", markets).status != OK:
        rep.add(g, "diger", SKIP, "load_markets başarısız olduğu için diğer ccxt testleri atlandı")
        return
    ex = holder["ex"]

    def ohlcv():
        rows = ex.fetch_ohlcv(symbol, "5m", limit=3)
        n, _, last, _ = klines_stats(rows, FIVE_MIN_MS)
        return f"{n} mum, son açılış {fmt_both(from_ms(last))}"

    def funding_rate():
        fr = ex.fetch_funding_rate(symbol)
        return f"funding %{float(fr['fundingRate']) * 100:.4f}"

    def open_interest():
        oi = ex.fetch_open_interest(symbol)
        return f"OI {float(oi.get('openInterestAmount') or 0):,.0f}"

    def order_book():
        book = ex.fetch_order_book(symbol, limit=5)
        return f"en iyi alış {book['bids'][0][0]}, en iyi satış {book['asks'][0][0]}"

    rep.run(g, "fetch_ohlcv", ohlcv)
    rep.run(g, "fetch_funding_rate", funding_rate, critical=False)
    rep.run(g, "fetch_open_interest", open_interest, critical=False)
    rep.run(g, "fetch_order_book", order_book)

    keys = [secrets.get(k) for k in ("WEEX_API_KEY", "WEEX_API_SECRET", "WEEX_API_PASSPHRASE")]
    if all(keys):

        def balance():
            private = factory({**base, "apiKey": keys[0], "secret": keys[1], "password": keys[2]})
            private.fetch_balance({"type": "swap"})
            return "API anahtarı geçerli, vadeli bakiye okunabildi (tutar rapora yazılmaz, emir gönderilmez)"

        rep.run(g, "ozel_api_bakiye", balance)
    elif any(keys):
        rep.add(g, "ozel_api_bakiye", WARN, "WEEX API bilgileri eksik: key, secret ve passphrase üçü birden gerekli")
    else:
        rep.add(g, "ozel_api_bakiye", SKIP, "WEEX API anahtarı yok (demo test için gerekmez)")


def run_binance(rep: Report, t: Transport, ctx: dict) -> None:
    g = "Binance"

    def server_time():
        r = t.get(f"{BINANCE_FAPI}/fapi/v1/time")
        return clock_outcome(rep, "Binance", int(r.data["serverTime"]), r)

    if rep.run(g, "rest_saat", server_time).status == FAIL:
        rep.add(g, "rest_diger", SKIP, "Binance vadeli REST'e ulaşılamadı; diğer REST testleri atlandı")
    else:
        run_binance_rest(rep, t, ctx)

    def ws_market():
        stream = "btcusdt@kline_5m"
        res = t.ws(
            f"{BINANCE_WS_MARKET}/{stream}",
            subscribe=[{"method": "SUBSCRIBE", "params": [stream], "id": 1}],
            accept=event_is("kline"),
        )
        if res.first is None:
            return Outcome(FAIL, f"bağlandı ({res.ms_open:.0f} ms) ama {WS_TIMEOUT:.0f} sn içinde mum gelmedi")
        save_sample(rep, "binance_ws_kline", res.first)
        return f"/market adresi çalışıyor: bağlantı {res.ms_open:.0f} ms, ilk mum {res.ms_first:.0f} ms"

    def ws_public():
        stream = "btcusdt@bookTicker"
        res = t.ws(
            f"{BINANCE_WS_PUBLIC}/{stream}",
            subscribe=[{"method": "SUBSCRIBE", "params": [stream], "id": 1}],
            accept=event_is("bookTicker"),
        )
        if res.first is None:
            return Outcome(FAIL, f"bağlandı ({res.ms_open:.0f} ms) ama {WS_TIMEOUT:.0f} sn içinde fiyat gelmedi")
        return f"/public adresi çalışıyor: bağlantı {res.ms_open:.0f} ms, ilk fiyat {res.ms_first:.0f} ms"

    def ws_liquidations():
        stream = "!forceOrder@arr"
        res = t.ws(
            f"{BINANCE_WS_MARKET}/{stream}",
            subscribe=[{"method": "SUBSCRIBE", "params": [stream], "id": 1}],
            accept=event_is("forceOrder"),
            timeout=LIQUIDATION_WAIT,
        )
        if res.first is None:
            return f"bağlandı ({res.ms_open:.0f} ms); {LIQUIDATION_WAIT:.0f} sn içinde likidasyon olmadı (sakin piyasada normal)"
        save_sample(rep, "binance_ws_forceOrder", res.first)
        return f"likidasyon akışı çalışıyor: ilk kayıt {res.ms_first / 1000:.1f} sn içinde geldi"

    rep.run(g, "ws_market_kline", ws_market)
    rep.run(g, "ws_public_fiyat", ws_public)
    rep.run(g, "ws_likidasyon", ws_liquidations)

    try:
        stream = "btcusdt@kline_5m"
        res = t.ws(
            f"{BINANCE_WS_LEGACY}/{stream}",
            subscribe=[{"method": "SUBSCRIBE", "params": [stream], "id": 1}],
            accept=event_is("kline"),
            timeout=8.0,
        )
        legacy = "hâlâ veri veriyor (kullanmayacağız)" if res.first is not None else "veri vermiyor (beklenen: kapandı)"
    except Exception as exc:
        legacy = f"kapalı (beklenen): {describe_error(exc, 120)}"
    rep.add(g, "ws_eski_adres", INFO, f"eski {BINANCE_WS_LEGACY} {legacy}")


def run_binance_rest(rep: Report, t: Transport, ctx: dict) -> None:
    g = "Binance"

    def exchange_info():
        r = t.get(f"{BINANCE_FAPI}/fapi/v1/exchangeInfo")
        save_sample(rep, "binance_exchangeInfo", r.data)
        perps = binance_usdt_perps(r.data)
        ctx["binance_perps"] = perps
        limits = [
            f"{x.get('rateLimitType')} {x.get('limit')}/{x.get('intervalNum')}{x.get('interval', '')[:1].lower()}"
            for x in r.data.get("rateLimits", [])
        ]
        if limits:
            rep.finding("Binance vadeli istek sınırları", ", ".join(limits))
        return f"{len(perps)} USDT-M perpetual"

    rep.run(g, "rest_kontratlar", exchange_info)

    def klines():
        r = t.get(f"{BINANCE_FAPI}/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "5m", "limit": 500})
        save_sample(rep, "binance_klines_5m", as_list(r.data)[:5])
        n, first, last, gaps = klines_stats(r.data, FIVE_MIN_MS)
        return f"{n} adet 5m mum, son açılış {fmt_both(from_ms(last))}, boşluk {gaps}"

    rep.run(g, "rest_mum_5m", klines)

    def oldest():
        r = t.get(f"{BINANCE_FAPI}/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "5m", "startTime": 0, "limit": 1})
        first = int(as_list(r.data)[0][0])
        rep.finding("Binance BTCUSDT 5m geçmişi", f"{fmt_both(from_ms(first))} tarihinden beri")
        return f"BTCUSDT 5m geçmişi {fmt_both(from_ms(first))} tarihinden beri"

    rep.run(g, "rest_mum_gecmisi", oldest, critical=False)

    def futures_data():
        ok = []
        for endpoint in BINANCE_FUTURES_DATA:
            r = t.get(f"{BINANCE_FAPI}/futures/data/{endpoint}", {"symbol": "BTCUSDT", "period": "5m", "limit": 3})
            rows = as_list(r.data)
            save_sample(rep, f"binance_{endpoint}", rows)
            if rows:
                ok.append(endpoint)
            time.sleep(REQUEST_PAUSE)
        if len(ok) < len(BINANCE_FUTURES_DATA):
            missing = sorted(set(BINANCE_FUTURES_DATA) - set(ok))
            return Outcome(WARN, f"{len(ok)}/{len(BINANCE_FUTURES_DATA)} veri verdi; boş: {', '.join(missing)}")
        return f"{len(ok)}/{len(BINANCE_FUTURES_DATA)} türev verisi uç noktası (OI, long/short, taker) veri verdi"

    rep.run(g, "rest_turev_verisi", futures_data)

    def funding():
        r = t.get(f"{BINANCE_FAPI}/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})
        save_sample(rep, "binance_premiumIndex", r.data)
        return f"BTCUSDT son funding %{float(r.data['lastFundingRate']) * 100:.4f}"

    rep.run(g, "rest_funding", funding, critical=False)

    def prices():
        r = t.get(f"{BINANCE_FAPI}/fapi/v1/ticker/price")
        rows = [x for x in as_list(r.data) if isinstance(x, dict)]
        ctx["binance_last"] = {x["symbol"]: to_float(x.get("price")) for x in rows if x.get("symbol")}
        return f"{len(rows)} paritenin son fiyatı okundu"

    rep.run(g, "rest_fiyatlar", prices, critical=False)

    def vision():
        month = previous_month()
        url = f"{BINANCE_VISION}/data/futures/um/monthly/klines/BTCUSDT/5m/BTCUSDT-5m-{month}.zip"
        t.get(url, expect_json=False, method="HEAD")
        return f"toplu geçmiş veri arşivi erişilebilir ({month} dosyası mevcut) – hızlı veri indirme için"

    rep.run(g, "veri_arsivi", vision, critical=False)


def run_cross(rep: Report, ctx: dict) -> None:
    g = "Karşılaştırma"
    weex_last, binance_last = ctx.get("weex_last") or {}, ctx.get("binance_last") or {}
    diffs = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        w, b = weex_last.get(symbol), binance_last.get(symbol)
        if w and b:
            diffs.append(f"{symbol} {pct_diff(w, b):+.3f}%")
    if diffs:
        text = "WEEX − Binance (anlık, birkaç saniye arayla): " + ", ".join(diffs)
        rep.add(g, "fiyat_farki", INFO, text)
        rep.finding("Fiyat farkı", text)

    weex, binance = set(ctx.get("weex_perps") or []), set(ctx.get("binance_perps") or [])
    if weex and binance:
        both = weex & binance
        text = f"WEEX'teki {len(weex)} USDT paritesinin {len(both)} tanesi Binance vadelide de var"
        top = ctx.get("weex_top") or []
        if top:
            text += f"; WEEX hacim ilk {len(top)} içinde {sum(1 for s in top if s in binance)} tanesi"
        rep.add(g, "ortak_pariteler", INFO, text)
        rep.finding("Ortak pariteler (türev verisi tam olanlar)", text)


def run_telegram(rep: Report, t: Transport, token: str, chat_id: str) -> str | None:
    """Bot ve chat id kontrolü. Mesaj gönderilebilecekse bot adresini döner."""
    g = "Telegram"
    if not token:
        rep.add(g, "bot", SKIP, ".env'de TELEGRAM_TOKEN yok (setup_env.bat ile ekle)")
        return None
    base = f"{TELEGRAM_API}/bot{token}"

    def get_me():
        r = t.get(f"{base}/getMe")
        if not r.data.get("ok"):
            raise UserFacingError("token geçersiz")
        return f"bot bulundu: @{r.data['result'].get('username')}"

    if rep.run(g, "bot", get_me).status != OK:
        return None
    if chat_id:
        return base

    def find_chat():
        r = t.get(f"{base}/getUpdates", {"limit": 50})
        chats: dict[Any, str] = {}
        for update in r.data.get("result", []):
            message = update.get("message") or update.get("edited_message") or update.get("channel_post") or {}
            chat = message.get("chat") or {}
            if "id" in chat:
                chats[chat["id"]] = chat.get("first_name") or chat.get("title") or chat.get("username") or ""
        if not chats:
            return Outcome(
                WARN,
                "chat id bulunamadı: Telegram'da kendi botunu aç, 'merhaba' yaz, sonra bu testi tekrar çalıştır",
            )
        lines = ["", "*" * 50, "  TELEGRAM CHAT ID (sadece ekranda, rapora yazılmaz):"]
        lines += [f"    {cid}   ({name})" for cid, name in chats.items()]
        lines += ["  Bu sayıyı .env içindeki TELEGRAM_CHAT_ID= satırına yaz,", "  kaydet ve testi tekrar çalıştır.", "*" * 50, ""]
        rep.screen_only("\n".join(lines))
        return Outcome(WARN, f"{len(chats)} sohbet bulundu; chat id ekranda gösterildi → .env'ye yaz, testi tekrarla")

    rep.run(g, "chat_id", find_chat, critical=False)
    return None


def send_telegram_summary(rep: Report, t: Transport, base: str, chat_id: str) -> None:
    def send():
        text = (
            f"CyberBot bağlantı testi: {rep.verdict()}\n"
            f"{rep.counts_text()}\n"
            f"{fmt_both(utc_now())}"
        )
        r = t.post_json(f"{base}/sendMessage", {"chat_id": chat_id, "text": text})
        if not r.data.get("ok"):
            raise UserFacingError(str(r.data.get("description", "mesaj gönderilemedi")))
        return "test mesajı gönderildi – Telegram'a bak"

    rep.run("Telegram", "mesaj_gonder", send)


# --------------------------------------------------------------------------


def main(
    transport: Transport | None = None,
    ccxt_factory: Callable[[dict], Any] | None = None,
    reports_dir: str | Path = "reports",
    env: dict | None = None,
) -> int:
    env = os.environ if env is None else env
    rep = Report("Bağlantı testi (Faz 0)", "connection_test", reports_dir)
    secrets = {key: (env.get(key) or "").strip() for key in SECRET_ENV_KEYS}
    for value in secrets.values():
        rep.add_secret(value)
    chat_id = (env.get("TELEGRAM_CHAT_ID") or "").strip()
    rep.versions.update(lib_versions())

    print(f"CyberBot bağlantı testi – {fmt_both(rep.started)}")
    print("Sadece herkese açık piyasa verisi okunur; emir gönderilmez, ayar değiştirilmez.\n")
    ctx: dict[str, Any] = {}
    try:
        t = transport or Transport()
        run_weex(rep, t, ctx)
        run_weex_ccxt(rep, ctx, secrets, ccxt_factory)
        run_binance(rep, t, ctx)
        run_cross(rep, ctx)
        telegram_base = run_telegram(rep, t, secrets["TELEGRAM_TOKEN"], chat_id)
        if telegram_base:
            send_telegram_summary(rep, t, telegram_base, chat_id)
    except KeyboardInterrupt:
        rep.add("Genel", "kesildi", FAIL, "test kullanıcı tarafından durduruldu")
    except Exception as exc:  # beklenmeyen hata: rapor yine de yazılır
        rep.log.exception("beklenmeyen hata")
        rep.add("Genel", "script_hatasi", FAIL, describe_error(exc))
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
