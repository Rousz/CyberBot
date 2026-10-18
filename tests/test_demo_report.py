"""demo_report: Freqtrade'in kendi persistence katmanıyla yazılmış dry-run işlem DB'si +
çöküş boşluklu uptime oturumları + küçük türev DB'si -> uptime %, ayrılan işlemler, istatistikler."""

import sqlite3
from datetime import datetime, timezone

import pytest

from cyberbot import demo_report as dr
from cyberbot.uptime import UptimeStore

MIN = 60_000
HOUR = 60 * MIN
NOW = 1_776_000_000_000 // HOUR * HOUR  # sabit "şimdi"
T0 = NOW - 30 * HOUR


def dt(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


@pytest.fixture
def data_env(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("CYBERBOT_DATA_DIR", str(data))
    monkeypatch.setenv("CYBERBOT_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("CYBERBOT_CONFIG", str(tmp_path / "yok.json"))
    return data


def make_trades_db(path, trades):
    """Freqtrade 2026.9 persistence ile gerçek tradesv3 şeması (trades + trade_custom_data)."""
    from freqtrade.enums import TradingMode
    from freqtrade.persistence import Trade, init_db

    init_db(f"sqlite:///{path}")
    try:
        for spec in trades:
            spec = dict(spec)
            sl = spec.pop("sl", None)
            is_open = spec.pop("is_open", False)
            t = Trade(exchange="weex", stake_amount=spec.pop("stake", 100.0), fee_open=0.0008, fee_close=0.0008,
                      trading_mode=TradingMode.FUTURES, leverage=3.0, is_open=is_open,
                      open_date=dt(spec.pop("open")), **spec)
            Trade.session.add(t)
            Trade.commit()
            if sl is not None:
                t.set_custom_data("sl", sl)
    finally:
        Trade.session.remove()


def closed(pair, open_ms, close_ms, pnl, reason, *, short=False, sl=None, open_rate=100.0, amount=2.0, funding=0.0):
    return {"pair": pair, "open": open_ms, "close_date": dt(close_ms), "close_rate": open_rate, "is_short": short,
            "open_rate": open_rate, "amount": amount, "close_profit_abs": pnl, "close_profit": pnl / 100,
            "exit_reason": reason, "funding_fees": funding, "sl": sl}


def closed_count(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT COUNT(*) FROM trades WHERE close_date IS NOT NULL").fetchone()[0]


def make_uptime(data):
    ft = UptimeStore(data / "uptime.sqlite", "freqtrade")
    rec = UptimeStore(data / "uptime.sqlite", "recorder")
    s1 = ft.start_session(at_ms=T0)
    ft.stop_session(s1, at_ms=T0 + 10 * HOUR)  # temiz
    s2 = ft.start_session(at_ms=T0 + 11 * HOUR)
    ft.heartbeat(s2, at_ms=T0 + 20 * HOUR)  # çöktü (kapanış kaydı yok)
    s3 = ft.start_session(at_ms=T0 + 21 * HOUR)
    ft.heartbeat(s3, at_ms=NOW - 30_000)  # şu an çalışıyor
    r1 = rec.start_session(at_ms=T0)
    rec.heartbeat(r1, at_ms=NOW - 20_000)
    ft.add_event("exchange_down", "BTC 5m bayat", at_ms=T0 + 5 * HOUR)
    ft.add_event("exchange_recovered", "", at_ms=T0 + 5 * HOUR + 10 * MIN)


def make_derivs(data):
    with sqlite3.connect(data / "derivs.sqlite") as conn:
        conn.executescript("""
            CREATE TABLE bn_futures_data(symbol TEXT, period TEXT, ts_ms INTEGER, avail_ms INTEGER);
            CREATE TABLE weex_premium(symbol TEXT, bucket_ms INTEGER, avail_ms INTEGER);
            CREATE TABLE ws_sessions(conn_id INTEGER PRIMARY KEY, url TEXT, open_ms INTEGER, close_ms INTEGER,
                                     reason TEXT);
            CREATE TABLE gaps(id INTEGER PRIMARY KEY, source TEXT, symbol TEXT, start_ms INTEGER, end_ms INTEGER,
                              reason TEXT, detected_ms INTEGER, state TEXT);
        """)
        conn.executemany("INSERT INTO bn_futures_data VALUES ('BTCUSDT', '5m', ?, ?)",
                         [(NOW - i * 5 * MIN, NOW) for i in range(1, 400)])  # 287 tanesi son 24 saatte
        conn.execute("INSERT INTO weex_premium VALUES ('BTCUSDT', ?, ?)", (NOW - MIN, NOW))
        conn.execute("INSERT INTO ws_sessions(url, open_ms, close_ms, reason) VALUES (?, ?, ?, 'rotate')",
                     ("wss://fstream.binance.com/market/ws", NOW - 30 * HOUR, NOW - 12 * HOUR))
        conn.execute("INSERT INTO ws_sessions(url, open_ms, close_ms) VALUES (?, ?, NULL)",
                     ("wss://fstream.binance.com/market/ws", NOW - 6 * HOUR))
        conn.execute("INSERT INTO gaps(source, symbol, start_ms, end_ms, detected_ms, state) VALUES "
                     "('bn_futures_data', 'BTCUSDT', 1, 2, 3, 'open')")


def run(argv=()):
    return dr.main(list(argv), now_ms=NOW)


def summary_text(tmp_path):
    return next((tmp_path / "reports").glob("demo_report_*.txt")).read_text(encoding="utf-8")


def test_full_report_excludes_outage_trades_and_computes_stats(data_env, tmp_path):
    make_uptime(data_env)
    make_derivs(data_env)
    make_trades_db(data_env / "tradesv3.dryrun.sqlite", [
        closed("BTC/USDT:USDT", T0 + 1 * HOUR, T0 + 2 * HOUR, 10.0, "tp", sl=95.0, open_rate=100.0, amount=2.0),
        closed("ETH/USDT:USDT", T0 + 3 * HOUR, T0 + 4 * HOUR, -5.0, "stop_loss", short=True, sl=2020.0,
               open_rate=2000.0, amount=0.25, funding=-0.5),
        # bot kapalıyken (10h-11h) açık kalan işlem -> istatistik dışı
        closed("SOL/USDT:USDT", T0 + 9 * HOUR, T0 + 12 * HOUR, 50.0, "tp"),
        # WEEX verisi bayatken (5h - 5h10m) açık -> istatistik dışı
        closed("BTC/USDT:USDT", T0 + 4 * HOUR + 50 * MIN, T0 + 5 * HOUR + 20 * MIN, -20.0, "stop_loss"),
        closed("ETH/USDT:USDT", T0 + 22 * HOUR, T0 + 23 * HOUR, 4.0, "trailing_stop_loss", short=True),
        {"pair": "BTC/USDT:USDT", "open": NOW - HOUR, "open_rate": 74000.0, "amount": 0.004, "is_open": True,
         "is_short": False, "funding_fees": 0.25},
    ])
    assert closed_count(data_env / "tradesv3.dryrun.sqlite") == 5
    code = run()
    text = summary_text(tmp_path)
    assert code == 0
    assert "SONUÇ: BAŞARILI (uyarılarla)" in text
    assert "UTC (İstanbul" in text
    # uptime: 30 saatte 28 saat 1 dk çalıştı (çöküş: son kalp atışı + 60 sn)
    assert "%93.39" in text and "%95'in altında" in text
    assert "yeniden başlatma 2, temiz olmayan kapanış 1" in text
    assert "şu an çalışıyor" in text
    kesinti = text.split("Kesinti dönemleri – bot:")[1].split("\n\n")[0]
    assert kesinti.count("→") == 2 and "(60 dk)" in kesinti and "(59 dk)" in kesinti
    assert "kaydedici_uptime" in text and "%100.00" in text
    # kesintili işlemler ayrıldı
    assert "kapanmış 5 (temiz 3, kesintili 2), açık 1" in text
    dirty = text.split("Kesintili dönemle kesişen işlemler (istatistik dışı):")[1].split("\n\n")[0]
    assert "SOL/USDT:USDT" in dirty and "bot kapalı" in dirty and "WEEX verisi bayat" in dirty
    # temiz istatistikler: +10, -5, +4
    clean = text.split("Temiz işlemlerin sonuçları (kesintili işlemler hariç):")[1].split("\n\n")[0]
    assert "işlem sayısı: 3 (kazanan 2, kaybeden 1)" in clean
    assert "kazanma oranı: %66.7" in clean
    assert "+9.00 USDT (başlangıç 1,000 USDT'nin %+0.90'i)" in clean
    assert "kâr faktörü: 2.80" in clean
    assert "ortalama R: +0.00 (2 işlemde stop kaydı var)" in clean  # +1R ve -1R
    assert "5.00 USDT (%0.50)" in clean
    assert "long: 1 işlem" in text and "short: 2 işlem" in text
    assert "stop_loss + trailing_stop_loss: 2 işlem, kazanma %50, -1.00 USDT" in text
    assert "en iyi: BTC/USDT:USDT +10.00 USDT (1)\n" in text and "en kötü: ETH/USDT:USDT -1.00 USDT (2)\n" in text
    assert "Açık işlemler:\n  #6 BTC/USDT:USDT long 3x" in text
    assert dr.FEE_LINE in text
    assert "funding toplamı -0.25 USDT" in text
    # türev verisi
    derivs = text.split("Türev verisi (son 24 saat):")[1].split("\n\n")[0]
    assert "bn_futures_data: 288 satır" in derivs and "weex_premium: 1 satır" in derivs
    assert "bn_liquidations: tablo yok" in derivs
    assert "açık boşluklar (kaynak başına): bn_futures_data 1" in derivs
    assert "likidasyon WS kapsaması: %75.0" in derivs
    assert "Uyarılar:" in text and "likidasyon WS kapsaması %75.0" in text
    assert (tmp_path / "reports" / "logs" / "demo_report_last.txt").exists()


def test_days_window_limits_closed_trades(data_env, tmp_path):
    make_uptime(data_env)
    make_trades_db(data_env / "tradesv3.dryrun.sqlite", [
        closed("BTC/USDT:USDT", T0 + 1 * HOUR, T0 + 2 * HOUR, 10.0, "tp"),
        closed("ETH/USDT:USDT", T0 + 22 * HOUR, T0 + 23 * HOUR, 4.0, "tp"),
    ])
    assert run(argv=["--days", "0.5"]) == 0
    text = summary_text(tmp_path)
    assert "kapanmış 1 (temiz 1, kesintili 0)" in text
    assert "%100.00" in text  # son 12 saatte bot hep açıktı


def test_missing_databases_still_produce_report(data_env, tmp_path):
    assert run() == 0
    text = summary_text(tmp_path)
    assert "SONUÇ: BAŞARILI" in text
    assert "işlem veritabanı yok" in text and "çalışma kaydı yok" in text
    assert "türev veritabanı yok" in text and "henüz işlem yok" in text
    assert dr.FEE_LINE in text


def test_empty_trades_database(data_env, tmp_path):
    make_trades_db(data_env / "tradesv3.dryrun.sqlite", [])
    make_uptime(data_env)
    assert run() == 0
    text = summary_text(tmp_path)
    assert "0 işlem kaydı" in text and "dönemde kapanmış işlem yok" in text
    assert "kapanmış işlem yok" in text.split("Temiz işlemlerin sonuçları")[1]


def test_event_outage_without_recovery_ends_with_its_session():
    from cyberbot.uptime import Event, Session

    sessions = {"freqtrade": [Session(1, "freqtrade", 0, 5 * HOUR, None, None)]}  # 5h'de çöktü
    events = [Event(1, "freqtrade", 2 * HOUR, "exchange_down", "")]
    periods = dr.event_outages(events, sessions, 0, 10 * HOUR)
    assert periods == [(2 * HOUR, 5 * HOUR + MIN, "exchange_down")]
    short = [Event(1, "freqtrade", 2 * HOUR, "exchange_down", ""), Event(2, "freqtrade", 2 * HOUR + MIN,
                                                                        "exchange_recovered", "")]
    assert dr.event_outages(short, sessions, 0, 10 * HOUR) == []  # 2 dk'dan kısa


def test_trade_stats_drawdown_and_profit_factor():
    def t(i, pnl):
        return dr.TradeRow(i, "X", False, False, i, i + 1, 1.0, 1.0, 1.0, 10.0, 3.0, pnl, None, "tp", 0, 0, 0)

    s = dr.trade_stats([t(1, 50), t(2, -30), t(3, -30), t(4, 100)], 1000)
    assert s.n == 4 and s.wins == 2 and s.total == 90
    assert s.profit_factor == pytest.approx(150 / 60)
    assert s.max_dd_abs == 60 and s.max_dd_pct == pytest.approx(100 * 60 / 1050)
    assert dr.trade_stats([t(1, 5)], 1000).profit_factor is None
    assert dr.parse_dt_ms("2026-10-17 23:09:53.539730") == 1_792_278_593_539
