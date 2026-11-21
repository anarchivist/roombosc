import logging

import pytest

from roombosc.config import Config
from roombosc.logging_config import configure_logging


@pytest.fixture
def isolated_logging(monkeypatch):
    root = logging.RootLogger(logging.WARNING)
    monkeypatch.setattr(logging, "root", root)
    yield root
    for handler in root.handlers:
        handler.close()


def test_default_stderr_only(tmp_path, monkeypatch, capsys, isolated_logging):
    monkeypatch.chdir(tmp_path)
    configure_logging(Config("127.0.0.1", "fake", "fake"))
    logging.info("stderr only")
    assert "stderr only" in capsys.readouterr().err
    assert not (tmp_path / "log").exists()


def test_file_and_stderr_append(tmp_path, capsys, isolated_logging):
    path = tmp_path / "nested" / "run.log"
    config = Config(
        "127.0.0.1",
        "fake",
        "fake",
        log_to_file=True,
        log_file=str(path),
        log_level="DEBUG",
    )
    configure_logging(config)
    logging.debug("first event é")
    configure_logging(config)
    logging.info("second event")
    text = path.read_text(encoding="utf-8")
    assert text.count("first event é") == 1
    assert text.count("second event") == 1
    assert "DEBUG:root:first event é" in text
    assert "second event" in capsys.readouterr().err


def test_unwritable_parent(tmp_path, isolated_logging):
    parent = tmp_path / "file"
    parent.write_text("existing")
    config = Config(
        "127.0.0.1", "fake", "fake", log_to_file=True, log_file=str(parent / "run.log")
    )
    with pytest.raises(OSError):
        configure_logging(config)
