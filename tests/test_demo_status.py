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


def mark(env_paths, action, clock):
    return ds.take_mark(action, env_paths["uptime_path"], clock.now_ms())


def test_start_success_after_waiting_for_sessions(env_paths):
    m = mark(env_paths, "start", FakeClock())

    def hook(clock, n):
        if n == 2:  # 2. bekleyişte ikisi de açılır
            ft, rec = stores(env_paths["uptime_path"])
            ft.start_session(at_ms=clock.now_ms())
            rec.start_session(at_ms=clock.now_ms())

    clock = HookClock(hook)
    code = ds.run_start(m, clock=clock, env=ENV, **env_paths)
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
    m = mark(env_paths, "start", clock)
    _, rec = stores(env_paths["uptime_path"])
    rec.start_session(at_ms=since + 5 * SEC)
    logs = env_paths["logs_dir"]
    logs.mkdir(parents=True)
    lines = [f"satir {i}" for i in range(1, 51)]
    lines[45] = f"telegram https://api.telegram.org/bot{TOKEN}/getMe hata"
    lines[46] = '"password": "gizli-sifre-123", api_key=ABCDEF123456'
    lines[47] = "jwt " + "Zx9" * 20
    (logs / "freqtrade.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    code = ds.run_start(m, clock=clock, env=ENV, timeout_s=60, **env_paths)
    text = summary(env_paths, "demo_start")
    assert code == 1 and "SONUÇ: HATA" in text
    assert "[HATA   ] Durum         freqtrade" in text and "yeni oturum açılmadı" in text
    assert "[OK     ] Durum         recorder" in text
    assert "Son 30 log satırı – freqtrade.log" in text
    assert "satir 50" in text and "satir 21\n" in text and "satir 20\n" not in text  # sadece son 30
    for secret in (TOKEN, "gizli-sifre-123", "ABCDEF123456", "Zx9" * 20):
        assert secret not in text
    assert "***" in text
    assert "Açıklama – bot (Freqtrade)" in text and "WEEX'e ulaşılamıyor" in text
    assert clock.now_ms() - since >= 60 * SEC  # süre dolana kadar bekledi


def test_start_rejects_old_session_that_was_not_restarted(env_paths):
    # "docker compose up" eski container'ı yeniden başlatmadıysa (eski kod/ayar, Telegram /stop
    # sıfırlanmadı) taze kalp atışı olsa bile BAŞARILI sayılmaz: işaretten sonra yeni oturum şart.
    clock = FakeClock()
    now = clock.now_ms()
    ft, rec = stores(env_paths["uptime_path"])
    old = ft.start_session(at_ms=now - 3_600 * SEC)
    m = mark(env_paths, "start", clock)
    ft.heartbeat(old, at_ms=now + 10 * SEC)
    rec.start_session(at_ms=now + 2 * SEC)
    clock.t += 10 * SEC
    code = ds.run_start(m, clock=clock, env={}, timeout_s=20, settle_s=0, **env_paths)
    text = summary(env_paths, "demo_start")
    assert code == 1 and "SONUÇ: HATA" in text
    assert "[HATA   ] Durum         freqtrade" in text and "hâlâ çalışıyor, yeniden başlatılmadı" in text
    assert "11_demo_stop.bat, sonra 10_demo_start.bat" in text
    assert "[OK     ] Durum         recorder" in text
    assert "[UYARI  ] Genel         telegram" in text  # .env'de Telegram boş


@pytest.mark.parametrize("vm_lag_s", [-600, 0, 150, 3_600])
def test_start_and_stop_ignore_windows_vs_docker_clock_offset(env_paths, vm_lag_s):
    # WSL2/Docker saati Windows'tan geri kalsa da (uykudan sonra) karar oturum kimliğine dayanır;
    # hiçbir Windows saati kullanılmaz. Container saatleri kendi aralarında tutarlı.
    vm = FakeClock(FakeClock().now_ms() - vm_lag_s * SEC)
    ft, rec = stores(env_paths["uptime_path"])
    a, b = ft.start_session(at_ms=vm.now_ms() - 7_200 * SEC), rec.start_session(at_ms=vm.now_ms() - 7_200 * SEC)
    ft.heartbeat(a, at_ms=vm.now_ms() - 20 * SEC)
    rec.heartbeat(b, at_ms=vm.now_ms() - 20 * SEC)
    m = mark(env_paths, "start", vm)
    vm.t += 20 * SEC  # bot yeniden başlatıldı
    ft.stop_session(a, at_ms=vm.now_ms())
    rec.stop_session(b, at_ms=vm.now_ms())
    ft.start_session(at_ms=vm.now_ms() + SEC)
    rec.start_session(at_ms=vm.now_ms() + SEC)
    assert ds.run_start(m, clock=vm, env=ENV, settle_s=0, **env_paths) == 0
    assert summary(env_paths, "demo_start").count("yeni oturum") == 2

    m = mark(env_paths, "stop", vm)
    vm.t += 30 * SEC
    for store in (ft, rec):
        store.stop_session(store.sessions()[-1].id, at_ms=vm.now_ms())
    assert ds.run_stop(m, clock=vm, env=ENV, **env_paths) == 0
    text = summary(env_paths, "demo_stop")
    assert text.count("temiz kapandı") == 2 and "zaten durmuştu" not in text


def test_start_without_mark_fails_clearly(env_paths):
    code = ds.run_start(None, mark_problem="işaret dosyası yok", clock=FakeClock(), env=ENV, **env_paths)
    text = summary(env_paths, "demo_start")
    assert code == 1 and "başlatma öncesi durum kaydı kullanılamadı (işaret dosyası yok)" in text


def test_start_detects_crash_during_settle(env_paths):
    since = FakeClock().now_ms()
    m = mark(env_paths, "start", FakeClock())
    ft, rec = stores(env_paths["uptime_path"])
    sid = ft.start_session(at_ms=since + SEC)
    rec.start_session(at_ms=since + SEC)

    def hook(clock, n):
        ft.stop_session(sid, kind="clean", at_ms=clock.now_ms())

    code = ds.run_start(m, clock=HookClock(hook), env=ENV, **env_paths)
    text = summary(env_paths, "demo_start")
    assert code == 1 and "açıldı ama hemen kapandı" in text


def test_stop_clean_and_unclean(env_paths):
    clock = FakeClock()
    since = clock.now_ms()
    ft, rec = stores(env_paths["uptime_path"])
    a = ft.start_session(at_ms=since - 7_200 * SEC)
    b = rec.start_session(at_ms=since - 7_200 * SEC)
    ft.heartbeat(a, at_ms=since - 10 * SEC)
    rec.heartbeat(b, at_ms=since - 10 * SEC)
    m = mark(env_paths, "stop", clock)
    ft.stop_session(a, at_ms=since + 20 * SEC)
    rec.stop_session(b, at_ms=since + 5 * SEC)
    assert ds.run_stop(m, clock=clock, env=ENV, **env_paths) == 0
    text = summary(env_paths, "demo_stop")
    assert "SONUÇ: BAŞARILI" in text and text.count("temiz kapandı") == 2 and "2.0 saat" in text

    for p in env_paths["reports_dir"].glob("demo_stop_*.txt"):
        p.unlink()
    # ikinci durdurma: bot zaten durmuştu; kaydedici kapanış kaydı yazmadan öldü
    rec.start_session(at_ms=since + 60 * SEC)
    clock2 = FakeClock(since + 100 * SEC)
    m = mark(env_paths, "stop", clock2)
    clock2.t += 20 * SEC
    assert ds.run_stop(m, clock=clock2, env=ENV, timeout_s=10, **env_paths) == 1
    text = summary(env_paths, "demo_stop")
    assert "zaten durmuştu" in text and "[UYARI  ] Durum         freqtrade" in text
    assert "kapanış kaydı yok" in text and "Son log satırları – recorder.log" in text
    assert "dosya yok" in text


def test_stop_of_already_dead_session_and_without_mark(env_paths):
    clock = FakeClock()
    now = clock.now_ms()
    ft, rec = stores(env_paths["uptime_path"])
    a = ft.start_session(at_ms=now - 7_200 * SEC)
    ft.heartbeat(a, at_ms=now - 3_600 * SEC)  # bir saat önce elektrik kesildi
    b = rec.start_session(at_ms=now - 7_200 * SEC)
    m = mark(env_paths, "stop", clock)
    rec.stop_session(b, at_ms=now + SEC, kind="crash:RuntimeError")
    assert ds.run_stop(m, clock=clock, env=ENV, **env_paths) == 0
    text = summary(env_paths, "demo_stop")
    assert "durdurmadan önce zaten çalışmıyordu" in text and "kapanış türü 'crash:RuntimeError'" in text
    for p in env_paths["reports_dir"].glob("demo_stop_*.txt"):
        p.unlink()
    assert ds.run_stop(None, mark_problem="işaret dosyası yok", clock=clock, env=ENV, timeout_s=0,
                       **env_paths) == 1
    text = summary(env_paths, "demo_stop")
    assert "durdurma öncesi durum kaydı yok (işaret dosyası yok)" in text and "kapanış kaydı yok" in text


def test_stop_without_database_is_a_warning(env_paths):
    assert ds.run_stop(None, clock=FakeClock(), env={}, **env_paths) == 0
    assert "demo test hiç başlatılmamış" in summary(env_paths, "demo_stop")


def test_mark_file_roundtrip_and_rejections(tmp_path):
    clock = FakeClock()
    db = tmp_path / "uptime.sqlite"
    ft, _ = stores(db)
    sid = ft.start_session(at_ms=clock.now_ms())
    path = tmp_path / ds.MARK_FILE
    assert ds.run_mark("start", clock=clock, uptime_path=db, path=path) == 0
    m, problem = ds.read_mark(path, "start", clock.now_ms() + 60 * SEC)
    assert problem == "" and m.max_id == sid and m.last["freqtrade"] == {"id": sid, "stopped": False, "fresh": True}
    assert "recorder" not in m.last
    assert not path.exists()  # okununca silinir, ikinci kez kullanılmaz
    assert ds.read_mark(path, "start", clock.now_ms())[1] == "işaret dosyası yok"
    ds.run_mark("stop", clock=clock, uptime_path=db, path=path)
    assert "'stop' komutuna ait" in ds.read_mark(path, "start", clock.now_ms())[1]
    ds.run_mark("start", clock=clock, uptime_path=db, path=path)
    assert "eski" in ds.read_mark(path, "start", clock.now_ms() + ds.MARK_MAX_AGE_MS + SEC)[1]
    path.write_text("{bozuk", encoding="utf-8")
    assert "okunamadı" in ds.read_mark(path, "start", clock.now_ms())[1]
    # veritabanı yoksa (ilk çalıştırma) kimlik 0
    assert ds.take_mark("start", tmp_path / "yok.sqlite", clock.now_ms()).max_id == 0


def test_main_uses_paths_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CYBERBOT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CYBERBOT_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("CYBERBOT_REPO_DIR", str(tmp_path))
    monkeypatch.setattr(ds.Clock, "sleep", lambda self, seconds: None)
    assert ds.main(["mark", "start"]) == 0
    assert (tmp_path / "data" / ds.MARK_FILE).exists()
    assert ds.main(["start", "--timeout", "0.001"]) == 1  # oturum yok
    assert not (tmp_path / "data" / ds.MARK_FILE).exists()
    assert ds.main(["mark", "stop"]) == 0
    assert ds.main(["stop"]) == 0
    assert list((tmp_path / "reports").glob("demo_stop_*.txt"))
    with pytest.raises(SystemExit):
        ds.main(["mark"])


def test_bat_files_use_marks_not_windows_clock():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    start = (root / "10_demo_start.bat").read_text(encoding="ascii")
    stop = (root / "11_demo_stop.bat").read_text(encoding="ascii")
    for text in (start, stop):
        assert "powershell" not in text.lower() and "--since" not in text
        assert "conntest" not in text  # WEEX anahtarlı servis sadece bağlantı testinde
    assert start.index("demo_status mark start") < start.index("docker compose up") < \
        start.index("demo_status start")
    assert "up -d --build --force-recreate freqtrade recorder" in start
    assert stop.index("demo_status mark stop") < stop.index("docker compose stop") < stop.index("demo_status stop\n")


def test_classify_start_states():
    from cyberbot.uptime import Session

    now = 10_000_000
    assert ds.classify_start([], 0, now).kind == "none"
    old = Session(1, "freqtrade", now - 900_000, now - 10_000, None, None)
    assert ds.classify_start([old], 1, now).kind == "running"  # taze ama işaretten önce
    assert ds.classify_start([old], 1, now).status == ds.FAIL
    assert ds.classify_start([old], 0, now).kind == "new"
    stale = Session(2, "freqtrade", now - 900_000, now - 600_000, None, None)
    assert ds.classify_start([stale], 1, now).kind == "stale"
    stopped = Session(3, "freqtrade", now - 900_000, now - 600_000, now - 600_000, "clean")
    assert ds.classify_start([stale, stopped], 1, now).kind == "stopped"
    assert ds.classify_start([stale, stopped], 3, now).kind == "none"


def test_redact_text_masks_token_like_values():
    text = ds.redact_text(f"bot{TOKEN} token: abc123 secret=xyz Authorization: Bearer q path /repo/user_data/x.log")
    assert TOKEN not in text and "abc123" not in text and "xyz" not in text
    assert "/repo/user_data/x.log" in text
