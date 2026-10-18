"""Ortak modüller: paths, settings, uptime, notify, launch."""

import json

import pytest

from cyberbot import launch, notify, paths, settings, uptime

MIN = 60_000
HOUR = 60 * MIN


# --- paths / settings -------------------------------------------------------


def test_paths_follow_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CYBERBOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CYBERBOT_CONFIG", str(tmp_path / "c.json"))
    assert paths.uptime_db() == tmp_path / "data" / "uptime.sqlite"
    assert paths.derivs_db().name == "derivs.sqlite"
    assert paths.binance_perps_json().parent == tmp_path / "data"
    assert paths.config_path() == tmp_path / "c.json"


def test_section_merges_defaults_without_mutating_them(tmp_path):
    defaults = {"a": 1, "nested": {"x": 1, "y": 2}}
    cfg = {"cyberbot": {"recorder": {"nested": {"y": 5}, "b": 3}}}
    merged = settings.section("recorder", defaults, cfg)
    assert merged == {"a": 1, "b": 3, "nested": {"x": 1, "y": 5}}
    assert defaults == {"a": 1, "nested": {"x": 1, "y": 2}}
    assert settings.section("missing", defaults, {}) == defaults


def test_load_config_reads_file_or_returns_empty(tmp_path):
    path = tmp_path / "config.json"
    assert settings.load_config(path) == {}
    path.write_text(json.dumps({"cyberbot": {"strategy": {"leverage": 2}}}), encoding="utf-8")
    assert settings.section("strategy", {"leverage": 3}, settings.load_config(path)) == {"leverage": 2}


# --- uptime -----------------------------------------------------------------


def test_store_records_sessions_heartbeats_and_events(tmp_path):
    store = uptime.UptimeStore(tmp_path / "u.sqlite", "freqtrade")
    sid = store.start_session(version="t", at_ms=1_000)
    store.heartbeat(sid, at_ms=61_000)
    store.add_event("exchange_down", "BTC 5m eski", at_ms=70_000)
    store.stop_session(sid, at_ms=90_000)
    store.stop_session(sid, kind="again", at_ms=99_000)  # ikinci kapanış yok sayılır
    (s,) = store.sessions()
    assert (s.started_ms, s.stopped_ms, s.stop_kind) == (1_000, 90_000, "clean")
    assert store.events()[0].kind == "exchange_down"
    assert store.last_heartbeat_ms() == 90_000
    other = uptime.UptimeStore(tmp_path / "u.sqlite", "recorder")
    assert other.sessions() == [] and other.last_heartbeat_ms() is None


def test_summarize_counts_crash_gap_and_running_session():
    sessions = [
        uptime.Session(1, "freqtrade", 0, 2 * HOUR, 2 * HOUR, "clean"),          # 0-2h temiz
        uptime.Session(2, "freqtrade", 3 * HOUR, 5 * HOUR - MIN, None, None),    # çöktü ~5h
        uptime.Session(3, "freqtrade", 6 * HOUR, 10 * HOUR - 30_000, None, None),  # hâlâ çalışıyor
    ]
    s = uptime.summarize(sessions, 0, 10 * HOUR)
    assert s.up_ms == 2 * HOUR + 2 * HOUR + 4 * HOUR
    assert s.uptime_pct == pytest.approx(80.0)
    assert s.downtime == [(2 * HOUR, 3 * HOUR), (5 * HOUR, 6 * HOUR)]
    assert s.sessions == 3 and s.unclean_stops == 1


def test_summarize_clips_to_window_and_filters_short_gaps():
    sessions = [
        uptime.Session(1, "f", -HOUR, HOUR, HOUR, "clean"),
        uptime.Session(2, "f", HOUR + 30_000, 3 * HOUR, 3 * HOUR, "clean"),
    ]
    s = uptime.summarize(sessions, 0, 4 * HOUR, min_gap_ms=2 * MIN)
    assert s.up_ms == 3 * HOUR - 30_000
    assert s.downtime == [(3 * HOUR, 4 * HOUR)]  # 30 sn'lik yeniden başlatma listede yok
    assert uptime.summarize([], 0, HOUR).downtime == [(0, HOUR)]
    assert uptime.summarize([], 5, 5).uptime_pct == 0.0


def test_heartbeat_thread_updates_store(tmp_path):
    store = uptime.UptimeStore(tmp_path / "u.sqlite", "freqtrade")
    sid = store.start_session(at_ms=1)
    hb = uptime.Heartbeat(store, sid, interval_s=0.01).start()
    import time

    deadline = time.time() + 5
    while store.last_heartbeat_ms() == 1 and time.time() < deadline:
        time.sleep(0.01)
    hb.stop()
    assert store.last_heartbeat_ms() > 1


