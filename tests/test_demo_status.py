"""demo_status: başlatma/durdurma kontrolü – geçici uptime DB, sahte saat (bekleme anında geçer)."""

import pytest

from cyberbot import demo_status as ds
from cyberbot.uptime import UptimeStore
from tests.probe_fakes import FakeClock

TOKEN = "123456789:AAFakeTelegramTokenForTests_xyz_0123456789"
SEC = 1000


class HookClock(FakeClock):
    """Her sleep'te hook(clock, n) çağırır: bekleme sırasında oturum açılmasını taklit eder."""

    def __init__(self, hook=None):
        super().__init__()
        self.hook = hook
        self.n = 0

    def sleep(self, seconds):
        super().sleep(seconds)
        self.n += 1
        if self.hook:
            self.hook(self, self.n)


@pytest.fixture
def env_paths(tmp_path):
    return {"uptime_path": tmp_path / "data" / "uptime.sqlite", "logs_dir": tmp_path / "logs",
            "reports_dir": tmp_path / "reports"}


def stores(path):
    return UptimeStore(path, "freqtrade"), UptimeStore(path, "recorder")


def summary(env_paths, slug):
    return next(env_paths["reports_dir"].glob(f"{slug}_*.txt")).read_text(encoding="utf-8")


ENV = {"TELEGRAM_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "555000111"}


def test_start_success_after_waiting_for_sessions(env_paths):
    since = FakeClock().now_ms()

    def hook(clock, n):
        if n == 2:  # 2. bekleyişte ikisi de açılır
            ft, rec = stores(env_paths["uptime_path"])
            ft.start_session(at_ms=clock.now_ms())
            rec.start_session(at_ms=clock.now_ms())

    clock = HookClock(hook)
    code = ds.run_start(since, clock=clock, env=ENV, **env_paths)
    text = summary(env_paths, "demo_start")
    assert code == 0 and "SONUÇ: BAŞARILI" in text
    assert "bot (Freqtrade): yeni oturum" in text and "kaydedici (recorder): yeni oturum" in text
    assert "telegram" in text and "açık" in text
    assert clock.sleeps[-1] == ds.SETTLE_S  # bulunduktan sonra kısa bir kararlılık beklemesi
    assert "Son " not in text  # başarıda log kuyruğu yok
    assert (env_paths["reports_dir"] / "logs" / "demo_start_last.txt").exists()
    assert TOKEN not in text and "555000111" not in text


def test_start_failure_shows_redacted_log_tail(env_paths):
    clock = FakeClock()
    since = clock.now_ms()
    _, rec = stores(env_paths["uptime_path"])
    rec.start_session(at_ms=since + 5 * SEC)
    logs = env_paths["logs_dir"]
    logs.mkdir(parents=True)
    lines = [f"satir {i}" for i in range(1, 51)]
    lines[45] = f"telegram https://api.telegram.org/bot{TOKEN}/getMe hata"
    lines[46] = '"password": "gizli-sifre-123", api_key=ABCDEF123456'
    lines[47] = "jwt " + "Zx9" * 20
    (logs / "freqtrade.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = ds.run_start(since, clock=clock, env=ENV, timeout_s=60, **env_paths)
    text = summary(env_paths, "demo_start")
    assert code == 1 and "SONUÇ: HATA" in text
    assert "[HATA   ] Durum         freqtrade" in text and "henüz hiç oturum kaydı yok" in text
    assert "[OK     ] Durum         recorder" in text
    assert "Son 30 log satırı – freqtrade.log" in text
    assert "satir 50" in text and "satir 21\n" in text and "satir 20\n" not in text  # sadece son 30
    for secret in (TOKEN, "gizli-sifre-123", "ABCDEF123456", "Zx9" * 20):
        assert secret not in text
    assert "***" in text
    assert "Açıklama – bot (Freqtrade)" in text and "WEEX'e ulaşılamıyor" in text
    assert clock.now_ms() - since >= 60 * SEC  # süre dolana kadar bekledi


def test_start_accepts_already_running_session_with_new_heartbeat(env_paths):
    clock = FakeClock()
    since = clock.now_ms()
    ft, rec = stores(env_paths["uptime_path"])
    old = ft.start_session(at_ms=since - 3_600 * SEC)
    ft.heartbeat(old, at_ms=since + 10 * SEC)
    rec.start_session(at_ms=since + 2 * SEC)
    code = ds.run_start(since, clock=clock, env={}, settle_s=0, **env_paths)
    text = summary(env_paths, "demo_start")
    assert code == 0 and "zaten çalışıyordu" in text
    assert "[UYARI  ] Genel         telegram" in text  # .env'de Telegram boş


def test_start_detects_crash_during_settle(env_paths):
    since = FakeClock().now_ms()
    ft, rec = stores(env_paths["uptime_path"])
    sid = ft.start_session(at_ms=since + SEC)
    rec.start_session(at_ms=since + SEC)

    def hook(clock, n):
        ft.stop_session(sid, kind="clean", at_ms=clock.now_ms())

    code = ds.run_start(since, clock=HookClock(hook), env=ENV, **env_paths)
    text = summary(env_paths, "demo_start")
    assert code == 1 and "açıldı ama hemen kapandı" in text


def test_stop_clean_and_unclean(env_paths):
    clock = FakeClock()
    since = clock.now_ms()
    ft, rec = stores(env_paths["uptime_path"])
    a = ft.start_session(at_ms=since - 7_200 * SEC)
    b = rec.start_session(at_ms=since - 7_200 * SEC)
    ft.stop_session(a, at_ms=since + 20 * SEC)
    rec.stop_session(b, at_ms=since + 5 * SEC)
    assert ds.run_stop(since, clock=clock, env=ENV, **env_paths) == 0
    text = summary(env_paths, "demo_stop")
    assert "SONUÇ: BAŞARILI" in text and text.count("temiz kapandı") == 2 and "2.0 saat" in text

    for p in env_paths["reports_dir"].glob("demo_stop_*.txt"):
        p.unlink()
    rec.start_session(at_ms=since + 60 * SEC)  # yeni oturum kapanış kaydı yazmadan öldü
    clock2 = FakeClock(since + 120 * SEC)
    assert ds.run_stop(since + 100 * SEC, clock=clock2, env=ENV, timeout_s=10, **env_paths) == 1
    text = summary(env_paths, "demo_stop")
    assert "kapanış kaydı yok" in text and "Son log satırları – recorder.log" in text
    assert "dosya yok" in text


def test_stop_without_database_is_a_warning(env_paths):
    assert ds.run_stop(1, clock=FakeClock(), env={}, **env_paths) == 0
    assert "demo test hiç başlatılmamış" in summary(env_paths, "demo_stop")


def test_main_uses_paths_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CYBERBOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CYBERBOT_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("CYBERBOT_REPO_DIR", str(tmp_path))
    assert ds.main(["stop", "--since", "1776000000000"]) == 0
    assert list((tmp_path / "reports").glob("demo_stop_*.txt"))


def test_classify_start_states():
    from cyberbot.uptime import Session

    now = 10_000_000
    assert ds.classify_start([], 0, now).kind == "none"
    stale = Session(1, "freqtrade", now - 900_000, now - 600_000, None, None)
    assert ds.classify_start([stale], now - 60_000, now).kind == "stale"
    stopped = Session(2, "freqtrade", now - 900_000, now - 600_000, now - 600_000, "clean")
    assert ds.classify_start([stale, stopped], now - 60_000, now).kind == "stopped"


def test_redact_text_masks_token_like_values():
    text = ds.redact_text(f"bot{TOKEN} token: abc123 secret=xyz Authorization: Bearer q path /repo/user_data/x.log")
    assert TOKEN not in text and "abc123" not in text and "xyz" not in text
    assert "/repo/user_data/x.log" in text
