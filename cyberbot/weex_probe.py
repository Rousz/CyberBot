"""Faz 1 davranış probu: Freqtrade'in doğru çalışması için WEEX ve Binance'in herkese açık
uç noktalarının nasıl davrandığını ölçer (araştırma raporlarındaki "PC TESTS NEEDED" listeleri).

SADECE PC'de çalışır: 02_weex_probe.bat -> Docker (tools container).
VM'de ÇALIŞTIRILMAZ (borsalara istek atar); VM birim testleri sahte cevaplarla sürer.

Sadece herkese açık piyasa verisi okunur: API anahtarı kullanılmaz, emir gönderilmez,
hiçbir ayar değişmez. İstekler arasında kısa beklemeler var (rate limit'e saygı).

Bölümler:
- Freqtrade: gerçek Freqtrade Weex sınıfı (ExchangeResolver, dry-run futures) ile piyasalar,
  kaldıraç, contractSize, 7 günlük 5m mum sürekliliği (100'lük parça sınırları), 1h mark
  ve funding mumları, ticker bid/ask birleştirmesi.
- WEEX ham uçlar: exchangeInfo denetimi, klines/historyKlines sınırları, mark/index,
  funding geçmişi, collectCycle, ticker/bookTicker/depth, open interest birimi, sembol adları.
- Binance: /futures/data zaman damgası anlamı ve yayın gecikmesi, en eski startTime,
  limit 500, likidasyon WS yük biçimi, 1000* sembolleri.

Çıktı: reports/weex_probe_<UTC>.txt (özet, "Önemli bulgular" = kararlar) ve
reports/samples/probe_*.json (küçük herkese açık örnekler).
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cyberbot import paths
from cyberbot.connection_test import (
    BINANCE_FAPI,
    BINANCE_FUTURES_DATA,
    BINANCE_WS_MARKET,
    SECRET_ENV_KEYS,
    WEEX_CONTRACT,
    HttpStatusError,
    Transport,
    as_list,
    binance_usdt_perps,
    lib_versions,
    probe_history_depth,
    save_sample,
    to_float,
    top_by_quote_volume,
    weex_usdt_perps,
)
from cyberbot.report import FAIL, OK, SKIP, WARN, Outcome, Report, describe_error
from cyberbot.timeutil import fmt_both, from_ms

USER_AGENT = "CyberBot-weex-probe/0.1"
MIN_MS = 60_000
HOUR_MS = 60 * MIN_MS
DAY_MS = 24 * HOUR_MS
TF_MS = {"5m": 5 * MIN_MS, "1h": HOUR_MS}
HISTORY_LIMIT = 100  # historyKlines istek başına en fazla 100 mum
TOP_N = 40
REQUEST_PAUSE = 0.3  # art arda istekler arası bekleme (sn); testlerde 0
LIQ_WAIT_S = 60.0  # likidasyon akışında ilk mesaj için bekleme
FD_POLL_S = 10.0  # /futures/data yeni satır yoklama aralığı
FD_POLL_MAX_S = 330.0  # en fazla bir 5m dönem + pay
BOUNDARY_GUARD_MS = 15_000  # mum açılışına bu kadar yakınsa biraz bekle (oluşan mum testi için)
BOUNDARY_END_GUARD_MS = 5_000  # mum kapanışına bu kadar yakınsa da bekle (istek sınırı aşmasın)
RECORDER_SAFETY_S = 60  # recorder varsayılanı: avail_ms = ts + dönem + 60 sn
DEPTH_LIMITS = (None, 15, 50, 200)
MEME_BASES = ("PEPE", "SHIB", "BONK", "FLOKI", "SATS", "RATS", "CAT", "LUNC", "XEC", "BTT", "CHEEMS", "MOG")
BTC = "BTC/USDT:USDT"
ETH = "ETH/USDT:USDT"

# Ham contract exchangeInfo'da bilinen anahtarlar (ccxt 4.5.88 örnek cevabı); fazlası rapora yazılır
KNOWN_CONTRACT_KEYS = frozenset({
    "symbol", "baseAsset", "quoteAsset", "marginAsset", "pricePrecision", "quantityPrecision",
    "baseAssetPrecision", "quotePrecision", "contractVal", "delivery", "forwardContractFlag",
    "minLeverage", "maxLeverage", "buyLimitPriceRatio", "sellLimitPriceRatio", "makerFeeRate",
    "takerFeeRate", "minOrderSize", "maxOrderSize", "maxPositionSize", "marketOpenLimitSize",
})


class Clock:
    """Gerçek saat; testlerde sahtesiyle değiştirilir (bekleme anında geçer)."""

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


# --------------------------------------------------------------------------
# Saf yardımcılar (VM'de birim testli)
# --------------------------------------------------------------------------


def floor_to(ms: int, step: int) -> int:
    return ms // step * step


def ceil_to(ms: int, step: int) -> int:
    return -(-ms // step) * step


def fmt_dur(ms: float) -> str:
    s = abs(ms) / 1000
    sign = "-" if ms < 0 else ""
    if s < 120:
        return f"{sign}{s:.0f} sn"
    if s < 7200:
        return f"{sign}{s / 60:.1f} dk"
    if s < 2 * 86400:
        return f"{sign}{s / 3600:.1f} saat"
    return f"{sign}{s / 86400:.1f} gün"


@dataclass
class Continuity:
    n: int
    first: int | None
    last: int | None
    missing: list[int]
    missing_at_chunk_border: int
    head_missing: int  # beklenen ilk mumdan önce eksik olanlar

    def text(self, tf_ms: int) -> str:
        if not self.n:
            return "mum yok"
        return (f"{self.n} mum {fmt_both(from_ms(self.first))} → {fmt_both(from_ms(self.last))}, "
                f"eksik {len(self.missing)} (100'lük parça sınırında {self.missing_at_chunk_border})")


def continuity(times: list[int], tf_ms: int, since_ms: int, chunk: int = HISTORY_LIMIT) -> Continuity:
    """Mum açılış zamanları dizisinde boşluklar. Parça sınırları since'ten (yukarı yuvarlanmış)
    itibaren her chunk mumda bir: Weex alt sınıfı historyKlines'ı tam bu sınırlarla böler.
    Bir parçanın ilk ya da son mumu eksikse "parça sınırında" sayılır."""
    times = sorted(set(int(t) for t in times))
    if not times:
        return Continuity(0, None, None, [], 0, 0)
    anchor = ceil_to(since_ms, tf_ms)
    have = set(times)
    missing = [t for t in range(times[0], times[-1] + 1, tf_ms) if t not in have]
    border = sum(1 for t in missing if ((t - anchor) // tf_ms) % chunk in (0, chunk - 1))
    head = max(0, (times[0] - anchor) // tf_ms)
    return Continuity(len(times), times[0], times[-1], missing, border, head)


def kline_times(rows: Any) -> list[int]:
    return [int(r[0]) for r in as_list(rows) if isinstance(r, (list, tuple)) and r]


def close_time_convention(rows: Any, tf_ms: int) -> str:
    diffs = Counter(int(r[6]) - int(r[0]) for r in as_list(rows) if isinstance(r, (list, tuple)) and len(r) > 6)
    if not diffs:
        return "closeTime alanı yok"
    diff = diffs.most_common(1)[0][0]
    if diff == tf_ms - 1:
        return "closeTime = açılış + tf − 1 ms"
    if diff == tf_ms:
        return "closeTime = açılış + tf"
    return f"closeTime = açılış + {diff} ms"


def history_semantics(t0: int, tf: int, small: list[int], exact: list[int], wide: list[int]) -> dict[str, Any]:
    """historyKlines sınır davranışı. small: [t0, t0+5tf], exact: [t0, t0+100tf-1], wide: [t0, t0+300tf]."""
    small_set = set(small)
    res: dict[str, Any] = {
        "start_inclusive": t0 in small_set,
        "end_inclusive": (t0 + 5 * tf) in small_set,
        "ascending": small == sorted(small) and exact == sorted(exact) and wide == sorted(wide),
        "exact_count": len(exact),
        "wide_count": len(wide),
    }
    expected = list(range(t0, t0 + HISTORY_LIMIT * tf, tf))
    res["chunk_ok"] = sorted(exact) == expected
    if not wide:
        res["wide_side"] = "boş"
    elif len(wide) > HISTORY_LIMIT:
        res["wide_side"] = "hepsi, 100 sınırı yok"
    elif min(wide) <= t0 + tf:
        res["wide_side"] = "İLK 100"
    elif max(wide) >= t0 + 299 * tf:
        res["wide_side"] = "SON 100"
    else:
        res["wide_side"] = "belirsiz"
    return res


def funding_side(times: list[int], start_ms: int, now_ms: int, step_ms: int = 8 * HOUR_MS) -> str:
    """startTime + limit (endTime yok) cevabı: startTime'dan ileri mi (İLK) yoksa en son kayıtlar mı?"""
    if not times:
        return "boş"
    first, last = min(times), max(times)
    if first < start_ms - step_ms:
        return "startTime yok sayıldı (daha eski kayıt döndü)"
    if first <= start_ms + 2 * step_ms:
        return "İLK"
    if last >= now_ms - 2 * step_ms:
        return "SON"
    return "belirsiz"