def test_heartbeat_pauses_while_not_alive_and_opens_new_session_after_stall(tmp_path):
    store = uptime.UptimeStore(tmp_path / "u.sqlite", "freqtrade")
    sid = store.start_session(at_ms=1)
    state = {"alive": True}
    hb = uptime.Heartbeat(store, sid, is_alive=lambda: state["alive"], version="v1")
    hb.beat()
    first_beat = store.last_heartbeat_ms()
    state["alive"] = False
    hb.beat()
    hb.beat()
    assert hb.stalled and store.last_heartbeat_ms() == first_beat and hb.session_id == sid
    state["alive"] = True
    hb.beat()
    old, new = store.sessions()
    assert old.id == sid and old.stop_kind == "stalled" and old.stopped_ms == first_beat + 60_000
    assert new.id == hb.session_id != sid and new.version == "v1" and new.stopped_ms is None
    assert not hb.stalled


def test_heartbeat_treats_failing_alive_check_as_not_alive(tmp_path):
    store = uptime.UptimeStore(tmp_path / "u.sqlite", "freqtrade")
    sid = store.start_session(at_ms=1)

    def broken():
        raise RuntimeError("x")

    hb = uptime.Heartbeat(store, sid, is_alive=broken)
    hb.beat()
    assert hb.stalled and store.last_heartbeat_ms() == 1


# --- notify -----------------------------------------------------------------


class FakeResponse:
    def __init__(self, status=200, ok=True):
        self.status_code = status
        self._ok = ok
        self.text = '{"ok": false, "description": "bad"}'

    def json(self):
        return {"ok": self._ok}


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.posts = []
        self.response = response or FakeResponse()
        self.exc = exc

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        if self.exc:
            raise self.exc
        return self.response


def test_notifier_sends_plain_text_and_dedups():
    session = FakeSession()
    n = notify.TelegramNotifier("123:SECRET", "42", session=session)
    assert n.send("WEEX'e ulaşılamıyor", dedup_key="weex") is True
    assert n.send("WEEX'e ulaşılamıyor", dedup_key="weex") is False
    url, payload = session.posts[0]
    assert url.endswith("/bot123:SECRET/sendMessage") and payload["chat_id"] == "42"
    assert "parse_mode" not in payload and len(session.posts) == 1


def test_notifier_disabled_and_errors_never_raise_or_leak(caplog):
    assert notify.TelegramNotifier("", "42").send("x") is False
    session = FakeSession(exc=ConnectionError("https://api.telegram.org/bot123:SECRET/sendMessage failed"))
    n = notify.TelegramNotifier("123:SECRET", "42", session=session)
    with caplog.at_level("WARNING"):
        assert n.send("x") is False
    assert "SECRET" not in caplog.text and "***" in caplog.text
    assert notify.TelegramNotifier("123:SECRET", "42", session=FakeSession(FakeResponse(400, False))).send("x") is False


def test_md_escape():
    assert notify.md_escape("BTC_USDT *x* `y` [z]") == "BTC\\_USDT \\*x\\* \\`y\\` \\[z]"


# --- launch -----------------------------------------------------------------


def test_launch_enables_telegram_only_with_token_and_chat_id():
    env, notes = launch.build_env({"TELEGRAM_TOKEN": " 1:abc ", "TELEGRAM_CHAT_ID": "42", "PATH": "/bin"})
    assert env["FREQTRADE__TELEGRAM__ENABLED"] == "true"
    assert env["FREQTRADE__TELEGRAM__TOKEN"] == "1:abc" and env["FREQTRADE__TELEGRAM__CHAT_ID"] == "42"
    assert "TELEGRAM_TOKEN" not in env and env["PATH"] == "/bin"
    env, notes = launch.build_env({"TELEGRAM_TOKEN": "1:abc", "TELEGRAM_CHAT_ID": ""})
    assert env["FREQTRADE__TELEGRAM__ENABLED"] == "false" and "FREQTRADE__TELEGRAM__TOKEN" not in env
    assert "UYARI" in notes[0]


def test_launch_strips_exchange_secrets_and_forces_dry_run():
    env, _ = launch.build_env({"FREQTRADE__EXCHANGE__KEY": "k", "FREQTRADE__EXCHANGE__SECRET": "s",
                               "WEEX_API_KEY": "k2", "OTHER": "1"})
    assert set(env) == {"OTHER", "FREQTRADE__TELEGRAM__ENABLED"}
    assert launch.build_argv(["trade", "--config", "c.json"]) == ["freqtrade", "trade", "--dry-run", "--config",
                                                                  "c.json"]
    assert launch.build_argv(["trade", "--dry-run"]).count("--dry-run") == 1
    assert launch.build_argv(["download-data", "-t", "5m"]) == ["freqtrade", "download-data", "-t", "5m"]
