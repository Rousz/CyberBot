"""İzlenen semboller ve WEEX -> Binance USDⓈ-M eşlemesi (saf fonksiyonlar).

- İzlenen küme: WEEX USDT vadelileri içinden 24 saatlik quoteVolume'a göre ilk N
  (stablecoin ve kaldıraçlı tokenler hariç) + her zaman izlenenler (BTC, ETH).
  Listeden düşen sembol keep_hours (48 saat) daha izlenir: pairlist değişince veri boşluğu olmasın.
- Eşleme: WEEX baseAsset'in önekini (1000, 10000, 1000000, 1M) ayır, Binance'te
  çekirdek ve önekli adayları dene. Aday ancak fiyat oranı (Binance mark / WEEX mark)
  beklenen çarpana %1.5 içinde uyarsa kabul edilir: aynı kısaltmalı farklı coinler elenir.
- binance_perps.json: Freqtrade parite adı (BASE/USDT:USDT, WEEX baseAsset) -> Binance sembolü.
  Geçici dosyaya yazılıp os.replace ile atomik değiştirilir.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cyberbot.recorder.db import to_float, to_int

HOUR_MS = 3_600_000
# Uzundan kısaya: "1000000" önce denenmeli.
PREFIXES: list[tuple[str, float]] = [("1000000", 1e6), ("10000", 1e4), ("1000", 1e3), ("1M", 1e6)]


@dataclass
class SymbolMapping:
    weex_symbol: str
    weex_base: str
    ft_pair: str
    binance_symbol: str | None
    multiplier: float          # bn_price ≈ weex_price * multiplier
    method: str                # exact | prefix_1000 | prefix_1000000 | prefix_1M | strip_1000 | manual | none
    price_ratio: float | None
    binance_onboard_ms: int | None
    note: str                  # ok | not_on_binance | price_mismatch | no_price | override...

    def as_dict(self) -> dict:
        return asdict(self)


def ft_pair(base: str) -> str:
    return f"{base}/USDT:USDT"


# --------------------------------------------------------------------------
# WEEX: evren ve hacim sıralaması
# --------------------------------------------------------------------------


def weex_usdt_perps(exchange_info: Any) -> dict[str, str]:
    """{WEEX sembolü: baseAsset} (USDT kotlu, USDT teminatlı)."""
    symbols = exchange_info.get("symbols", []) if isinstance(exchange_info, dict) else []
    out = {}
    for s in symbols:
        if not isinstance(s, dict):
            continue
        sym, base = s.get("symbol"), s.get("baseAsset")
        if sym and base and s.get("quoteAsset") == "USDT" and s.get("marginAsset", "USDT") == "USDT":
            out[str(sym)] = str(base)
    return out


def is_excluded(base: str, regexes: list[str]) -> bool:
    return any(re.search(rx, base.upper()) for rx in regexes)


def rank_by_volume(tickers: Any, perps: dict[str, str], regexes: list[str]) -> list[tuple[str, float]]:
    """[(sembol, quoteVolume)] büyükten küçüğe; sadece evrendeki, hariç tutulmayan semboller."""
    ranked = []
    for row in tickers if isinstance(tickers, list) else []:
        if not isinstance(row, dict):
            continue
        sym = row.get("symbol")
        qv = to_float(row.get("quoteVolume"))
        if sym in perps and qv is not None and not is_excluded(perps[sym], regexes):
            ranked.append((sym, qv))
    ranked.sort(key=lambda x: (-x[1], x[0]))
    return ranked


def select_tracked(ranked: list[tuple[str, float]], prev_last_top: dict[str, int | None], now_ms: int, *,
                   top_n: int, keep_hours: float, always: list[str], available: set[str]) -> dict[str, int]:
    """{sembol: son kez ilk N'de görüldüğü an}. Histerezis: düşen sembol keep_hours kalır.
    Borsadan kalkan (available'da olmayan) sembol hemen çıkar."""
    keep_ms = int(keep_hours * HOUR_MS)
    tracked: dict[str, int] = {}
    for sym, _ in ranked[:top_n]:
        tracked[sym] = now_ms
    for sym in always:
        if sym in available:
            tracked[sym] = now_ms
    for sym, last in prev_last_top.items():
        if sym not in tracked and sym in available and last is not None and now_ms - last <= keep_ms:
            tracked[sym] = last
    return tracked


def priority_order(tracked: dict[str, int], ranked: list[tuple[str, float]], always: list[str]) -> list[str]:
    """Geçmiş doldurma sırası: her zaman izlenenler (BTC, ETH), sonra hacme göre, sonra düşenler."""
    order = [s for s in always if s in tracked]
    order += [s for s, _ in ranked if s in tracked and s not in order]
    order += sorted(s for s in tracked if s not in order)
    return order


# --------------------------------------------------------------------------
# Binance
# --------------------------------------------------------------------------


def binance_usdt_perps(exchange_info: Any) -> dict[str, int | None]:
    """{Binance sembolü: onboardDate}: PERPETUAL, TRADING, USDT kotlu."""
    symbols = exchange_info.get("symbols", []) if isinstance(exchange_info, dict) else []
    return {
        str(s["symbol"]): to_int(s.get("onboardDate"))
        for s in symbols
        if isinstance(s, dict) and s.get("symbol") and s.get("contractType") == "PERPETUAL"
        and s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"
    }


def marks(premium_rows: Any) -> dict[str, float]:
    """premiumIndex (Binance veya WEEX, sembolsüz tüm liste) -> {sembol: markPrice}."""
    rows = premium_rows if isinstance(premium_rows, list) else [premium_rows] if isinstance(premium_rows, dict) else []
    out = {}
    for row in rows:
        if isinstance(row, dict) and row.get("symbol"):
            price = to_float(row.get("markPrice"))
            if price and price > 0:
                out[str(row["symbol"])] = price
    return out


def split_prefix(base: str) -> tuple[str, float, str]:
    """'1000PEPE' -> ('PEPE', 1000, '1000'); 'BTC' -> ('BTC', 1, '')."""
    for prefix, mult in PREFIXES:
        rest = base[len(prefix):]
        if base.startswith(prefix) and len(rest) >= 2 and rest[0].isalpha():
            return rest, mult, prefix
    return base, 1.0, ""


def candidates(base: str) -> list[tuple[str, float, str]]:
    """[(Binance sembolü, beklenen çarpan, yöntem)] WEEX baseAsset için, denenme sırasıyla."""
    core, weex_mult, weex_prefix = split_prefix(base)
    out = [(f"{base}USDT", 1.0, "exact")]
    for prefix, mult in [("", 1.0), *PREFIXES]:
        bn_base = prefix + core
        if bn_base == base:
            continue
        method = f"prefix_{prefix}" if prefix else f"strip_{weex_prefix}"
        out.append((f"{bn_base}USDT", mult / weex_mult, method))
    return out


def map_symbol(weex_symbol: str, base: str, weex_marks: dict[str, float], bn_perps: dict[str, int | None],
               bn_marks: dict[str, float], *, tolerance: float, override: Any = ...) -> SymbolMapping:
    pair = ft_pair(base)
    weex_mark = weex_marks.get(weex_symbol)

    def ratio_of(bn_symbol: str) -> float | None:
        bn_mark = bn_marks.get(bn_symbol)
        return bn_mark / weex_mark if bn_mark and weex_mark else None

    def none(note: str, ratio: float | None = None, method: str = "none") -> SymbolMapping:
        return SymbolMapping(weex_symbol, base, pair, None, 1.0, method, ratio, None, note)

    if override is not ...:  # elle eşleme
        if not override:
            return none("override_none", method="manual")
        bn_symbol = str(override.get("binance_symbol") or "")
        mult = float(override.get("multiplier") or 1.0)
        if bn_symbol not in bn_perps:
            return none("override_not_trading", method="manual")
        return SymbolMapping(weex_symbol, base, pair, bn_symbol, mult, "manual", ratio_of(bn_symbol),
                             bn_perps[bn_symbol], "override")

    first_ratio, note = None, "not_on_binance"
    for bn_symbol, mult, method in candidates(base):
        if bn_symbol not in bn_perps:
            continue
        ratio = ratio_of(bn_symbol)
        if ratio is None:
            note = "no_price" if note == "not_on_binance" else note
            continue
        if abs(ratio / mult - 1.0) <= tolerance:
            return SymbolMapping(weex_symbol, base, pair, bn_symbol, mult, method, round(ratio, 6),
                                 bn_perps[bn_symbol], "ok")
        if first_ratio is None:
            first_ratio = round(ratio, 6)
        note = "price_mismatch"
    return none(note, first_ratio)


def map_all(perps: dict[str, str], weex_marks: dict[str, float], bn_perps: dict[str, int | None],
            bn_marks: dict[str, float], *, tolerance: float, overrides: dict | None = None) -> dict[str, SymbolMapping]:
    overrides = overrides or {}
    return {
        sym: map_symbol(sym, base, weex_marks, bn_perps, bn_marks, tolerance=tolerance,
                        override=overrides[sym] if sym in overrides else ...)
        for sym, base in sorted(perps.items())
    }


# --------------------------------------------------------------------------
# binance_perps.json
# --------------------------------------------------------------------------


def perps_json(mappings: dict[str, SymbolMapping], now_ms: int) -> dict:
    """ARCHITECTURE.md biçimi; sadece Binance karşılığı olan pariteler."""
    pairs = {
        m.ft_pair: {"binance_symbol": m.binance_symbol, "multiplier": float(m.multiplier), "method": m.method}
        for m in sorted(mappings.values(), key=lambda m: m.ft_pair) if m.binance_symbol
    }
    return {"generated_ms": int(now_ms), "pairs": pairs}


def write_json_atomic(path: str | Path, data: dict) -> None:
    """Okuyan (strateji) asla yarım dosya görmez: aynı klasörde geçici dosya + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