def bn_ts_meaning(new_ts: int, seen_ms: int, period_ms: int = 5 * MIN_MS) -> tuple[str, int]:
    """Yeni bir /futures/data satırı seen_ms anında ilk kez görüldü. (anlam, yayın gecikmesi ms).
    Görülme anı ts + dönemden sonraysa ts dönem BAŞLANGICIdır (veri dönem bitince yayınlanır)."""
    delta = seen_ms - new_ts
    if delta >= period_ms:
        return "dönem başlangıcı", delta - period_ms
    return "dönem sonu / anlık görüntü", delta


def liquidation_shape(message: Any) -> dict[str, Any]:
    """forceOrder yükünün biçimi: tek nesne mi liste mi, st/ps alanları nerede."""
    items = message if isinstance(message, list) else [message]
    first = items[0] if items and isinstance(items[0], dict) else {}
    order = first.get("o") if isinstance(first.get("o"), dict) else {}
    return {
        "shape": "liste" if isinstance(message, list) else "tek nesne",
        "top_keys": sorted(first.keys()),
        "order_keys": sorted(order.keys()),
        "st": order.get("st", first.get("st")),
        "ps": order.get("ps", first.get("ps")),
        "has_st": "st" in order or "st" in first,
        "has_ps": "ps" in order or "ps" in first,
    }


def is_liquidation(message: Any) -> bool:
    if isinstance(message, list):
        return any(isinstance(m, dict) and m.get("e") == "forceOrder" for m in message)
    return isinstance(message, dict) and message.get("e") == "forceOrder"


def digit_symbols(symbols: list[str]) -> list[str]:
    return sorted(s for s in symbols if s[:1].isdigit())


def meme_naming(symbols: list[str], bases: tuple[str, ...] = MEME_BASES) -> list[str]:
    have = set(symbols)
    out = []
    for base in bases:
        forms = [f"{p}{base}USDT" for p in ("", "1000", "10000", "1000000", "1M") if f"{p}{base}USDT" in have]
        if forms:
            out.append("/".join(forms))
    return out


def body_error(data: Any) -> str | None:
    """WEEX bazen HTTP 200 ile gövdede hata kodu döner."""
    if isinstance(data, dict) and "code" in data and ("msg" in data or "message" in data):
        if str(data.get("code")) not in ("0", "200", "00000"):
            return f"kod {data.get('code')}: {data.get('msg') or data.get('message')}"
    return None


# --------------------------------------------------------------------------
# Prob
# --------------------------------------------------------------------------


