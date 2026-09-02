import io
import logging
from pathlib import Path

import pytest

from lego_manual_downloader import log

CHILD = f"{log.PACKAGE_LOGGER}.testing"


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger(CHILD)


class TestFormat:
    def test_info_prints_the_bare_message(
        self, logger: logging.Logger, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log.configure(color=False)
        logger.info("downloading %s", "10179-1")
        assert capsys.readouterr().out == "downloading 10179-1\n"

    def test_color_wraps_only_the_tag(
        self, logger: logging.Logger, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log.configure(color=True)
        logger.warning("careful")
        assert capsys.readouterr().err == "\033[33mWARNING \033[0mcareful\n"

    def test_color_is_omitted_when_disabled(
        self, logger: logging.Logger, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log.configure(color=False)
        logger.error("broken")
        assert "\033[" not in capsys.readouterr().err


class Tty(io.StringIO):
    """A StringIO is already an `IO[str]`; it just never claims to be a terminal."""

    def isatty(self) -> bool:
        return True


class TestUseColor:
    def test_a_tty_gets_color(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert log._use_color(Tty(), None)

    def test_a_pipe_does_not(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert not log._use_color(io.StringIO(), None)

    def test_no_color_env_wins_over_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        assert not log._use_color(Tty(), None)

    def test_an_explicit_choice_wins_over_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        assert log._use_color(io.StringIO(), True)


class TestStreams:
    def test_progress_goes_to_stdout_and_problems_to_stderr(
        self, logger: logging.Logger, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log.configure(level="debug", color=False)
        logger.debug("tracing")
        logger.info("working")
        logger.warning("careful")
        logger.error("broken")
        captured = capsys.readouterr()
        assert captured.out == "DEBUG   tracing\nworking\n"
        assert captured.err == "WARNING careful\nERROR   broken\n"


class TestLevels:
    def test_debug_is_hidden_by_default(
        self, logger: logging.Logger, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log.configure(color=False)
        logger.debug("tracing")
        logger.info("working")
        assert capsys.readouterr().out == "working\n"

    def test_error_level_hides_everything_quieter(
        self, logger: logging.Logger, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log.configure(level="error", color=False)
        logger.info("working")
        logger.warning("careful")
        logger.error("broken")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "ERROR   broken\n"

    def test_an_unknown_level_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown level"):
            log.configure(level="loud")


class TestLogFile:
    def test_records_are_written_with_a_timestamp_and_no_color(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        destination = tmp_path / "run.log"
        log.configure(log_file=destination, color=True)
        logger.info("working")
        logger.warning("careful")

        lines = destination.read_text().splitlines()
        assert len(lines) == 2
        assert lines[0].endswith("INFO     working")
        assert lines[1].endswith("WARNING  careful")
        assert "\033[" not in destination.read_text()

    def test_reconfiguring_does_not_duplicate_output(
        self, logger: logging.Logger, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log.configure(color=False)
        log.configure(color=False)
        logger.info("working")
        assert capsys.readouterr().out == "working\n"
