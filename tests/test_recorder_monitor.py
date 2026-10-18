"""İzleme: WEEX erişimi, bot canlılığı, Binance; tek uyarı, hatırlatma, düzelme, açılış süresi (grace)."""

import asyncio

from cyberbot.recorder.monitor import Monitor, SourceHealth, Status, fmt_duration
from cyberbot.uptime import UptimeStore
from tests.recorder_fakes import MIN, T0, mon_cfg

S = 1000


class Harness:
    def __init__(self, tmp_path, **cfg):
        self.status = Status()
        self.events = UptimeStore(tmp_path / "uptime.sqlite", "recorder")
        self.bot = UptimeStore(tmp_path / "uptime.sqlite", "freqtrade")
        self.sent: list[str] = []
        self.mon = Monitor(mon_cfg(**cfg), status=self.status, notifier=None, events=self.events,
                           bot_store=self.bot, started_ms=T0, send=self.sent.append)

    def check(self, at_ms):
        asyncio.run(self.mon.check(at_ms))

    def kinds(self):
        return [e.kind for e in self.events.events("recorder")]


def bot_alive(h, at_ms):
    sid = h.bot.start_session(at_ms=at_ms)
    return sid


def test_weex_unreachable_alert_once_reminder_and_recovery(tmp_path):
    h = Harness(tmp_path, realert_minutes=180)
    sid = bot_alive(h, T0)
    w = h.status.weex
    w.ok(T0 + 400 * S)
    for t in (430, 460, 490, 520):
        w.fail(T0 + t * S, "ConnectionError")
        h.bot.heartbeat(sid, at_ms=T0 + t * S)
        h.check(T0 + t * S)
    assert h.sent == []                                  # 120 sn dolmadı
    w.fail(T0 + 530 * S, "x")
    h.check(T0 + 530 * S)                                # son başarıdan 130 sn
    assert len(h.sent) == 1
    msg = h.sent[0]
    assert "WEEX'e ulaşılamıyor" in msg and "bot yeni işlem" in msg and "UTC" in msg and "İstanbul" in msg
    h.bot.heartbeat(sid, at_ms=T0 + 600 * S)
    h.check(T0 + 600 * S)
    assert len(h.sent) == 1                              # tekrar yok (dedup)
    h.bot.heartbeat(sid, at_ms=T0 + 530 * S + 180 * MIN)
    h.check(T0 + 530 * S + 180 * MIN)
    assert len(h.sent) == 2 and h.sent[1].startswith("HATIRLATMA")
    w.ok(T0 + 530 * S + 181 * MIN)
    h.bot.heartbeat(sid, at_ms=T0 + 530 * S + 181 * MIN)
    h.check(T0 + 530 * S + 181 * MIN)
    assert h.sent[-1].startswith("DÜZELDİ: WEEX")
    assert h.kinds() == ["weex_unreachable", "weex_recovered"]


def test_grace_period_suppresses_alerts(tmp_path):
    h = Harness(tmp_path, grace_s=300)
    h.status.weex.fail(T0 + 10 * S, "x")
    h.check(T0 + 299 * S)                                # bot yok + WEEX yok ama açılış süresi
    assert h.sent == [] and h.kinds() == []
    h.check(T0 + 301 * S)
    assert {k for k in h.kinds()} == {"weex_unreachable", "bot_stale"}


def test_weex_never_succeeded_counts_from_start(tmp_path):
    h = Harness(tmp_path)
    bot_alive(h, T0 + 299 * S)
    h.status.weex.fail(T0 + 200 * S, "x")
    h.check(T0 + 301 * S)
    assert h.kinds() == ["weex_unreachable"]


def test_bot_stale_and_recovered(tmp_path):
    h = Harness(tmp_path, bot_heartbeat_stale_s=300)
    sid = bot_alive(h, T0)
    h.check(T0 + 301 * S)                                # son kalp atışı T0: 301 sn
    assert h.kinds() == ["bot_stale"] and h.sent[0].startswith("UYARI: Bot çalışmıyor")
    h.check(T0 + 400 * S)
    assert len(h.sent) == 1
    h.bot.heartbeat(sid, at_ms=T0 + 450 * S)
    h.check(T0 + 460 * S)
    assert h.kinds() == ["bot_stale", "bot_recovered"]
    h.bot.stop_session(sid, at_ms=T0 + 500 * S)          # düzgün kapanış da 'çalışmıyor'
    h.check(T0 + 510 * S)
    assert h.kinds()[-1] == "bot_stale" and "kapatıldı" in h.sent[-1]


def test_binance_418_alerts_immediately_and_recovers(tmp_path):
    h = Harness(tmp_path)
    bot_alive(h, T0 + 400 * S)
    h.status.binance_ban_until_ms = T0 + 1000 * S
    h.check(T0 + 401 * S)
    assert h.kinds() == ["binance_unreachable"] and "418" in h.sent[0]
    h.bot.heartbeat(h.bot.sessions()[-1].id, at_ms=T0 + 1000 * S)
    h.check(T0 + 1001 * S)
    assert h.kinds() == ["binance_unreachable", "binance_recovered"]


def test_binance_ws_down_long_alerts(tmp_path):
    h = Harness(tmp_path, binance_alert_after_s=600)
    bot_alive(h, T0 + 900 * S)
    h.status.ws_enabled = True
    h.status.ws_down_since_ms = T0 + 300 * S
    h.check(T0 + 899 * S)
    assert h.kinds() == []
    h.check(T0 + 901 * S)
    assert h.kinds() == ["binance_unreachable"] and "likidasyon" in h.sent[0]


def test_monitor_never_raises(tmp_path):
    h = Harness(tmp_path)

    class Broken:
        def sessions(self, *_):
            raise RuntimeError("db bozuk")

        def add_event(self, *a, **k):
            raise RuntimeError("db bozuk")

    h.mon.bot_store = Broken()
    h.mon.events = Broken()
    h.mon._send = lambda text: (_ for _ in ()).throw(RuntimeError("telegram"))
    h.status.weex.fail(T0, "x")
    h.check(T0 + 3600 * S)  # istisna fırlatmaz
    assert h.mon.weex.active


def test_source_health_and_duration_text():
    hl = SourceHealth("x")
    assert hl.down_for_ms(T0, T0 - 1) == 0
    hl.fail(T0, "e")
    assert hl.down_for_ms(T0 + 5, T0 - 10) == 15
    hl.ok(T0 + 6)
    assert hl.down_for_ms(T0 + 100, 0) == 0
    assert fmt_duration(7 * MIN) == "7 dakika" and fmt_duration(125 * MIN) == "2 saat 5 dakika"
