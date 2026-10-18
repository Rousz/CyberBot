"""python -m cyberbot.recorder: kaydedici + izleme servisini başlatır.

Log: ekrana (docker logs) ve /repo/user_data/logs/recorder.log (dönen dosya).
SIGTERM/SIGINT (docker stop, Ctrl+C) gelince düzgün kapanır.
Gizli bilgiler (Telegram token) hiçbir log satırına yazılmaz.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import signal
import sys
import time

from cyberbot import paths, settings
from cyberbot.notify import TelegramNotifier
from cyberbot.recorder.defaults import MONITOR_DEFAULTS, RECORDER_DEFAULTS


class _RedactFilter(logging.Filter):
    """Token bir hata metnine (ör. URL) karışırsa maskeler."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 6]

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            text = record.getMessage()
            for secret in self.secrets:
                text = text.replace(secret, "***")
            record.msg, record.args = text, ()
        return True


def setup_logging(cfg: dict, secrets: list[str]) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    fmt.converter = time.gmtime  # UTC
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    redact = _RedactFilter(secrets)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_dir = paths.repo_dir() / "user_data" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            log_dir / "recorder.log", maxBytes=int(cfg["log_max_mb"]) * 1024 * 1024,
            backupCount=int(cfg["log_backups"]), encoding="utf-8"))
    except OSError as exc:
        print(f"[recorder] log dosyası açılamadı: {exc}", flush=True)
    for handler in handlers:
        handler.setFormatter(fmt)
        handler.addFilter(redact)
        root.addHandler(handler)
    for noisy in ("aiohttp", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def amain() -> None:
    from cyberbot.recorder.service import Recorder

    config = settings.load_config()
    cfg = settings.section("recorder", RECORDER_DEFAULTS, config)
    mon_cfg = settings.section("monitor", MONITOR_DEFAULTS, config)
    token, chat_id = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    setup_logging(cfg, [token or ""])
    notifier = TelegramNotifier(token, chat_id)
    if not notifier.enabled:
        logging.getLogger(__name__).warning("Telegram kapalı (.env'de TELEGRAM_TOKEN/TELEGRAM_CHAT_ID boş); "
                                            "uyarılar sadece loga yazılır")
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    recorder = Recorder(cfg, mon_cfg, notifier=notifier)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, recorder.request_stop)
        except (NotImplementedError, RuntimeError):  # Windows'ta doğrudan çalıştırma
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(recorder.request_stop))
    await recorder.run()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
