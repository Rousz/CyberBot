"""Ortak dosya yolları.

Container içinde: repo /repo (bind mount), veritabanları /data (Docker volume
"cyberbot_data"; Windows klasörü üzerinden SQLite kilitlenme sorunlarını önler).
VM testlerinde ortam değişkenleriyle geçici klasörlere yönlendirilir.
Değerler her çağrıda ortamdan okunur (testler monkeypatch ile değiştirebilsin).
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_DEFAULT = Path(__file__).resolve().parent.parent


def repo_dir() -> Path:
    return Path(os.environ.get("CYBERBOT_REPO_DIR", _REPO_DEFAULT))


def data_dir() -> Path:
    return Path(os.environ.get("CYBERBOT_DATA_DIR", repo_dir() / "user_data" / "cyberbot"))


def config_path() -> Path:
    return Path(os.environ.get("CYBERBOT_CONFIG", repo_dir() / "user_data" / "config.json"))


def reports_dir() -> Path:
    return Path(os.environ.get("CYBERBOT_REPORTS_DIR", repo_dir() / "reports"))


def uptime_db() -> Path:
    return data_dir() / "uptime.sqlite"


def derivs_db() -> Path:
    return data_dir() / "derivs.sqlite"


def trades_db() -> Path:
    return data_dir() / "tradesv3.dryrun.sqlite"


def binance_perps_json() -> Path:
    """Recorder yazar, strateji okur: WEEX paritesi -> Binance vadeli karşılığı."""
    return data_dir() / "binance_perps.json"