class Probe:
    def __init__(self, rep: Report, transport: Any, clock: Clock | None = None):
        self.rep = rep
        self.t = transport
        self.clock = clock or Clock()
        self.ctx: dict[str, Any] = {}
        self.offset_ms = 0  # WEEX sunucu saati − yerel saat

    # --- ağ yardımcıları ---------------------------------------------------

    def pause(self) -> None:
        self.clock.sleep(REQUEST_PAUSE)

    def call(self, url: str, params: dict | None = None) -> tuple[Any, str | None]:
        """(veri, hata). HTTP 4xx/5xx ve gövdedeki hata kodu istisna değil hata metni olarak döner;
        bağlantı hataları istisna olarak yükselir (kontrol UYARI olur)."""
        try:
            data = self.t.get(url, params).data
        except HttpStatusError as exc:
            return None, describe_error(exc, 220)
        finally:
            self.pause()
        err = body_error(data)
        return (None, err) if err else (data, None)

    def weex(self, path: str, params: dict | None = None) -> tuple[Any, str | None]:
        return self.call(f"{WEEX_CONTRACT}/capi/v3/market/{path}", params)

    def weex_now(self) -> int:
        return self.clock.now_ms() + self.offset_ms

    def check(self, group: str, name: str, fn: Callable[[], str | Outcome], critical: bool = False):
        return self.rep.run(group, name, fn, critical=critical)

    def finding(self, label: str, value: str) -> None:
        self.rep.finding(label, value)

    def sample(self, name: str, data: Any) -> None:
        save_sample(self.rep, f"probe_{name}", data)

    # ======================================================================
    # Freqtrade
    # ======================================================================

    def run_freqtrade(self, factory: Callable[[], Any]) -> None:
        g = "Freqtrade"
        holder: dict[str, Any] = {}

        def init():
            ex = factory()
            holder["ex"] = ex
            cls = f"{type(ex).__module__}.{type(ex).__name__}"
            if type(ex).__name__ != "Weex":
                return Outcome(FAIL, f"CyberBot Weex sınıfı yerine {cls} yüklendi – imajdaki kayıt bozuk")
            swaps = sorted(p for p, m in ex.markets.items()
                           if m.get("swap") and m.get("linear") and m.get("quote") == "USDT")
            self.ctx["ft_swaps"] = swaps
            lev = ex.get_max_leverage(BTC, 100.0)
            eth = ex.markets.get(ETH) or {}
            cs_ccxt, cs_ft = eth.get("contractSize"), ex.get_contract_size(ETH)
            detail = (f"{cls}: {len(swaps)} USDT-M perpetual, BTC en yüksek kaldıraç {lev:g}x, "
                      f"ETH contractSize ccxt {cs_ccxt} → Freqtrade {cs_ft}")
            if cs_ft != 1.0:
                return Outcome(FAIL, detail + " – miktar ölçeklenir, freqtrade_ext/weex.py kontrol edilmeli")
            self.finding("Karar – contractSize",
                         f"ccxt ETH contractSize={cs_ccxt} (contractVal), Freqtrade get_contract_size=1.0 → "
                         "miktarlar baz birim, emir boyutu ölçeklenmez")
            if lev <= 1.0:
                return Outcome(WARN, detail + " – kaldıraç 1x'e düşer")
            return detail

        if self.check(g, "borsa_baslat", init, critical=True).status != OK:
            self.rep.add(g, "diger", SKIP, "Freqtrade WEEX sınıfı başlatılamadı; Freqtrade testleri atlandı")
            ex = holder.get("ex")
            if ex is not None:
                ex.close()
            return
        ex = holder["ex"]
        try:
            self._ft_checks(g, ex)
        finally:
            ex.close()

    def _ft_frame_times(self, ex, pair: str, tf: str, candle_type, since_ms: int) -> list[int]:
        """Freqtrade'in indirme yolu (get_historic_ohlcv: Weex parçalaması dahil) ile mum zamanları.
        refresh_latest_ohlcv(cache=False) KULLANILMAZ: o eksik mumları sahte 0 hacimli satırlarla
        doldurur (fill_missing) ve süreklilik ölçümü hiçbir boşluğu göremez."""
        df = ex.get_historic_ohlcv(pair, tf, since_ms, candle_type)
        if df is None or df.empty:
            return []
        self.ctx.setdefault("ft_frames", {})[(tf, str(candle_type))] = df
        return [int(ts.timestamp() * 1000) for ts in df["date"]]

    def _ft_checks(self, g: str, ex) -> None:
        from freqtrade.enums import CandleType

        def candles(tf: str, candle_type, days: int, label: str):
            def fn():
                tf_ms = TF_MS[tf]
                now = self.clock.now_ms()
                since = floor_to(now - days * DAY_MS, tf_ms)  # canlıdaki gibi mum ızgarasında
                times = self._ft_frame_times(ex, BTC, tf, candle_type, since)
                c = continuity(times, tf_ms, since)
                if not c.n:
                    return Outcome(WARN, "veri gelmedi")
                expected_last = floor_to(now, tf_ms) - tf_ms
                late = c.last < expected_last - tf_ms
                text = c.text(tf_ms) + (f"; baştaki eksik {c.head_missing}" if c.head_missing else "")
                if label:
                    verdict = ("100'lük sınırlarda boşluk yok → Weex historyKlines parçalaması doğru"
                               if not c.missing else
                               f"{len(c.missing)} eksik mum ({c.missing_at_chunk_border} tanesi parça sınırında) "
                               "→ freqtrade_ext/weex.py parçalaması gözden geçirilmeli")
                    self.finding(label, verdict)
                if c.missing or late:
                    return Outcome(WARN, text + ("; son kapanmış mum gelmedi" if late else ""))
                return text
            return fn

        self.check(g, "mum_5m_7gun", candles("5m", CandleType.FUTURES, 7, "Karar – Freqtrade 5m geçmişi"))
        self.check(g, "mark_1h_60gun", candles("1h", CandleType.MARK, 60, "Karar – Freqtrade 1h mark mumları"))

        def funding():
            since = floor_to(self.clock.now_ms() - 7 * DAY_MS, HOUR_MS)
            times = self._ft_frame_times(ex, BTC, "1h", CandleType.FUNDING_RATE, since)
            if not times:
                return Outcome(WARN, "funding kaydı gelmedi – dry-run funding ücreti hesaplanamaz")
            steps = Counter(fmt_dur(b - a) for a, b in zip(times, times[1:]))
            df = self.ctx["ft_frames"][("1h", str(CandleType.FUNDING_RATE))]
            last_rate = float(df["open"].iloc[-1])
            return (f"7 günde {len(times)} funding kaydı, aralıklar {dict(steps)}, "
                    f"son {fmt_both(from_ms(times[-1]))} %{last_rate * 100:.4f}")

        self.check(g, "funding_1h", funding)

        def tickers():
            tick = ex.get_tickers()
            pairs = [p for p in self.ctx.get("ft_swaps", []) if p in tick]
            top = sorted(pairs, key=lambda p: tick[p].get("quoteVolume") or 0, reverse=True)[:TOP_N]
            missing = [p for p in top if tick[p].get("bid") is None or tick[p].get("ask") is None]
            text = f"hacimde ilk {len(top)} paritenin {len(top) - len(missing)} tanesinde bid/ask var"
            self.finding("Karar – ticker bid/ask",
                         "ticker/24hr + bookTicker birleşimi tam → SpreadFilter çalışır" if not missing and top
                         else f"bid/ask eksik: {', '.join(missing[:10]) or 'parite yok'} → SpreadFilter bu pariteleri eler")
            if missing or not top:
                return Outcome(WARN, text + (f"; eksik: {', '.join(missing[:10])}" if missing else ""))
            return text

        self.check(g, "ticker_bid_ask", tickers)

    # ======================================================================
    # WEEX ham uç noktalar
    # ======================================================================

    def run_weex(self) -> None:
        g = "WEEX"

        def server_time():
            data, err = self.weex("time")
            if err:
                return Outcome(WARN, f"sunucu saati alınamadı ({err}); yerel saat kullanılıyor")
            self.offset_ms = int(data["serverTime"]) - self.clock.now_ms()
            return f"sunucu {fmt_both(from_ms(int(data['serverTime'])))}, fark {self.offset_ms:+d} ms"

        self.check(g, "sunucu_saati", server_time)
        self.check(g, "exchangeInfo", self.weex_exchange_info)
        self.check(g, "sembol_adlari", self.weex_symbol_names)
        self.check(g, "ticker_24hr", self.weex_ticker)
        self.check(g, "bookTicker", self.weex_book_ticker)
        self.check(g, "klines_1000", self.weex_klines)
        self.check(g, "historyKlines_sinir", self.weex_history_bounds)
        self.check(g, "historyKlines_5m_derinlik", self.weex_history_depth("5m"))
        self.check(g, "historyKlines_1h_derinlik", self.weex_history_depth("1h"))
        self.check(g, "historyKlines_mark_index", self.weex_history_price_types)
        self.check(g, "mark_index_klines", self.weex_mark_klines)
        self.check(g, "funding_gecmisi", self.weex_funding_history)
        self.check(g, "collectCycle_ilk40", self.weex_collect_cycle)
        self.check(g, "depth_limitleri", self.weex_depth_limits)
        self.check(g, "open_interest", self.weex_open_interest)

    def weex_exchange_info(self):
        data, err = self.weex("exchangeInfo")
        if err:
            return Outcome(WARN, err)
        rows = [s for s in data.get("symbols", []) if isinstance(s, dict)] if isinstance(data, dict) else []
        if not rows:
            return Outcome(WARN, "symbols listesi boş")
        self.ctx["contracts"] = {s.get("symbol"): s for s in rows if s.get("symbol")}
        self.ctx["weex_perps"] = weex_usdt_perps(data)
        key_counts = Counter(k for s in rows for k in s)
        extra = sorted(set(key_counts) - KNOWN_CONTRACT_KEYS)
        partial = sorted(k for k, n in key_counts.items() if n < len(rows))
        no_base = sorted(str(s.get("symbol")) for s in rows if not s.get("baseAsset") or not s.get("quoteAsset"))
        mismatch, min_mismatch = [], []
        for s in rows:
            cv, qp = to_float(s.get("contractVal")), s.get("quantityPrecision")
            try:
                step = 10 ** -int(qp)
            except (TypeError, ValueError):
                step = None
            if cv is not None and step is not None and not math.isclose(cv, step, rel_tol=1e-9):
                mismatch.append(f"{s.get('symbol')} contractVal {s.get('contractVal')} / adım {step:g}")
            mo = to_float(s.get("minOrderSize"))
            if cv is not None and mo is not None and not math.isclose(cv, mo, rel_tol=1e-9):
                min_mismatch.append(str(s.get("symbol")))
        status_like = [k for k in key_counts if any(w in k.lower() for w in ("status", "list", "online", "time",
                                                                               "delist", "enable", "open", "new"))]
        top_keys = sorted(k for k in data if k != "symbols")
        self.sample("weex_exchangeInfo_keys", {
            "top_level_keys": top_keys, "key_counts": dict(key_counts), "extra_keys": extra,
            "missing_base_quote": no_base[:20], "contractVal_mismatch": mismatch[:20], "first": rows[:3],
        })
        self.finding("WEEX exchangeInfo anahtarları", ", ".join(sorted(key_counts)) +
                     (f" | bilinmeyen ek anahtarlar: {', '.join(extra)}" if extra else " | ek anahtar yok")
                     + (f" | durum/zaman benzeri: {', '.join(sorted(status_like))}" if status_like else
                        " | durum/listeleme zamanı alanı YOK → yeni/kapanan pariteler mum sayısından anlaşılmalı"))
        self.finding("Karar – contractVal",
                     f"{len(mismatch)}/{len(rows)} sembolde contractVal ≠ 10^-quantityPrecision, "
                     f"{len(min_mismatch)} sembolde contractVal ≠ minOrderSize"
                     + (f" (ör. {'; '.join(mismatch[:3])})" if mismatch else "")
                     + " → Freqtrade'de contractSize 1.0 (miktar baz birim) kararı geçerli")
        text = (f"{len(rows)} kontrat ({len(self.ctx['weex_perps'])} USDT-M), anahtar {len(key_counts)}, "
                f"ek {len(extra)}, bazı sembollerde eksik anahtar {len(partial)}, "
                f"baseAsset/quoteAsset eksik {len(no_base)}, contractVal uyumsuz {len(mismatch)}")
        if no_base:
            return Outcome(WARN, text + f" ({', '.join(no_base[:5])}) – ccxt 4.5.88 bunları atlar")
        return text

    def weex_symbol_names(self):
        symbols = sorted(self.ctx.get("contracts") or {})
        if not symbols:
            return Outcome(SKIP, "exchangeInfo yok")
        digits = digit_symbols(symbols)
        memes = meme_naming(symbols)
        self.finding("WEEX rakamla başlayan semboller", f"{len(digits)}: {', '.join(digits[:40]) or '-'}")
        self.finding("WEEX meme coin adlandırması", ", ".join(memes) or "listede yok")
        return f"rakamla başlayan {len(digits)} sembol; meme coin biçimleri: {', '.join(memes[:8]) or '-'}"

    def weex_ticker(self):
        data, err = self.weex("ticker/24hr")
        if err:
            return Outcome(WARN, err)
        rows = [x for x in as_list(data) if isinstance(x, dict)]
        self.sample("weex_ticker_24hr", rows[:3])
        top = top_by_quote_volume(rows, TOP_N)
        self.ctx["top"] = [s for s, _ in top]
        self.ctx["ticker"] = {x.get("symbol"): x for x in rows}
        keys = sorted({k for x in rows for k in x})
        with_bidask = sum(1 for x in rows if any(x.get(k) not in (None, "") for k in ("bidPrice", "askPrice", "bid",
                                                                                      "ask", "bestBid", "bestAsk")))
        perps = self.ctx.get("weex_perps") or []
        btc = self.ctx["ticker"].get("BTCUSDT") or {}
        vol, qvol, last = (to_float(btc.get(k)) for k in ("volume", "quoteVolume", "lastPrice"))
        unit = "?"
        if vol and qvol and last:
            ratio = qvol / vol / last
            unit = ("quoteVolume USDT, volume baz birim" if 0.8 < ratio < 1.25 else
                    f"quoteVolume/volume/fiyat = {ratio:.4g} – birim beklenenden farklı")
        self.finding("WEEX ticker/24hr", f"{len(rows)} satır (exchangeInfo USDT-M {len(perps)}), bid/ask olan "
                     f"{with_bidask} → bookTicker birleştirmesi {'gerekli' if not with_bidask else 'gerekmeyebilir'}; "
                     f"{unit}; anahtarlar: {', '.join(keys)}")
        text = f"{len(rows)} satır (USDT-M {len(perps)}), bid/ask içeren {with_bidask}, {unit}"
        if perps and len(rows) < len(perps) * 0.9:
            return Outcome(WARN, text + " – ticker sayısı kontrat sayısından az")
        return text

    def weex_book_ticker(self):
        data, err = self.weex("ticker/bookTicker")
        if err:
            return Outcome(WARN, err)
        rows = [x for x in as_list(data) if isinstance(x, dict)]
        self.sample("weex_bookTicker", rows[:3])
        have = {x.get("symbol") for x in rows if to_float(x.get("bidPrice")) and to_float(x.get("askPrice"))}
        top = self.ctx.get("top") or []
        missing = [s for s in top if s not in have]
        text = (f"{len(rows)} satır, alanlar {', '.join(sorted({k for x in rows for k in x}))}; "
                f"hacimde ilk {len(top)} içinde bid/ask olmayan {len(missing)}")
        if missing:
            return Outcome(WARN, text + f" ({', '.join(missing[:8])})")
        return text

    def _wait_away_from_boundary(self, tf_ms: int) -> None:
        """Mum sınırının iki yanından uzak dur: açılıştan sonraki ilk 15 sn ve kapanıştan önceki
        son 5 sn (istek + bekleme sınırı aşarsa oluşan mum kapanmış sanılır)."""
        into = self.weex_now() % tf_ms
        if into < BOUNDARY_GUARD_MS:
            self.clock.sleep((BOUNDARY_GUARD_MS - into) / 1000 + 5)
        elif tf_ms - into < BOUNDARY_END_GUARD_MS:
            self.clock.sleep((tf_ms - into + BOUNDARY_GUARD_MS) / 1000 + 5)

    def weex_klines(self):
        tf = TF_MS["5m"]
        self._wait_away_from_boundary(tf)
        now = self.weex_now()  # istekten ÖNCE: cevap/bekleme sonrası saat bir sonraki muma geçmiş olabilir
        data, err = self.weex("klines", {"symbol": "BTCUSDT", "interval": "5m", "limit": 1000})
        if err:
            return Outcome(WARN, f"limit=1000 reddedildi: {err}")
        rows = as_list(data)
        times = kline_times(rows)
        if not times:
            return Outcome(WARN, "mum gelmedi")
        self.sample("weex_klines_5m", rows[-3:])
        current_open = floor_to(now, tf)
        forming = times[-1] >= current_open
        ascending = times == sorted(times)
        convention = close_time_convention(rows, tf)
        old, err_old = self.weex("klines", {"symbol": "BTCUSDT", "interval": "5m", "limit": 10,
                                            "startTime": now - 30 * DAY_MS, "endTime": now - 29 * DAY_MS})
        old_times = kline_times(old)
        if err_old:
            ignores = f"startTime/endTime ile hata: {err_old}"
        elif old_times and max(old_times) >= current_open - tf:
            ignores = "startTime/endTime YOK SAYILIYOR (en yeni mumlar döndü)"
        elif old_times:
            ignores = "startTime/endTime uygulanıyor"
        else:
            ignores = "startTime/endTime ile boş cevap"
        if forming:
            self.finding("Karar – son mum (klines)", "son satır OLUŞAN mum → Freqtrade onu atar "
                         "(ohlcv_partial_candle=True) → mevcut ayar doğru")
        else:
            self.finding("Karar – son mum (klines)", "son satır KAPANMIŞ mum (WEEX oluşan mumu vermiyor) → "
                         "Freqtrade 2026.9 yeni kapanan mumu 15 sn bekleme payından sonra tutar, sinyal gecikmez "
                         "→ ohlcv_partial_candle=True kalır, değişiklik gerekmez")
        self.finding("WEEX klines", f"limit=1000 → {len(times)} mum, {'artan' if ascending else 'KARIŞIK'} sıra, "
                     f"{convention}; {ignores}")
        text = (f"{len(times)} mum, son satır {'oluşan' if forming else 'kapanmış'} mum "
                f"({fmt_both(from_ms(times[-1]))}), {convention}; {ignores}")
        if len(times) < 1000 or not ascending:
            return Outcome(WARN, text)
        return text

    def _history(self, start: int, end: int, interval: str = "5m", price_type: str | None = None):
        params = {"symbol": "BTCUSDT", "interval": interval, "startTime": start, "endTime": end}
        if price_type:
            params["priceType"] = price_type
        data, err = self.weex("historyKlines", params)
        return as_list(data), err

    def weex_history_bounds(self):
        tf = TF_MS["5m"]
        t0 = floor_to(self.weex_now() - 3 * DAY_MS, tf)
        small, e1 = self._history(t0, t0 + 5 * tf)
        exact, e2 = self._history(t0, t0 + HISTORY_LIMIT * tf - 1)
        wide, e3 = self._history(t0, t0 + 300 * tf)
        if e1 or e2 or e3:
            return Outcome(WARN, f"historyKlines hata verdi: {e1 or e2 or e3}")
        self.sample("weex_historyKlines_exact", exact[:3])
        self.ctx["hist_last_price"] = {int(r[0]): to_float(r[4]) for r in exact if len(r) > 4}
        sem = history_semantics(t0, tf, kline_times(small), kline_times(exact), kline_times(wide))
        bounds = (f"startTime {'dahil' if sem['start_inclusive'] else 'HARİÇ'}, "
                  f"endTime {'dahil' if sem['end_inclusive'] else 'hariç'}, "
                  f"300 mumluk aralıkta {sem['wide_count']} satır ({sem['wide_side']}), "
                  f"tam 100'lük pencerede {sem['exact_count']} satır")
        if sem["chunk_ok"]:
            decision = f"{bounds} → mevcut Weex parçalama (endTime = start + 100×tf − 1) doğru"
        else:
            decision = f"{bounds} → Weex parçalama her 100 mumda boşluk bırakabilir, freqtrade_ext/weex.py düzeltilmeli"
        self.finding("Karar – historyKlines", decision)
        if not sem["chunk_ok"] or not sem["ascending"]:
            return Outcome(WARN, bounds + ("" if sem["ascending"] else "; sıra artan değil"))
        return bounds

    def weex_history_depth(self, interval: str):
        def fn():
            tf = TF_MS[interval]
            now = self.weex_now()
            errors: list[str] = []

            def has_data(days: int) -> bool:
                start = floor_to(now - days * DAY_MS, tf)
                end = start + HISTORY_LIMIT * tf - 1
                rows, err = self._history(start, end, interval)
                if err:
                    errors.append(f"{days} gün: {err}")
                    return False
                return any(start <= t <= end for t in kline_times(rows))

            days, open_ended = probe_history_depth(has_data)
            first_err = errors[0] if errors else "hata yok, sadece boş liste"
            text = (f"en az {days} gün" + (" (daha eskisi de olabilir)" if open_ended else "")
                    + (f"; çok eski istekte: {first_err}" if not open_ended else ""))
            self.finding(f"WEEX historyKlines {interval} derinliği", text)
            if days == 0:
                return Outcome(WARN, "geçmiş mum verisi yok: " + first_err)
            return text
        return fn

    def weex_history_price_types(self):
        tf = TF_MS["5m"]
        t0 = floor_to(self.weex_now() - 3 * DAY_MS, tf)
        last = self.ctx.get("hist_last_price") or {}
        parts, warn = [], False
        for price_type in ("MARK", "INDEX"):
            rows, err = self._history(t0, t0 + 20 * tf - 1, "5m", price_type)
            if err:
                parts.append(f"{price_type} reddedildi ({err})")
                warn = True
                continue
            times = kline_times(rows)
            zero_vol = all(to_float(r[5]) in (0.0, None) for r in rows if len(r) > 5)
            diff = sum(1 for r in rows if len(r) > 4 and last.get(int(r[0])) is not None
                       and to_float(r[4]) != last.get(int(r[0])))
            parts.append(f"{price_type} kabul ({len(times)} satır, hacim {'0' if zero_vol else 'dolu'}, "
                         f"son fiyattan farklı kapanış {diff})")
            if price_type == "MARK":
                self.sample("weex_historyKlines_mark", rows[:3])
                if len(times) < 20:
                    warn = True
        text = "; ".join(parts)
        self.finding("WEEX historyKlines priceType", text)
        return Outcome(WARN, text) if warn else text

    def weex_mark_klines(self):
        parts, warn = [], False
        for path in ("markPriceKlines", "indexPriceKlines"):
            self._wait_away_from_boundary(HOUR_MS)
            now = self.weex_now()  # istekten önce (bkz. weex_klines)
            data, err = self.weex(path, {"symbol": "BTCUSDT", "interval": "1h", "limit": 1000})
            if err:
                parts.append(f"{path} limit=1000 reddedildi ({err})")
                warn = True
                continue
            rows = as_list(data)
            times = kline_times(rows)
            forming = bool(times) and times[-1] >= floor_to(now, HOUR_MS)
            parts.append(f"{path} 1h limit=1000 → {len(times)} satır, son {'oluşan' if forming else 'kapanmış'} mum")
            if path == "markPriceKlines":
                self.sample("weex_markPriceKlines_1h", rows[-3:])
            if len(times) < 1000:
                warn = True
        text = "; ".join(parts)
        self.finding("WEEX mark/index klines", text)
        return Outcome(WARN, text) if warn else text

    def weex_funding_history(self):
        now = self.weex_now()
        start = now - 60 * DAY_MS
        a, err = self.weex("fundingRate", {"symbol": "BTCUSDT", "startTime": start, "limit": 10})
        if err:
            return Outcome(WARN, f"fundingRate reddedildi: {err}")
        rows_a = [x for x in as_list(a) if isinstance(x, dict)]
        self.sample("weex_fundingRate", rows_a[:3])
        times_a = [int(x["fundingTime"]) for x in rows_a if x.get("fundingTime") is not None]
        side = funding_side(times_a, start, now)
        order = ("artan" if times_a == sorted(times_a) else "azalan" if times_a == sorted(times_a, reverse=True)
                 else "karışık")
        b, err_b = self.weex("fundingRate", {"symbol": "BTCUSDT", "startTime": now - 400 * DAY_MS, "limit": 1000})
        times_b = [int(x["fundingTime"]) for x in as_list(b) if isinstance(x, dict) and x.get("fundingTime")]
        if err_b:
            cap = f"limit=1000 reddedildi ({err_b})"
        else:
            span = fmt_dur(now - min(times_b)) if times_b else "-"
            cap = f"limit=1000 → {len(times_b)} kayıt (en eskisi {span} önce)"
        w0, w1 = now - 60 * DAY_MS, now - 50 * DAY_MS
        c, err_c = self.weex("fundingRate", {"symbol": "BTCUSDT", "startTime": w0, "endTime": w1, "limit": 100})
        times_c = [int(x["fundingTime"]) for x in as_list(c) if isinstance(x, dict) and x.get("fundingTime")]
        if err_c:
            window = f"endTime ile hata ({err_c})"
            window_ok = False
        else:
            window_ok = bool(times_c) and all(w0 <= t <= w1 for t in times_c)
            window = f"startTime+endTime penceresi {'uygulanıyor' if window_ok else 'UYGULANMIYOR'} ({len(times_c)} kayıt)"
        on_hour = all(t % HOUR_MS == 0 for t in times_a + times_b)
        text = (f"startTime+limit → {side} kayıtlar ({order} sıra); {cap}; {window}; "
                f"fundingTime {'tam saatte' if on_hour else 'tam saatte DEĞİL'}")
        self.finding("Karar – funding geçmişi", text + (" → Weex._fetch_funding_rate_history (endTime sınırlı) doğru"
                                                        if window_ok else " → funding geçmişi alımı gözden geçirilmeli"))
        return text if window_ok else Outcome(WARN, text)

    def weex_collect_cycle(self):
        data, err = self.weex("premiumIndex")
        if err:
            return Outcome(WARN, err)
        rows = [x for x in as_list(data) if isinstance(x, dict)]
        self.ctx["mark"] = {x.get("symbol"): to_float(x.get("markPrice")) for x in rows}
        cycles = {x.get("symbol"): x.get("collectCycle") for x in rows}
        top = self.ctx.get("top") or []
        dist = Counter(str(cycles.get(s, "yok")) for s in top)
        odd = [f"{s}={cycles.get(s)}" for s in top if str(cycles.get(s)) != "480"]
        text = (f"premiumIndex {len(rows)} sembol; hacimde ilk {len(top)} için collectCycle (dk) dağılımı "
                f"{dict(dist)}" + (f"; 8 saatten farklı: {', '.join(odd[:10])}" if odd else ""))
        self.finding("WEEX funding periyodu (ilk 40)", text)
        return text

    def weex_depth_limits(self):
        parts, accepted = [], []
        for limit in DEPTH_LIMITS:
            params = {"symbol": "BTCUSDT"} if limit is None else {"symbol": "BTCUSDT", "limit": limit}
            data, err = self.weex("depth", params)
            label = "limitsiz" if limit is None else str(limit)
            if err:
                parts.append(f"{label}: reddedildi ({err[:80]})")
                continue
            bids, asks = len(data.get("bids") or []), len(data.get("asks") or [])
            parts.append(f"{label}: {bids}/{asks} seviye")
            if limit is not None:
                accepted.append(limit)
        text = "; ".join(parts)
        self.finding("WEEX depth limitleri", text + " (Freqtrade l2_limit_range [15, 200])")
        if 15 not in accepted or 200 not in accepted:
            return Outcome(WARN, text)
        return text

    def weex_open_interest(self):
        lines = []
        for symbol in ("BTCUSDT", "ETHUSDT"):
            data, err = self.weex("openInterest", {"symbol": symbol})
            if err:
                lines.append(f"{symbol}: hata ({err})")
                continue
            row = as_list(data)[0] if as_list(data) else {}
            if symbol == "BTCUSDT":
                self.sample("weex_openInterest", row)
            oi = to_float(row.get("openInterest"))
            mark = (self.ctx.get("mark") or {}).get(symbol) or to_float(
                ((self.ctx.get("ticker") or {}).get(symbol) or {}).get("markPrice"))
            cv = to_float(((self.ctx.get("contracts") or {}).get(symbol) or {}).get("contractVal"))
            if oi is None or not mark:
                lines.append(f"{symbol}: OI {row.get('openInterest')} (mark fiyatı yok)")
                continue
            text = f"{symbol}: ham OI {oi:,.3f}, mark {mark:,.2f} → baz birim sayılırsa ≈ {oi * mark / 1e6:,.1f}M$"
            if cv:
                text += f"; kontrat sayılırsa (×{cv:g}) ≈ {oi * cv * mark / 1e6:,.3f}M$"
            lines.append(text)
        joined = " | ".join(lines)
        self.finding("OI birimi (WEEX sitesindeki USDT değeriyle elle karşılaştır)", joined)
        return joined

    # ======================================================================
    # Binance
    # ======================================================================

    def bn(self, path: str, params: dict | None = None) -> tuple[Any, str | None]:
        return self.call(f"{BINANCE_FAPI}{path}", params)

    def run_binance(self) -> None:
        g = "Binance"

        def server_time():
            data, err = self.bn("/fapi/v1/time")
            if err:
                return Outcome(WARN, err)
            self.ctx["bn_offset"] = int(data["serverTime"]) - self.clock.now_ms()
            return f"sunucu {fmt_both(from_ms(int(data['serverTime'])))}, fark {self.ctx['bn_offset']:+d} ms"

        self.check(g, "sunucu_saati", server_time)
        self.check(g, "futures_data_zaman", self.bn_futures_data_time)
        self.check(g, "futures_data_baslangic", self.bn_futures_data_start)
        self.check(g, "futures_data_limit", self.bn_futures_data_limit)
        self.check(g, "likidasyon_ws", self.bn_liquidations)
        self.check(g, "sembol_1000", self.bn_symbols)

    def bn_now(self) -> int:
        return self.clock.now_ms() + int(self.ctx.get("bn_offset") or 0)

    def _fd(self, endpoint: str, **params) -> tuple[list, str | None]:
        data, err = self.bn(f"/futures/data/{endpoint}", {"symbol": "BTCUSDT", "period": "5m", **params})
        return [x for x in as_list(data) if isinstance(x, dict)], err

    def bn_futures_data_time(self):
        period = 5 * MIN_MS
        newest: dict[str, int] = {}
        grids: dict[str, list[int]] = {}
        for endpoint in BINANCE_FUTURES_DATA:
            rows, err = self._fd(endpoint, limit=5)
            if err or not rows:
                newest[endpoint] = -1
                continue
            times = sorted(int(x["timestamp"]) for x in rows if x.get("timestamp") is not None)
            grids[endpoint] = times
            newest[endpoint] = times[-1]
            self.sample(f"binance_{endpoint}", rows[-2:])
        ok = {k: v for k, v in newest.items() if v > 0}
        if not ok:
            return Outcome(WARN, "/futures/data hiçbir uçtan veri gelmedi")
        now = self.bn_now()
        aligned = all(v % period == 0 for v in ok.values())
        same_grid = len({tuple(v[-3:]) for v in grids.values()}) == 1
        ages = ", ".join(f"{k} {fmt_dur(now - v)}" for k, v in ok.items())
        # yayın gecikmesi: en yeni satır değişene kadar yokla (en fazla bir dönem + pay)
        base = ok.get("openInterestHist") or max(ok.values())
        seen_ts, seen_ms = None, None
        deadline = self.clock.now_ms() + int(FD_POLL_MAX_S * 1000)
        while self.clock.now_ms() < deadline:
            self.clock.sleep(FD_POLL_S)
            rows, err = self._fd("openInterestHist", limit=1)
            if rows and int(rows[-1]["timestamp"]) > base:
                seen_ts, seen_ms = int(rows[-1]["timestamp"]), self.bn_now()
                break
        parts = [f"en yeni satır yaşı: {ages}", f"5m hizalı {'evet' if aligned else 'HAYIR'}",
                 f"5 uçta aynı zaman ızgarası {'evet' if same_grid else 'HAYIR'}"]
        if seen_ts is None:
            text = "; ".join(parts) + f"; {FD_POLL_MAX_S / 60:.1f} dk içinde yeni satır gelmedi"
            self.finding("Karar – Binance /futures/data zamanı", text)
            return Outcome(WARN, text)
        meaning, lag = bn_ts_meaning(seen_ts, seen_ms, period)
        parts.append(f"yeni satır ({fmt_both(from_ms(seen_ts))}) {fmt_dur(seen_ms - seen_ts)} sonra görüldü → "
                     f"timestamp = {meaning}, yayın gecikmesi ≈ {fmt_dur(lag)} (±{FD_POLL_S:.0f} sn)")
        text = "; ".join(parts)
        if meaning == "dönem başlangıcı":
            need = int(math.ceil(lag / 1000 + FD_POLL_S + 15))
            decision = (f"timestamp dönem başlangıcı, gecikme ≈ {fmt_dur(lag)} → avail_ms = ts + 5 dk + "
                        f"güvenlik; önerilen güvenlik ≥ {need} sn (recorder varsayılanı {RECORDER_SAFETY_S} sn "
                        f"{'yeterli' if need <= RECORDER_SAFETY_S else 'YETERSİZ, artırılmalı'})")
            warn = need > RECORDER_SAFETY_S
        else:
            decision = (f"timestamp dönem sonu/anlık görüntü, gecikme ≈ {fmt_dur(lag)} → avail_ms = ts + 5 dk "
                        "kuralı ihtiyatlı (bir dönem geç kullanılır); daraltma ancak elle incelemeyle")
            warn = False
        self.finding("Karar – Binance /futures/data zamanı", decision)
        return Outcome(WARN, text) if warn or not aligned or not same_grid else text

    def bn_futures_data_start(self):
        now = self.bn_now()
        parts, ok_295 = [], False
        for label, days in (("now−29.5g", 29.5), ("now−31g", 31)):
            start = int(now - days * DAY_MS)
            rows, err = self._fd("openInterestHist", startTime=start, limit=5)
            if err:
                parts.append(f"{label}: reddedildi ({err[:100]})")
                continue
            if not rows:
                parts.append(f"{label}: boş")
                continue
            first = min(int(x["timestamp"]) for x in rows)
            parts.append(f"{label}: kabul, ilk satır {fmt_dur(now - first)} önce")
            if days == 29.5:
                ok_295 = True
        text = "; ".join(parts)
        self.finding("Binance /futures/data en eski startTime", text)
        return text if ok_295 else Outcome(WARN, text + " – recorder ilk doldurma başlangıcı gözden geçirilmeli")

    def bn_futures_data_limit(self):
        rows, err = self._fd("openInterestHist", limit=500)
        rows2, err2 = self._fd("openInterestHist", limit=501)
        r500 = f"limit=500 → {len(rows)} satır" if not err else f"limit=500 reddedildi ({err[:100]})"
        r501 = f"limit=501 → {len(rows2)} satır" if not err2 else f"limit=501 reddedildi ({err2[:100]})"
        text = f"{r500}; {r501}"
        self.finding("Binance /futures/data limit", text)
        return Outcome(WARN, text) if err or len(rows) < 500 else text

    def bn_liquidations(self):
        stream = "!forceOrder@arr"
        res = self.t.ws(BINANCE_WS_MARKET, subscribe=[{"method": "SUBSCRIBE", "params": [stream], "id": 1}],
                        accept=is_liquidation, timeout=LIQ_WAIT_S)
        if res.first is None:
            text = f"bağlandı ({res.ms_open:.0f} ms); {LIQ_WAIT_S:.0f} sn içinde likidasyon olmadı (sakin piyasada normal)"
            self.finding("Karar – likidasyon WS", text + " → yük biçimi doğrulanamadı, testi hareketli bir anda tekrarla")
            return Outcome(WARN, text)
        self.sample("binance_ws_forceOrder", res.first)
        shape = liquidation_shape(res.first)
        text = (f"ilk kayıt {res.ms_first / 1000:.1f} sn; yük {shape['shape']}, üst alanlar {shape['top_keys']}, "
                f"o alanları {shape['order_keys']}, st={shape['st']} ps={shape['ps']}")
        decision = (f"yük {shape['shape']}; st alanı {'VAR' if shape['has_st'] else 'yok'}"
                    f"{' (=' + str(shape['st']) + ')' if shape['has_st'] else ''}, ps {'var' if shape['has_ps'] else 'yok'}"
                    + (" → recorder 'st == 1' filtresi çalışır" if shape["has_st"] else
                       " → st yoksa recorder hepsini UM sayar mı kontrol edilmeli"))
        self.finding("Karar – likidasyon WS", decision)
        return text if shape["shape"] == "tek nesne" and shape["has_st"] else Outcome(WARN, text)

    def bn_symbols(self):
        data, err = self.bn("/fapi/v1/exchangeInfo")
        if err:
            return Outcome(WARN, err)
        perps = binance_usdt_perps(data)
        digits = digit_symbols(perps)
        onboard = sum(1 for s in data.get("symbols", []) if s.get("onboardDate"))
        limits = ", ".join(f"{x.get('rateLimitType')} {x.get('limit')}/{x.get('intervalNum')}"
                           f"{str(x.get('interval', ''))[:1].lower()}" for x in data.get("rateLimits", []))
        self.finding("Binance rakamla başlayan semboller", f"{len(digits)}: {', '.join(digits) or '-'}")
        weex = self.ctx.get("weex_perps") or []
        if weex:
            self.finding("Meme coin adları WEEX / Binance",
                         f"WEEX: {', '.join(meme_naming(weex)) or '-'} | Binance: {', '.join(meme_naming(perps)) or '-'}")
        return (f"{len(perps)} USDT-M perpetual, rakamla başlayan {len(digits)}, onboardDate olan {onboard}; "
                f"istek sınırları: {limits or '-'}")


