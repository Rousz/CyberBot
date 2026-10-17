from datetime import datetime, timezone

import pytest

from cyberbot import connection_test as ct
from tests.fakes import FakeCcxt, FakeTransport, load, now_ms, synthetic_klines

TOKEN = "123456789:AAFakeTelegramTokenForTests_xyz"
CHAT_ID = "555000111"
WEEX_KEYS = {"WEEX_API_KEY": "weexkey-AAAA1111", "WEEX_API_SECRET": "weexsecret-BBBB2222", "WEEX_API_PASSPHRASE": "pass-CCCC3333"}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(ct, "REQUEST_PAUSE", 0)
    FakeCcxt.created.clear()


def run(tmp_path, env=None, transport=None, factory=FakeCcxt):
    env = {"TELEGRAM_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT_ID} if env is None else env
    transport = transport or FakeTransport()
    code = ct.main(transport=transport, ccxt_factory=factory, reports_dir=tmp_path, env=env)
    summary = next(tmp_path.glob("connection_test_*.txt")).read_text(encoding="utf-8")
    log = next((tmp_path / "logs").glob("connection_test_*.log")).read_text(encoding="utf-8")
    return code, summary, log, transport


def all_sample_text(tmp_path):
    return "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "samples").glob("*.json"))


# --- uçtan uca (sahte ağ ile) ----------------------------------------------


def test_full_run_success(tmp_path):
    code, summary, log, t = run(tmp_path)
    assert code == 0
    assert "SONUÇ: BAŞARILI   (" in summary
    assert "UYARI 0, HATA 0" in summary
    assert "UTC (İstanbul" in summary
    for label in ("WEEX 5m mum geçmişi", "Ortak pariteler", "Fiyat farkı", "WEEX USDT-M perpetual sayısı"):
        assert label in summary
    # gizli bilgiler hiçbir dosyada yok
    for text in (summary, log, all_sample_text(tmp_path)):
        assert TOKEN not in text
        assert CHAT_ID not in text
    # Telegram'a özet mesajı gitti
    assert len(t.posts) == 1
    url, payload = t.posts[0]
    assert url.endswith("/sendMessage") and payload["chat_id"] == CHAT_ID
    assert "BAŞARILI" in payload["text"]
    # yeni Binance WS adresleri kullanıldı
    ws_urls = [u for u, _, _ in t.ws_calls]
    assert f"{ct.BINANCE_WS_MARKET}/btcusdt@kline_5m" in ws_urls
    assert f"{ct.BINANCE_WS_PUBLIC}/btcusdt@bookTicker" in ws_urls
    assert f"{ct.BINANCE_WS_MARKET}/!forceOrder@arr" in ws_urls
    # WEEX WS'e User-Agent başlığı ve abonelik gönderildi
    weex_ws = next(c for c in t.ws_calls if c[0] == ct.WEEX_WS_PUBLIC)
    assert weex_ws[2]["User-Agent"] and weex_ws[1][0]["params"] == ["BTCUSDT@ticker"]
    assert (tmp_path / "samples" / "weex_exchangeInfo.json").exists()
    assert not list((tmp_path / "samples").glob("*telegram*"))


def test_binance_451_reported_and_other_rest_skipped(tmp_path):
    t = FakeTransport(failures={"fapi.binance.com": ct.HttpStatusError(451, '{"code":0,"msg":"restricted location"}')})
    code, summary, _, t = run(tmp_path, transport=t)
    assert code == 1
    assert "SONUÇ: HATA" in summary
    assert "HTTP 451 – bölge engeli" in summary
    assert "diğer REST testleri atlandı" in summary
    assert sum("fapi.binance.com" in url for url, _ in t.calls) == 1


def test_weex_rest_unreachable_still_tests_websocket(tmp_path):
    t = FakeTransport(failures={"api-contract.weex.com": ConnectionError("Failed to establish a new connection")})
    code, summary, _, t = run(tmp_path, transport=t)
    assert code == 1
    assert "ConnectionError" in summary
    assert any(url == ct.WEEX_WS_PUBLIC for url, _, _ in t.ws_calls)


def test_missing_chat_id_is_shown_only_on_screen(tmp_path, capsys):
    code, summary, log, t = run(tmp_path, env={"TELEGRAM_TOKEN": TOKEN})
    out = capsys.readouterr().out
    assert code == 0
    assert "SONUÇ: BAŞARILI (uyarılarla)" in summary
    assert CHAT_ID in out
    assert CHAT_ID not in summary and CHAT_ID not in log
    assert TOKEN not in out
    assert t.posts == []


def test_without_telegram_token_telegram_is_skipped(tmp_path):
    code, summary, _, t = run(tmp_path, env={})
    assert code == 0
    assert "TELEGRAM_TOKEN yok" in summary
    assert not any("telegram" in url for url, _ in t.calls)


def test_short_weex_history_warns_and_suggests_binance(tmp_path):
    code, summary, _, _ = run(tmp_path, transport=FakeTransport(history_days=20))
    assert code == 0
    assert "Binance verisi kullanılacak" in summary


def test_silent_weex_websocket_fails(tmp_path):
    t = FakeTransport(ws_silent=("ws-contract.weex.com", "fstream.binance.com/ws/"))
    code, summary, _, _ = run(tmp_path, transport=t)
    assert code == 1
    assert "fiyat gelmedi" in summary


def test_partial_weex_keys_warn_without_leaking(tmp_path):
    env = {"WEEX_API_KEY": WEEX_KEYS["WEEX_API_KEY"]}
    code, summary, log, _ = run(tmp_path, env=env)
    assert code == 0
    assert "üçü birden gerekli" in summary
    assert WEEX_KEYS["WEEX_API_KEY"] not in summary + log
    assert all("apiKey" not in ex.config for ex in FakeCcxt.created)


def test_full_weex_keys_use_private_read_only_call(tmp_path):
    code, summary, log, _ = run(tmp_path, env=dict(WEEX_KEYS))
    assert code == 0
    assert "API anahtarı geçerli" in summary
    private = [ex for ex in FakeCcxt.created if ex.config.get("apiKey")]
    assert len(private) == 1 and private[0].config["password"] == WEEX_KEYS["WEEX_API_PASSPHRASE"]
    for value in WEEX_KEYS.values():
        assert value not in summary + log + all_sample_text(tmp_path)


def test_unexpected_crash_still_writes_report(tmp_path, monkeypatch):
    def boom(rep, ctx):
        raise KeyError("beklenmeyen")

    monkeypatch.setattr(ct, "run_cross", boom)
    code, summary, _, _ = run(tmp_path)
    assert code == 1
    assert "script_hatasi" in summary


# --- saf yardımcılar --------------------------------------------------------


def test_weex_usdt_perps_excludes_coin_margined():
    assert ct.weex_usdt_perps(load("weex/exchangeInfo.json")) == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "WEEXONLYUSDT"]
    assert ct.weex_usdt_perps([]) == []


