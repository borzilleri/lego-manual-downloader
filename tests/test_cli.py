import logging
from pathlib import Path

import pytest

from conftest import SETS, ManualOnlyWriter, SetsOnlyProvider, StubProvider, records_at
from lego_manual_downloader import cli
from lego_manual_downloader.cli import build_arg_parser, main, validate_output_dir
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.log import PACKAGE_LOGGER
from lego_manual_downloader.providers import BaseProvider

BRICKSET_CONFIG = '[brickset]\nusername = "u"\npassword = "p"\n'

STUB_CONFIG = '[providers]\nowned-sets-providers = ["stub"]\nmanual-providers = ["stub"]\n'


def _use_providers(monkeypatch: pytest.MonkeyPatch, providers: dict[str, BaseProvider]) -> None:
    """Stand fakes in for the real providers, leaving main's own wiring under test.

    `main` builds its chains from the provider names in the config, so the config
    each test writes is what makes these reachable.
    """
    monkeypatch.setattr(cli, "create_providers", lambda *_: providers)


def _use_stub_providers(monkeypatch: pytest.MonkeyPatch, sets: list[LegoSet] | None = None) -> None:
    _use_providers(monkeypatch, {"stub": StubProvider(sets)})


def _config_file(tmp_path: Path, body: str = STUB_CONFIG) -> Path:
    config = tmp_path / "config.toml"
    config.write_text(body)
    return config


class TestArgParser:
    def test_download_dir_is_a_path(self) -> None:
        args = build_arg_parser().parse_args(["/some/dir"])
        assert args.download_dir == Path("/some/dir")
        assert args.config is None

    def test_config_flag_is_a_path(self) -> None:
        args = build_arg_parser().parse_args(["/some/dir", "--config", "/etc/lmd.toml"])
        assert args.config == Path("/etc/lmd.toml")

    def test_log_level_defaults_to_unset_so_config_can_speak(self) -> None:
        assert build_arg_parser().parse_args(["/some/dir"]).log_level is None

    def test_log_level_rejects_an_unknown_name(self) -> None:
        with pytest.raises(SystemExit):
            build_arg_parser().parse_args(["/some/dir", "--log-level", "loud"])

    def test_log_file_is_a_path(self) -> None:
        args = build_arg_parser().parse_args(["/some/dir", "--log-file", "/tmp/lmd.log"])
        assert args.log_file == Path("/tmp/lmd.log")

    def test_dry_run_defaults_to_false(self) -> None:
        assert build_arg_parser().parse_args(["/some/dir"]).dry_run is False

    def test_dry_run_flag_is_a_switch(self) -> None:
        assert build_arg_parser().parse_args(["/some/dir", "--dry-run"]).dry_run is True

    def test_download_dir_is_required(self) -> None:
        with pytest.raises(SystemExit):
            build_arg_parser().parse_args([])