# --------------------------------------------------------------------------


def freqtrade_config(datadir: Path) -> dict:
    """Dry-run futures config: API anahtarı yok, sadece herkese açık uçlar."""
    from freqtrade.enums import RunMode

    return {
        "runmode": RunMode.DRY_RUN,
        "dry_run": True,
        "dry_run_wallet": 1000,
        "trading_mode": "futures",
        "margin_mode": "isolated",
        "stake_currency": "USDT",
        "stake_amount": "unlimited",
        "timeframe": "5m",
        "startup_candle_count": 400,
        "datadir": datadir,
        "user_data_dir": datadir,
        "exchange": {"name": "weex", "key": "", "secret": "", "password": "", "pair_whitelist": [],
                     "pair_blacklist": [], "weex_maintenance_margin_rate": 0.01},
        "entry_pricing": {"price_side": "other", "use_order_book": True, "order_book_top": 1},
        "exit_pricing": {"price_side": "other", "use_order_book": True, "order_book_top": 1},
        "order_types": {"entry": "market", "exit": "market", "stoploss": "market", "stoploss_on_exchange": False},
    }


def default_exchange_factory(datadir: Path) -> Callable[[], Any]:
    def make():
        import freqtrade.exchange as fx
        from freqtrade.resolvers import ExchangeResolver

        if not hasattr(fx, "Weex"):  # imajda kayıtlı; değilse (imaj dışı) repo sınıfını kaydet
            from freqtrade_ext.weex import Weex

            fx.Weex = Weex
        return ExchangeResolver.load_exchange(freqtrade_config(datadir), load_leverage_tiers=True)
    return make


