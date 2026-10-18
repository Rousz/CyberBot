"""python -m cyberbot.recorder: log dosyası yeri ve gizli bilgi maskeleme."""

import logging

from cyberbot.recorder import __main__ as entry
from cyberbot.recorder.defaults import RECORDER_DEFAULTS


def test_logging_writes_rotating_file_and_masks_token(tmp_path, monkeypatch):
    monkeypatch.setenv("CYBERBOT_REPO_DIR", str(tmp_path))
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        entry.setup_logging(RECORDER_DEFAULTS, ["123456:SECRET-token"])
        logging.getLogger("cyberbot.recorder.test").warning("hata: https://api.telegram.org/bot123456:SECRET-token/x")
        for h in root.handlers:
            h.flush()
        text = (tmp_path / "user_data" / "logs" / "recorder.log").read_text(encoding="utf-8")
        assert "SECRET" not in text and "bot***" in text
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()
