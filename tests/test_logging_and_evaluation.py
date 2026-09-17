import os
import logging
import pytest
from job_agent import setup_logging, ConsoleFilter, _OUTPUT_DIR


def test_console_filter():
    f = ConsoleFilter()
    # Noisy loggers should be rejected
    for noisy in ["selenium.webdriver", "seleniumbase.core", "urllib3.connectionpool", "playwright._impl"]:
        record = logging.LogRecord(
            name=noisy,
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="test",
            args=(),
            exc_info=None
        )
        assert f.filter(record) is False

    # Standard app loggers should be accepted
    for app in ["root", "job_agent", "core.job_utils", "scrapers.tanqeeb"]:
        record = logging.LogRecord(
            name=app,
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="test",
            args=(),
            exc_info=None
        )
        assert f.filter(record) is True


def test_setup_logging_new_run_clears_log(tmp_path, monkeypatch):
    log_file = tmp_path / "job_agent.log"
    log_file.write_text("Old log entry from previous run\n", encoding="utf-8")
    assert "Old log entry" in log_file.read_text(encoding="utf-8")

    monkeypatch.setattr("job_agent._OUTPUT_DIR", str(tmp_path))

    setup_logging(is_resumed=False)
    logging.info("Fresh log message from new run")

    for h in logging.getLogger().handlers:
        h.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "Old log entry" not in content
    assert "Fresh log message from new run" in content


def test_setup_logging_resumed_run_appends_log(tmp_path, monkeypatch):
    log_file = tmp_path / "job_agent.log"
    log_file.write_text("Prior session log entry\n", encoding="utf-8")

    monkeypatch.setattr("job_agent._OUTPUT_DIR", str(tmp_path))

    setup_logging(is_resumed=True)
    logging.info("Resumed session log message")

    for h in logging.getLogger().handlers:
        h.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "Prior session log entry" in content
    assert "Resumed session log message" in content


def test_non_root_logger_writes_to_file(tmp_path, monkeypatch):
    monkeypatch.setattr("job_agent._OUTPUT_DIR", str(tmp_path))
    setup_logging(is_resumed=False)

    scraper_logger = logging.getLogger("scrapers.bayt")
    scraper_logger.info("Found 5 jobs on Bayt")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = tmp_path / "job_agent.log"
    content = log_file.read_text(encoding="utf-8")
    assert "scrapers.bayt" in content
    assert "Found 5 jobs on Bayt" in content