def main(
    transport: Any = None,
    exchange_factory: Callable[[], Any] | None = None,
    reports_dir: str | Path | None = None,
    clock: Clock | None = None,
) -> int:
    rep = Report("WEEX/Binance davranış probu (Faz 1)", "weex_probe", reports_dir or paths.reports_dir())
    rep.versions.update(lib_versions())
    for key in SECRET_ENV_KEYS:  # prob anahtar kullanmaz; yine de hiçbir çıktıya sızmasın
        rep.add_secret(os.environ.get(key))
    print(f"CyberBot WEEX/Binance probu – {fmt_both(rep.started)}")
    print("Sadece herkese açık piyasa verisi okunur; API anahtarı kullanılmaz, emir gönderilmez.")
    print("Süre: yaklaşık 5-10 dakika (Binance yayın gecikmesi ve likidasyon akışı beklenir).\n")
    with tempfile.TemporaryDirectory(prefix="cyberbot_probe_") as tmp:
        try:
            if transport is None:
                transport = Transport()
                transport.session.headers["User-Agent"] = USER_AGENT
            probe = Probe(rep, transport, clock)
            probe.run_freqtrade(exchange_factory or default_exchange_factory(Path(tmp)))
            probe.run_weex()
            probe.run_binance()
        except KeyboardInterrupt:
            rep.add("Genel", "kesildi", FAIL, "prob kullanıcı tarafından durduruldu")
        except Exception as exc:  # beklenmeyen hata: rapor yine de yazılır
            rep.log.exception("beklenmeyen hata")
            rep.add("Genel", "script_hatasi", FAIL, describe_error(exc))
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
