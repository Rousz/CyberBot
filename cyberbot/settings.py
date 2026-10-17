"""CyberBot ayarları: tek config dosyası (user_data/config.json) içindeki "cyberbot" bölümü.

Her modül kendi varsayılanlarını tutar ve section("ad", VARSAYILANLAR) ile
config'deki değerlerle birleştirir. Config'de olmayan anahtar varsayılandan gelir.
Örnek:  {"cyberbot": {"strategy": {...}, "recorder": {...}, "monitor": {...}}}
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from cyberbot import paths


def deep_merge(defaults: dict, overrides: dict | None) -> dict:
    """Varsayılanların kopyası üzerine overrides'ı (iç içe) yazar; girdileri değiştirmez."""
    result = copy.deepcopy(defaults)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: str | Path | None = None) -> dict:
    """Freqtrade config dosyasını okur (yoksa boş dict)."""
    path = Path(path) if path else paths.config_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def section(name: str, defaults: dict, config: dict | None = None) -> dict[str, Any]:
    """config["cyberbot"][name] ile varsayılanları birleştirir. config verilmezse dosyadan okunur."""
    config = load_config() if config is None else config
    return deep_merge(defaults, (config.get("cyberbot") or {}).get(name))
