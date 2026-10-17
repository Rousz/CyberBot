"""Repo düzeni kontrolleri: Windows .bat dosyaları, gizli bilgiler, satır sonları, ağ engeli."""

from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
BAT_FILES = sorted(ROOT.glob("*.bat")) + sorted((ROOT / "setup").glob("*.bat"))


def test_bat_files_exist():
    names = {p.name for p in BAT_FILES}
    assert {"00_quick_check.bat", "01_connection_test.bat", "setup_env.bat", "setup_wslconfig.bat"} <= names


def test_bat_files_are_ascii_and_quiet():
    # Türkçe karakterler cmd.exe'de bozulabildiği için .bat dosyaları ASCII tutulur;
    # Türkçe metni Python (Docker içinde) basar.
    for path in BAT_FILES:
        data = path.read_bytes()
        assert data.isascii(), f"{path.name} ASCII dışı karakter içeriyor"
        assert data.replace(b"\r\n", b"\n").startswith(b"@echo off\n"), f"{path.name} '@echo off' ile başlamalı"


def test_top_level_bat_files_switch_console_to_utf8():
    for path in ROOT.glob("*.bat"):
        assert "chcp 65001" in path.read_text(encoding="ascii"), path.name


def test_gitattributes_forces_crlf_for_bat_and_lf_for_python():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.bat text eol=crlf" in text
    assert "*.py text eol=lf" in text


def test_env_example_has_no_values():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            assert key.isupper() and value == "", f".env.example içinde değer var: {key}"


def test_gitignore_blocks_secrets_data_and_logs():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for required in (".env", "!.env.example", "reports/logs/", "*.log", "*.sqlite", "user_data/data/"):
        assert required in lines, required
    assert lines.index("!.env.example") > lines.index(".env.*")


def test_network_is_blocked_in_tests(monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(Exception, match="yasak"):
        requests.get("https://api-contract.weex.com/capi/v3/market/time", timeout=2)


def test_image_pins_freqtrade_and_ccxt_and_registers_weex():
    text = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM freqtradeorg/freqtrade:2026.9" in text
    assert '"ccxt==4.5.88"' in text
    assert "from freqtrade.exchange.weex import Weex" in text
    assert "latest" not in text


def test_docker_build_context_contains_only_weex_module():
    lines = [ln.strip() for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    assert lines == ["*", "!freqtrade_ext/weex.py"]


def test_compose_reads_secrets_from_env_and_keeps_keys_out_of_freqtrade():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "TELEGRAM_TOKEN: ${TELEGRAM_TOKEN:-}" in text
    freqtrade_block = text.split("  freqtrade:", 1)[1].split("\n  recorder:", 1)[0]
    assert "WEEX_API" not in freqtrade_block and "--dry-run" in freqtrade_block
    assert "stop_grace_period: 60s" in freqtrade_block
    assert "cyberbot_data:/data" in text
