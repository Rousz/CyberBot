"""WEEX USDT-M açık REST verisi (https://api-contract.weex.com, capi/v3/market/...).

Freqtrade aynı IP'yi kullandığı için yük çok küçük tutulur (~0.15 istek/sn ortalama):
- premiumIndex (sembolsüz, tek çağrı = tüm semboller) her 60 sn -> weex_premium
  (izlenen semboller). WEEX erişilebilirliği (izleme) de bu sonuçlardan çıkar.
- openInterest sembol başına her 5 dk, mum kapanışından ~30 sn önce -> weex_oi.
  Birimi doğrulanmadı (coin mi kontrat mı): ham saklanır (oi_raw).
- fundingRate geçmişi: açılışta bir kez (limit 1000) ve her ödeme sonrası
  (nextFundingTime + 2 dk) -> weex_funding_hist.
- exchangeInfo + ticker/24hr (pahalı) saatte bir: izlenen semboller.
Ham alanlar saklanır (ccxt parse_funding_rate zaman alanlarını karıştırıyor).
WEEX premium/OI geçmişi yoktur: kaçan an geri gelmez (gaps: unrecoverable).
"""

from __future__ import annotations

import logging
from typing import Any

from cyberbot.recorder.db import MIN_MS, to_float, to_int
from cyberbot.recorder.limiter import Clock, HttpClient, RateLimiter, retry_after_s
from cyberbot.recorder.monitor import SourceHealth, Status

logger = logging.getLogger(__name__)

BAR_MS = 300_000
FUNDING_SAFETY_MS = 60_000          # funding avail_ms = ödeme + gecikme (2 dk) + 60 sn
FUNDING_LIVE_WINDOW_MS = 30 * 60_000  # ödemeden bu kadar içinde çekilen satır "canlı" sayılır
P_EXCHANGE_INFO = "/capi/v3/market/exchangeInfo"
P_TICKER_24HR = "/capi/v3/market/ticker/24hr"
P_PREMIUM = "/capi/v3/market/premiumIndex"
P_OPEN_INTEREST = "/capi/v3/market/openInterest"
P_FUNDING = "/capi/v3/market/fundingRate"


def is_error_payload(data: Any) -> bool:
    """WEEX hata gövdesi: {"code": "-1121", "msg": "..."} (başarı zarfı code 200/0 hariç)."""
    if not isinstance(data, dict) or "msg" not in data or "code" not in data:
        return False
    return str(data.get("code")) not in ("0", "200", "00000")


def unwrap(data: Any) -> Any:
    """Bazı uçlar {"code":"200","data":[...]} zarfı dönebilir."""
    if isinstance(data, dict) and "data" in data and not is_error_payload(data):
        return data["data"]
    return data


def parse_premium(rows: Any, recv_ms: int, symbols: set[str] | None = None) -> list[dict]:
    out = []
    for row in rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else []:
        if not isinstance(row, dict) or not row.get("symbol"):
            continue
        sym = str(row["symbol"])
        if symbols is not None and sym not in symbols:
            continue
        out.append({
            "symbol": sym, "bucket_ms": recv_ms - recv_ms % MIN_MS, "server_ms": to_int(row.get("time")),
            "recv_ms": recv_ms, "mark": to_float(row.get("markPrice")), "idx": to_float(row.get("indexPrice")),
            "last_funding": to_float(row.get("lastFundingRate")),
            "forecast_funding": to_float(row.get("forecastFundingRate")),
            "interest_rate": to_float(row.get("interestRate")),
            "next_funding_ms": to_int(row.get("nextFundingTime")),
            "collect_cycle_min": to_int(row.get("collectCycle")),
            "avail_ms": recv_ms,
        })
    return out


def parse_oi(data: Any, symbol: str, recv_ms: int, mark: float | None) -> dict | None:
    rows = data if isinstance(data, list) else [data]
    for row in rows:
        if isinstance(row, dict) and row.get("symbol", symbol) == symbol:
            oi = to_float(row.get("openInterest"))
            if oi is None:
                return None
            return {"symbol": symbol, "bucket_ms": recv_ms - recv_ms % BAR_MS, "server_ms": to_int(row.get("time")),
                    "recv_ms": recv_ms, "oi_raw": oi, "mark": mark, "avail_ms": recv_ms}
    return None


def funding_avail_ms(funding_ms: int, recv_ms: int, delay_ms: int) -> int:
    """Canlıda çekilen satır (ödemeden en fazla 30 dk sonra): max(recv_ms, ödeme + gecikme + 60 sn),
    yani kaydedicinin gerçekten elinde olduğu andan önce değil. Sonradan toplu çekilen geçmiş satır:
    deterministik ödeme + gecikme + 60 sn (Binance /futures/data kuralı gibi)."""
    deterministic = funding_ms + delay_ms + FUNDING_SAFETY_MS
    if recv_ms - funding_ms <= FUNDING_LIVE_WINDOW_MS:
        return max(recv_ms, deterministic)
    return deterministic


def parse_funding(rows: Any, symbol: str, recv_ms: int, delay_ms: int = 120_000) -> list[dict]:
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("symbol", symbol) != symbol:
            continue
        t = to_int(row.get("fundingTime"))
        if t is None or t > recv_ms:
            continue
        out.append({"symbol": symbol, "funding_ms": t, "rate": to_float(row.get("fundingRate")),
                    "mark": to_float(row.get("markPrice")), "recv_ms": recv_ms,
                    "avail_ms": funding_avail_ms(t, recv_ms, delay_ms)})
    return out