class TestValidateOutputDir:
    def test_accepts_a_writable_directory(self, tmp_path: Path) -> None:
        assert validate_output_dir(tmp_path)

    def test_rejects_a_missing_path(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        assert not validate_output_dir(tmp_path / "absent")
        assert records_at(caplog, logging.ERROR, "does not exist")

    def test_rejects_a_file(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        target = tmp_path / "a-file"
        target.write_text("hi")
        assert not validate_output_dir(target)
        assert records_at(caplog, logging.ERROR, "not a directory")

    def test_rejects_an_unwritable_directory(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        target = tmp_path / "locked"
        target.mkdir()
        target.chmod(0o500)
        try:
            assert not validate_output_dir(target)
            assert records_at(caplog, logging.ERROR, "not writable")
        finally:
            target.chmod(0o700)


class TestMain:
    def test_bad_output_dir_exits_one(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert main([str(tmp_path / "absent")]) == 1
        assert records_at(caplog, logging.ERROR, "does not exist")

    def test_missing_named_config_exits_one(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        assert main([str(tmp_path), "--config", str(tmp_path / "absent.toml")]) == 1
        assert records_at(caplog, logging.ERROR, "config file not found")

    def test_unusable_provider_config_exits_one(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No credentials anywhere, so no provider can be built."""
        config = _config_file(tmp_path, '[providers]\nowned-sets-providers = ["brickset"]\n')
        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert records_at(caplog, logging.ERROR, "no usable providers")

    def test_unknown_config_key_exits_one(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = _config_file(tmp_path, '[bogus]\nfoo = "bar"\n')
        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert records_at(caplog, logging.ERROR, "unknown config key")

    def test_successful_run_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_stub_providers(monkeypatch, SETS[:2])
        config = _config_file(tmp_path)

        assert main([str(tmp_path), "--config", str(config)]) == 0
        assert (tmp_path / "_lmd_db.json").exists()

    def test_a_failed_download_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_stub_providers(monkeypatch)
        config = _config_file(tmp_path)

        assert main([str(tmp_path), "--config", str(config)]) == 1

    def test_owning_no_sets_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_stub_providers(monkeypatch, [])
        config = _config_file(tmp_path)

        assert main([str(tmp_path), "--config", str(config)]) == 0

    def test_a_provider_named_in_config_but_not_built_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Chains are built from config names, so an unbuilt name leaves them empty."""
        _use_stub_providers(monkeypatch, SETS[:2])
        config = _config_file(tmp_path, BRICKSET_CONFIG)

        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert records_at(caplog, logging.ERROR, "No usable owned sets providers, stopping.")

    def test_unreadable_database_exits_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Seeded with sets that all succeed, so only the bad database can fail the run."""
        _use_stub_providers(monkeypatch, SETS[:2])
        (tmp_path / "_lmd_db.json").write_text("{ not json")
        config = _config_file(tmp_path)

        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert records_at(caplog, logging.ERROR, "Expecting property name")
        assert (tmp_path / "_lmd_db.json").read_text() == "{ not json"

    def test_each_role_list_feeds_its_own_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The two config lists are not interchangeable: each must reach its own chain.

        The providers fill one role apiece, so a swap leaves both chains empty.
        """
        _use_providers(monkeypatch, {"sets": SetsOnlyProvider(), "manual": ManualOnlyWriter()})
        config = _config_file(
            tmp_path,
            '[providers]\nowned-sets-providers = ["sets"]\nmanual-providers = ["manual"]\n',
        )

        assert main([str(tmp_path), "--config", str(config)]) == 0
        assert (tmp_path / SETS[0].file_name).exists()

    def test_dry_run_exits_zero_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_stub_providers(monkeypatch, SETS[:2])
        config = _config_file(tmp_path)

        assert main([str(tmp_path), "--config", str(config), "--dry-run"]) == 0
        assert not (tmp_path / "_lmd_db.json").exists()
        assert list(tmp_path.iterdir()) == [config]


class TestLoggingSetup:
    def test_config_supplies_the_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _use_stub_providers(monkeypatch, SETS[:1])
        config = _config_file(tmp_path, STUB_CONFIG + '[logging]\nlevel = "warning"\n')

        assert main([str(tmp_path), "--config", str(config)]) == 0
        assert logging.getLogger(PACKAGE_LOGGER).level == logging.WARNING

    def test_the_flag_beats_the_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_stub_providers(monkeypatch, SETS[:1])
        config = _config_file(tmp_path, STUB_CONFIG + '[logging]\nlevel = "warning"\n')

        assert main([str(tmp_path), "--config", str(config), "--log-level", "debug"]) == 0
        assert logging.getLogger(PACKAGE_LOGGER).level == logging.DEBUG

    def test_config_supplies_the_log_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        destination = tmp_path / "run.log"
        _use_stub_providers(monkeypatch, SETS[:1])
        config = _config_file(tmp_path, STUB_CONFIG + f'[logging]\nfile = "{destination}"\n')

        assert main([str(tmp_path), "--config", str(config)]) == 0
        assert "is missing, downloading." in destination.read_text()

    def test_a_bad_level_in_config_exits_one(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = _config_file(tmp_path, '[logging]\nlevel = "loud"\n')

        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert records_at(caplog, logging.ERROR, "[logging] unknown level 'loud'")
