"""weex_probe uçtan uca: Freqtrade kısmı offline_weex ile gerçek Freqtrade/ccxt kodundan,
WEEX ham uçları + Binance REST/WS sahte ağdan (internet yok)."""

import pytest

from cyberbot import weex_probe as wp
from tests.probe_fakes import FakeClock, ProbeRouter, ProbeTransport
from tests.weex_router import offline_weex

MIN = 60_000
TOKEN = "123456789:AAFakeTelegramTokenForTests_xyz"


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(wp, "REQUEST_PAUSE", 0)


def run(tmp_path, monkeypatch=None, **fake_kwargs):
    clock = FakeClock()
    transport = ProbeTransport(clock, **fake_kwargs)
    with offline_weex(ProbeRouter()) as router:
        code = wp.main(transport=transport, reports_dir=tmp_path, clock=clock)
    summary = next(tmp_path.glob("weex_probe_*.txt")).read_text(encoding="utf-8")
    log = next((tmp_path / "logs").glob("weex_probe_*.log")).read_text(encoding="utf-8")
    return code, summary, log, transport, router


def line(summary: str, label: str) -> str:
    return next(ln for ln in summary.splitlines() if label in ln)


def test_full_probe_reports_decisions(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", TOKEN)
    code, summary, log, t, router = run(tmp_path)
    assert code == 0
    assert "SONUÇ: BAŞARILI" in summary and "HATA 0" in summary
    # tek beklenen uyarı: fixture'daki baseAsset'siz sembol (NOBASEUSDT)
    assert "UYARI 1," in summary and "[UYARI  ] WEEX          exchangeInfo" in summary
    assert "UTC (İstanbul" in summary
    # Freqtrade kısmı gerçek Weex alt sınıfıyla çalıştı (5m 7 gün => historyKlines + klines)
    assert "freqtrade_ext.weex.Weex" in line(summary, "borsa_baslat")
    assert router.calls_to("capi/v3/market/historyKlines")
    assert "[OK     ] Freqtrade     mum_5m_7gun" in summary
    assert "eksik 0 (100'lük parça sınırında 0)" in line(summary, "mum_5m_7gun")
    assert "Karar – Freqtrade 5m geçmişi: 100'lük sınırlarda boşluk yok" in summary
    assert "Karar – contractSize" in summary and "get_contract_size=1.0" in summary
    assert "SpreadFilter çalışır" in summary
    # WEEX kararları
    assert "historyKlines: startTime dahil, endTime dahil, 300 mumluk aralıkta 100 satır (İLK 100)" in summary
    assert "mevcut Weex parçalama (endTime = start + 100×tf − 1) doğru" in summary
    assert "son satır OLUŞAN mum" in summary
    assert "startTime/endTime YOK SAYILIYOR" in summary
    assert "closeTime = açılış + tf − 1 ms" in summary
    assert "en az 398 gün" in line(summary, "historyKlines 5m derinliği") or \
        "gün" in line(summary, "historyKlines 5m derinliği")
    assert "-1170" in line(summary, "historyKlines 5m derinliği")
    assert "MARK kabul" in summary and "INDEX kabul" in summary
    assert "startTime+limit → İLK kayıtlar" in summary and "limit=1000 → 1000 kayıt" in summary
    assert "Weex._fetch_funding_rate_history (endTime sınırlı) doğru" in summary
    assert "'480': 2" in summary and "SOLUSDT=240" in summary
    assert "50: reddedildi" in summary and "200: 200/200 seviye" in summary
    assert "ham OI 51,234.567" in summary and "baz birim sayılırsa" in summary
    assert "1000PEPEUSDT" in line(summary, "WEEX rakamla başlayan")
    assert "baseAsset/quoteAsset eksik 1" in summary  # NOBASEUSDT
    assert "status" in line(summary, "WEEX exchangeInfo anahtarları")
    assert "quoteVolume USDT, volume baz birim" in summary
    # Binance kararları
    assert "timestamp dönem başlangıcı" in summary and "yeterli" in line(summary, "Binance /futures/data zamanı")
    assert "now−29.5g: kabul" in summary and "now−31g: reddedildi" in summary
    assert "limit=500 → 500 satır; limit=501 reddedildi" in summary
    assert "yük tek nesne; st alanı VAR (=1)" in summary
    assert "1000PEPEUSDT" in line(summary, "Binance rakamla başlayan")
    # örnekler kaydedildi, gizli bilgi yok
    samples = list((tmp_path / "samples").glob("probe_*.json"))
    assert {"probe_weex_exchangeInfo_keys.json", "probe_binance_ws_forceOrder.json"} <= {p.name for p in samples}
    for text in [summary, log] + [p.read_text(encoding="utf-8") for p in samples]:
        assert TOKEN not in text
    assert (tmp_path / "logs" / "weex_probe_last.txt").read_text(encoding="utf-8").startswith("BAŞARILI")
    # WS: ccxt tarzı SUBSCRIBE /market/ws
    url, sub, _ = t.ws_calls[0]
    assert url == "wss://fstream.binance.com/market/ws" and sub[0]["params"] == ["!forceOrder@arr"]
    # hiçbir istekte API anahtarı yok
    assert not any("apiKey" in str(p) or "signature" in str(p) for _, p in t.calls)


def test_closed_last_candle_and_exclusive_start_are_flagged(tmp_path):
    code, summary, *_ = run(tmp_path, forming=False, start_inclusive=False, history_side="last")
    assert code == 0  # uyarılar kontrolü düşürmez
    assert "BAŞARILI (uyarılarla)" in summary
    assert "son satır KAPANMIŞ mum" in summary and "ohlcv_partial_candle=False gerekli" in summary
    assert "startTime HARİÇ" in summary and "(SON 100)" in summary
    assert "freqtrade_ext/weex.py düzeltilmeli" in summary


def test_slow_binance_publication_and_quiet_liquidations_warn(tmp_path):
    code, summary, *_ = run(tmp_path, bn_lag_s=120, liquidation=None)
    assert code == 0
    assert "YETERSİZ, artırılmalı" in summary
    assert "likidasyon olmadı" in summary


def test_freqtrade_init_failure_is_critical_and_rest_still_runs(tmp_path):
    clock = FakeClock()

    def broken():
        raise RuntimeError("markets yüklenemedi")

    code = wp.main(transport=ProbeTransport(clock), exchange_factory=broken, reports_dir=tmp_path, clock=clock)
    summary = next(tmp_path.glob("weex_probe_*.txt")).read_text(encoding="utf-8")
    assert code == 1 and "SONUÇ: HATA" in summary
    assert "[HATA   ] Freqtrade     borsa_baslat" in summary
    assert "[ATLANDI] Freqtrade     diger" in summary
    assert "Karar – historyKlines" in summary  # ham testler yine çalıştı


# --- saf yardımcılar ----------------------------------------------------------


def test_continuity_counts_gaps_at_chunk_borders():
    tf = 5 * MIN
    since = 1_000 * tf + 7  # yukarı yuvarlanır
    times = [1_001 * tf + i * tf for i in range(300)]
    times.remove(1_001 * tf + 100 * tf)  # parça sınırı
    times.remove(1_001 * tf + 150 * tf)  # parça içi
    c = wp.continuity(times, tf, since)
    assert c.n == 298 and len(c.missing) == 2 and c.missing_at_chunk_border == 1 and c.head_missing == 0


def test_history_semantics_decides_first_or_last():
    tf = 5 * MIN
    t0 = 10_000 * tf
    exact = [t0 + i * tf for i in range(100)]
    first = wp.history_semantics(t0, tf, [t0 + i * tf for i in range(6)], exact, exact)
    assert first["start_inclusive"] and first["end_inclusive"] and first["chunk_ok"] and first["wide_side"] == "İLK 100"
    last = wp.history_semantics(t0, tf, [t0 + i * tf for i in range(1, 5)], exact[1:],
                                [t0 + i * tf for i in range(201, 301)])
    assert not last["start_inclusive"] and not last["end_inclusive"] and not last["chunk_ok"]
    assert last["wide_side"] == "SON 100"


def test_funding_side_and_binance_ts_meaning():
    h8 = 8 * 3_600_000
    now = 1_000 * h8
    start = now - 180 * h8
    assert wp.funding_side([start + i * h8 for i in range(10)], start, now) == "İLK"
    assert wp.funding_side([now - i * h8 for i in range(10)], start, now) == "SON"
    assert wp.bn_ts_meaning(0, 5 * MIN + 30_000) == ("dönem başlangıcı", 30_000)
    assert wp.bn_ts_meaning(0, 20_000) == ("dönem sonu / anlık görüntü", 20_000)


def test_liquidation_shape_and_symbol_helpers():
    shape = wp.liquidation_shape([{"e": "forceOrder", "o": {"s": "X", "st": 2}}])
    assert shape["shape"] == "liste" and shape["st"] == 2 and not shape["has_ps"]
    assert wp.is_liquidation({"e": "forceOrder"}) and not wp.is_liquidation({"result": None, "id": 1})
    assert wp.digit_symbols(["BTCUSDT", "1000PEPEUSDT", "1INCHUSDT"]) == ["1000PEPEUSDT", "1INCHUSDT"]
    assert wp.meme_naming(["1000PEPEUSDT", "PEPEUSDT", "SHIBUSDT"], ("PEPE", "SHIB", "BONK")) == \
        ["PEPEUSDT/1000PEPEUSDT", "SHIBUSDT"]
    assert wp.body_error({"code": -1121, "msg": "Invalid symbol"}) == "kod -1121: Invalid symbol"
    assert wp.body_error({"code": "200", "msg": "success"}) is None
