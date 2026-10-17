"""Freqtrade container başlatıcı.

docker-compose "freqtrade" servisi bunu çalıştırır:
    python -m cyberbot.launch trade --config ... --strategy CyberScalp ...
Yaptıkları:
- .env'de TELEGRAM_TOKEN ve TELEGRAM_CHAT_ID ikisi de doluysa Freqtrade Telegram'ını açar,
  değilse kapatır (boş token ile Freqtrade başlamaz).
- "trade" komutunda --dry-run'ı zorunlu ekler: demo test API anahtarı olmadan çalışır,
  canlı işlem bu aşamada mümkün değildir.
- Borsa anahtarlarını Freqtrade'e hiç geçirmez.
- Log ve veri klasörlerini oluşturur, sonra kendini freqtrade ile değiştirir (exec),
  böylece Docker'ın durdurma sinyali (SIGTERM) doğrudan Freqtrade'e gider.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cyberbot import paths

_SECRET_PREFIXES = ("FREQTRADE__EXCHANGE__KEY", "FREQTRADE__EXCHANGE__SECRET", "FREQTRADE__EXCHANGE__PASSWORD",
                    "FREQTRADE__EXCHANGE__UID")
_NOT_FOR_FREQTRADE = ("WEEX_API_KEY", "WEEX_API_SECRET", "WEEX_API_PASSPHRASE")


def build_env(environ: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    env = {k: v for k, v in environ.items()
           if not k.startswith(_SECRET_PREFIXES) and k not in _NOT_FOR_FREQTRADE}
    notes = []
    token = (environ.get("TELEGRAM_TOKEN") or "").strip()
    chat_id = (environ.get("TELEGRAM_CHAT_ID") or "").strip()
    env.pop("TELEGRAM_TOKEN", None)
    if token and chat_id:
        env["FREQTRADE__TELEGRAM__ENABLED"] = "true"
        env["FREQTRADE__TELEGRAM__TOKEN"] = token
        env["FREQTRADE__TELEGRAM__CHAT_ID"] = chat_id
        notes.append("Telegram açık.")
    else:
        env["FREQTRADE__TELEGRAM__ENABLED"] = "false"
        for key in ("FREQTRADE__TELEGRAM__TOKEN", "FREQTRADE__TELEGRAM__CHAT_ID"):
            env.pop(key, None)
        notes.append("UYARI: .env'de TELEGRAM_TOKEN veya TELEGRAM_CHAT_ID boş; Telegram bildirimleri kapalı.")
    return env, notes


def build_argv(argv: list[str]) -> list[str]:
    argv = list(argv)
    if argv and argv[0] == "trade" and "--dry-run" not in argv:
        argv.insert(1, "--dry-run")
    return ["freqtrade", *argv]


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    env, notes = build_env(dict(os.environ))
    for note in notes:
        print(f"[cyberbot.launch] {note}", flush=True)
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    (paths.repo_dir() / "user_data" / "logs").mkdir(parents=True, exist_ok=True)
    full = build_argv(argv)
    print(f"[cyberbot.launch] {' '.join(full)}", flush=True)
    os.execvpe(full[0], full, env)


if __name__ == "__main__":
    main()
