from pathlib import Path

import pytest

from conftest import SETS, ManualOnlyWriter, SetsOnlyProvider, StubProvider
from lego_manual_downloader import cli
from lego_manual_downloader.cli import build_arg_parser, main, validate_output_dir
from lego_manual_downloader.lego import LegoSet
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

    def test_rejects_a_missing_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert not validate_output_dir(tmp_path / "absent")
        assert "does not exist" in capsys.readouterr().out

    def test_rejects_a_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        target = tmp_path / "a-file"
        target.write_text("hi")
        assert not validate_output_dir(target)
        assert "not a directory" in capsys.readouterr().out

    def test_rejects_an_unwritable_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "locked"
        target.mkdir()
        target.chmod(0o500)
        try:
            assert not validate_output_dir(target)
            assert "not writable" in capsys.readouterr().out
        finally:
            target.chmod(0o700)


class TestMain:
    def test_bad_output_dir_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([str(tmp_path / "absent")]) == 1
        assert "does not exist" in capsys.readouterr().out

    def test_missing_named_config_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main([str(tmp_path), "--config", str(tmp_path / "absent.toml")]) == 1
        assert "config file not found" in capsys.readouterr().out

    def test_unusable_provider_config_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No credentials anywhere, so no provider can be built."""
        config = _config_file(tmp_path, '[providers]\nowned-sets-providers = ["brickset"]\n')
        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert "no usable providers" in capsys.readouterr().out

    def test_unknown_config_key_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = _config_file(tmp_path, '[bogus]\nfoo = "bar"\n')
        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert "unknown config key" in capsys.readouterr().out

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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Chains are built from config names, so an unbuilt name leaves them empty."""
        _use_stub_providers(monkeypatch, SETS[:2])
        config = _config_file(tmp_path, BRICKSET_CONFIG)

        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert "No usable owned sets providers, stopping." in capsys.readouterr().out

    def test_unreadable_database_exits_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Seeded with sets that all succeed, so only the bad database can fail the run."""
        _use_stub_providers(monkeypatch, SETS[:2])
        (tmp_path / "_lmd_db.json").write_text("{ not json")
        config = _config_file(tmp_path)

        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert "Expecting property name" in capsys.readouterr().out
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
