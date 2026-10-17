from datetime import datetime, timezone

import pytest

from cyberbot import timeutil
from cyberbot.report import (
    FAIL,
    INFO,
    OK,
    SKIP,
    VERDICT_FAIL,
    VERDICT_OK,
    VERDICT_WARN,
    WARN,
    Outcome,
    Report,
    UserFacingError,
    describe_error,
)


@pytest.fixture
def rep(tmp_path):
    report = Report("Deneme", "demo", tmp_path)
    yield report
    report.close()


def test_verdict_follows_worst_status(rep):
    rep.add("G", "a", OK, "tamam")
    rep.add("G", "b", SKIP, "atlandı")
    rep.add("G", "c", INFO, "bilgi")
    assert rep.verdict() == VERDICT_OK and rep.exit_code() == 0
    rep.add("G", "d", WARN, "uyarı")
    assert rep.verdict() == VERDICT_WARN and rep.exit_code() == 0
    rep.add("G", "e", FAIL, "hata")
    assert rep.verdict() == VERDICT_FAIL and rep.exit_code() == 1


def test_run_maps_results_and_exceptions(rep):
    assert rep.run("G", "str", lambda: "iyi").status == OK
    assert rep.run("G", "outcome", lambda: Outcome(WARN, "dikkat")).status == WARN

    def boom():
        raise ValueError("bozuk cevap")

    assert rep.run("G", "kritik", boom).status == FAIL
    soft = rep.run("G", "kritik_degil", boom, critical=False)
    assert soft.status == WARN and soft.detail == "ValueError: bozuk cevap"
    assert soft.ms is not None


def test_secrets_are_masked_everywhere(tmp_path, capsys):
    rep = Report("Deneme", "demo", tmp_path)
    rep.add_secret("SuperGizliToken123")
    rep.add_secret("ab")  # çok kısa değerler maskelenmez (yanlış eşleşme olmasın)
    rep.add("G", "x", FAIL, "https://api.telegram.org/botSuperGizliToken123/getMe bağlanamadı")
    rep.finding("bulgu", "SuperGizliToken123 içeren değer")
    rep.log.info("log satırı SuperGizliToken123")
    rep.finish()
    out = capsys.readouterr().out
    summary = rep.summary_path.read_text(encoding="utf-8")
    log = rep.log_path.read_text(encoding="utf-8")
    for text in (out, summary, log):
        assert "SuperGizliToken123" not in text
    assert "bot***/getMe" in summary


def test_screen_only_text_never_reaches_files(rep, capsys):
    rep.screen_only("GIZLI-CHAT-42")
    rep.add("G", "x", OK, "tamam")
    rep.save()
    assert "GIZLI-CHAT-42" in capsys.readouterr().out
    assert "GIZLI-CHAT-42" not in rep.summary_path.read_text(encoding="utf-8")
    assert "GIZLI-CHAT-42" not in rep.log_path.read_text(encoding="utf-8")


def test_render_and_finish(tmp_path, capsys):
    rep = Report("Bağlantı testi", "demo", tmp_path)
    rep.add("WEEX", "rest", OK, "çalışıyor", 12.3)
    rep.add("Binance", "ws", FAIL, "bağlanamadı")
    rep.finding("Saat farkı", "+12 ms")
    code = rep.finish()
    out = capsys.readouterr().out
    text = rep.summary_path.read_text(encoding="utf-8")
    assert code == 1
    assert "SONUÇ: HATA" in out and "SONUÇ: HATA" in text
    assert "[WEEX]" in text and "[Binance]" in text and "(12 ms)" in text
    assert "Önemli bulgular:" in text and "Saat farkı: +12 ms" in text
    assert rep.summary_path.name.startswith("demo_") and rep.summary_path.suffix == ".txt"
    assert rep.log_path.parent.name == "logs"
    assert "\r\n" not in rep.summary_path.read_bytes().decode("utf-8")


def test_describe_error():
    assert describe_error(UserFacingError("HTTP 451 – engel")) == "HTTP 451 – engel"
    assert describe_error(KeyError("x")) == "KeyError: 'x'"
    assert describe_error(TimeoutError()) == "TimeoutError"
    assert len(describe_error(ValueError("a" * 500))) == 300


# --- timeutil -------------------------------------------------------------


def test_fmt_both_shows_istanbul_time():
    dt = datetime(2026, 10, 17, 18, 30, 5, tzinfo=timezone.utc)
    assert timeutil.fmt_both(dt) == "2026-10-17 18:30:05 UTC (İstanbul 21:30:05)"


def test_fmt_both_shows_istanbul_date_after_midnight():
    dt = datetime(2026, 10, 17, 22, 15, 0, tzinfo=timezone.utc)
    assert timeutil.fmt_both(dt) == "2026-10-17 22:15:00 UTC (İstanbul 2026-10-18 01:15:00)"


def test_stamps_and_ms_roundtrip():
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert timeutil.file_stamp(dt) == "20260102_030405Z"
    assert timeutil.from_ms(timeutil.to_ms(dt)) == dt
    assert timeutil.fmt_istanbul(dt) == "2026-01-02 06:04:05"
    assert timeutil.utc_now().tzinfo is not None