def test_binance_usdt_perps_excludes_quarterly_settling_and_usdc():
    assert ct.binance_usdt_perps(load("binance/exchangeInfo.json")) == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_top_by_quote_volume_orders_and_limits():
    top = ct.top_by_quote_volume(load("weex/ticker_24hr.json"), 2)
    assert [s for s, _ in top] == ["BTCUSDT", "ETHUSDT"]
    assert ct.top_by_quote_volume([{"symbol": "X", "quoteVolume": "abc"}], 5) == []


def test_book_stats_spread_and_band_depth():
    depth = load("weex/depth.json")
    stats = ct.book_stats(depth)
    mid = (74010.5 + 74010.6) / 2
    assert stats["best_bid"] == 74010.5 and stats["best_ask"] == 74010.6
    assert stats["spread_bps"] == pytest.approx(0.1 / mid * 10_000)
    assert stats["bid_usdt"] == pytest.approx(74010.5 * 0.8 + 74009.0 * 3 + 73900.0 * 5)  # 73000 bant dışı
    assert stats["ask_usdt"] == pytest.approx(74010.6 * 1.2 + 74011.0 * 2.5 + 74100.0 * 4)  # 75000 bant dışı
    with pytest.raises(ValueError):
        ct.book_stats({"bids": [], "asks": []})


def test_klines_stats_counts_gaps_and_rejects_bad_shape():
    rows = synthetic_klines(now_ms(), 10)
    n, first, last, gaps = ct.klines_stats(rows, ct.FIVE_MIN_MS)
    assert (n, gaps) == (10, 0) and last - first == 9 * ct.FIVE_MIN_MS
    del rows[4]
    assert ct.klines_stats(rows, ct.FIVE_MIN_MS)[3] == 1
    with pytest.raises(ValueError):
        ct.klines_stats([[1, 2, 3]], ct.FIVE_MIN_MS)
    with pytest.raises(ValueError):
        ct.klines_stats([], ct.FIVE_MIN_MS)


@pytest.mark.parametrize("available", [0, 2, 5, 45, 200, 400, 1000, 5000])
def test_probe_history_depth_finds_limit(available):
    calls = []

    def has_data(days):
        calls.append(days)
        return days <= available

    days, open_ended = ct.probe_history_depth(has_data)
    if available >= ct.HISTORY_PROBE_DAYS[-1]:
        assert open_ended and days == ct.HISTORY_PROBE_DAYS[-1]
    else:
        assert not open_ended and available - 2 <= days <= available
    assert len(calls) <= 20


def test_trim_sample_keeps_candle_rows_whole():
    data = {"symbols": [{"s": i, "filters": [{"a": 1}] * 5} for i in range(10)], "delivery": [1, 2, 3, 4, 5]}
    trimmed = ct.trim_sample(data)
    assert len(trimmed["symbols"]) == 3 and len(trimmed["symbols"][0]["filters"]) == 3
    assert trimmed["delivery"] == [1, 2, 3, 4, 5]
    rows = synthetic_klines(now_ms(), 10)
    assert ct.trim_sample(rows) == rows[:3] and len(ct.trim_sample(rows)[0]) == len(rows[0])


def test_weex_ping_reply():
    assert ct.weex_ping_reply({"event": "ping", "time": "1776078750000"})["method"] == "PONG"
    assert ct.weex_ping_reply({"type": "ping"})["method"] == "PONG"
    assert ct.weex_ping_reply({"e": "ticker"}) is None
    assert ct.weex_ping_reply("ping") is None


def test_http_status_error_messages():
    msg = str(ct.HttpStatusError(451, '{"code":0,"msg":"Service unavailable from a restricted location"}'))
    assert msg.startswith("HTTP 451 – bölge engeli") and "restricted location" in msg
    assert str(ct.HttpStatusError(403, "<html><body>cloudflare</body></html>")) == (
        "HTTP 403 – erişim reddedildi: IP/bölge engeli ya da bot koruması olabilir"
    )
    assert str(ct.HttpStatusError(500, "")) == "HTTP 500"


def test_previous_month():
    assert ct.previous_month(datetime(2026, 1, 15, tzinfo=timezone.utc)) == "2025-12"
    assert ct.previous_month(datetime(2026, 10, 1, tzinfo=timezone.utc)) == "2026-09"