def oi_due_ms(now_ms: int, lead_s: float) -> int:
    """Bir sonraki OI turu: bir sonraki 5m kapanışından lead_s önce (şu andan sonraki ilk)."""
    lead = int(lead_s * 1000)
    t = now_ms - now_ms % BAR_MS + BAR_MS - lead
    return t if t > now_ms else t + BAR_MS


class FundingSchedule:
    """Hangi sembolün funding geçmişi ne zaman çekilecek. Ödeme anı (nextFundingTime)
    premium verisinden öğrenilir; ödeme + delay geçince bir kez çekilir. Ödemeden sonra
    premium bir sonraki ödemeyi gösterse de bekleyen ödeme unutulmaz."""

    def __init__(self, delay_ms: int, retry_ms: int = 60_000):
        self.delay_ms = delay_ms
        self.retry_ms = retry_ms
        self.awaiting: dict[str, int] = {}   # sembol -> henüz çekilmemiş ödeme anı
        self.done: dict[str, int] = {}       # sembol -> son işlenen ödeme anı
        self.fetched_once: set[str] = set()
        self.not_before: dict[str, int] = {}

    def observe(self, symbol: str, next_funding_ms: int | None) -> None:
        if not next_funding_ms:
            return
        pending = self.awaiting.get(symbol)
        if pending is None or pending <= self.done.get(symbol, 0):
            if next_funding_ms > self.done.get(symbol, 0):
                self.awaiting[symbol] = next_funding_ms

    def due(self, now_ms: int, tracked: list[str]) -> list[str]:
        out = []
        for sym in tracked:
            if now_ms < self.not_before.get(sym, 0):
                continue
            if sym not in self.fetched_once:
                out.append(sym)
                continue
            t = self.awaiting.get(sym)
            if t is not None and t > self.done.get(sym, 0) and now_ms >= t + self.delay_ms:
                out.append(sym)
        return out

    def mark(self, symbol: str, now_ms: int, ok: bool) -> None:
        if not ok:
            self.not_before[symbol] = now_ms + self.retry_ms
            return
        self.fetched_once.add(symbol)
        self.not_before.pop(symbol, None)
        t = self.awaiting.get(symbol)
        if t is not None and now_ms >= t + self.delay_ms:
            self.done[symbol] = t
            self.awaiting.pop(symbol, None)


class WeexRest:
    def __init__(self, http: HttpClient, cfg: dict, clock: Clock, status: Status, log_sink: list | None = None):
        self.http = http
        self.cfg = cfg
        self.clock = clock
        self.health: SourceHealth = status.weex
        self.log_sink = log_sink if log_sink is not None else []
        self.base = cfg["rest_url"].rstrip("/")
        self.limiter = RateLimiter(clock, max_rps=float(cfg["max_rps"]), window_s=float(cfg["window_s"]),
                                   window_max=int(cfg["window_max"]), name="WEEX REST")

    async def get(self, path: str, params: dict | None = None, *, symbol: str = "") -> tuple[int, Any]:
        """(http durum, veri); ağ hatasında (0, None). Asla istisna fırlatmaz."""
        await self.limiter.acquire()
        now = self.clock.now_ms()
        label = path.rsplit("/market/", 1)[-1]
        try:
            resp = await self.http.get(self.base + path, params)
        except Exception as exc:
            self.health.fail(now, f"{type(exc).__name__}: {exc}"[:200])
            self.log_sink.append((now, "weex:" + label, symbol, 0, None, None, None, 0))
            return 0, None
        data = unwrap(resp.data)
        rows = len(data) if isinstance(data, list) else None
        self.log_sink.append((now, "weex:" + label, symbol, resp.status, int(resp.ms), rows, None, 0))
        if resp.status == 429:
            self.limiter.pause(retry_after_s(resp.headers, 30.0), now, "HTTP 429")
            self.health.fail(now, "HTTP 429 (hız sınırı)")
            return 429, None
        if resp.status >= 500 or resp.status in (401, 403):
            self.health.fail(now, f"HTTP {resp.status}")
            return resp.status, None
        self.health.ok(now)  # sunucu cevap verdi
        if resp.status >= 400 or is_error_payload(data):
            logger.warning("WEEX %s %s: HTTP %s %s", label, symbol, resp.status, str(resp.data)[:200])
            return resp.status if resp.status >= 400 else 400, None
        return resp.status, data

    async def exchange_info(self) -> Any:
        status, data = await self.get(P_EXCHANGE_INFO)
        return data if status == 200 else None

    async def ticker_24hr(self) -> Any:
        status, data = await self.get(P_TICKER_24HR)
        return data if status == 200 else None

    async def premium_index(self) -> tuple[int, Any]:
        """(recv_ms, satırlar) veya (recv_ms, None)."""
        status, data = await self.get(P_PREMIUM)
        return self.clock.now_ms(), (data if status == 200 else None)

    async def open_interest(self, symbol: str) -> tuple[int, Any]:
        status, data = await self.get(P_OPEN_INTEREST, {"symbol": symbol}, symbol=symbol)
        return self.clock.now_ms(), (data if status == 200 else None)

    async def funding_history(self, symbol: str, start_ms: int | None, limit: int) -> tuple[int, Any]:
        params: dict = {"symbol": symbol, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        status, data = await self.get(P_FUNDING, params, symbol=symbol)
        return self.clock.now_ms(), (data if status == 200 else None)
