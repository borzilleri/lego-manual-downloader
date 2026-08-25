import json
from pathlib import Path

import pytest

from lego_manual_downloader.cli import (
    build_arg_parser,
    main,
    process_owned_sets,
    validate_output_dir,
)
from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.db import ManualDb
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.provider_factory import ProviderFactory
from lego_manual_downloader.providers import ManualProvider, OwnedSetsProvider

SETS = [
    LegoSet("10179", "Millennium Falcon", "2007"),
    LegoSet("6080", "King's Castle", "1984"),
    LegoSet("9999", "Unavailable", "2020"),
]


class StubProvider(OwnedSetsProvider, ManualProvider):
    """Serves every set except 9999, which no provider can supply."""

    def __init__(self, sets: list[LegoSet] | None = None) -> None:
        self.sets = SETS if sets is None else sets

    def get_owned_sets(self) -> list[LegoSet]:
        return self.sets

    def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool:
        if lego_set.number == "9999":
            return False
        output_path.write_bytes(b"%PDF-1.4 stub")
        return True


@pytest.fixture
def stub_factory() -> ProviderFactory:
    stub = StubProvider()
    return ProviderFactory([stub], [stub])


class TestArgParser:
    def test_download_dir_is_a_path(self) -> None:
        args = build_arg_parser().parse_args(["/some/dir"])
        assert args.download_dir == Path("/some/dir")
        assert args.config is None

    def test_config_flag_is_a_path(self) -> None:
        args = build_arg_parser().parse_args(["/some/dir", "--config", "/etc/lmd.toml"])
        assert args.config == Path("/etc/lmd.toml")

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
        target.write_text("")
        assert not validate_output_dir(target)
        assert "not a directory" in capsys.readouterr().out

    def test_rejects_an_unwritable_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "readonly"
        target.mkdir(mode=0o500)
        try:
            assert not validate_output_dir(target)
            assert "not writable" in capsys.readouterr().out
        finally:
            target.chmod(0o700)


class TestProcessOwnedSets:
    def test_downloads_and_records_each_set(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        db = ManualDb.load(tmp_path, DbConfig())
        process_owned_sets(SETS, tmp_path, db, stub_factory)

        assert (tmp_path / "10179 Millennium Falcon (2007).pdf").exists()
        assert sorted(db.db) == ["10179", "6080"]

    def test_failed_download_is_not_recorded(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        db = ManualDb.load(tmp_path, DbConfig())
        process_owned_sets(SETS, tmp_path, db, stub_factory)
        assert "9999" not in db.db

    def test_failed_download_is_reported(
        self, tmp_path: Path, stub_factory: ProviderFactory, capsys: pytest.CaptureFixture[str]
    ) -> None:
        process_owned_sets(SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory)
        assert "Unable to download manual for 9999" in capsys.readouterr().out

    def test_already_recorded_sets_are_skipped(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        db = ManualDb.load(tmp_path, DbConfig())
        db.add_manual(SETS[0])
        db.write_db()

        second = ManualDb.load(tmp_path, DbConfig())
        process_owned_sets(SETS, tmp_path, second, stub_factory)
        assert not (tmp_path / "10179 Millennium Falcon (2007).pdf").exists()
        assert (tmp_path / "6080 King's Castle (1984).pdf").exists()

    def test_writes_the_database(self, tmp_path: Path, stub_factory: ProviderFactory) -> None:
        process_owned_sets(SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory)
        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert sorted(written) == ["10179", "6080"]

    def test_empty_set_list_reports_and_writes_nothing(
        self, tmp_path: Path, stub_factory: ProviderFactory, capsys: pytest.CaptureFixture[str]
    ) -> None:
        process_owned_sets([], tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory)
        assert "No owned sets found." in capsys.readouterr().out
        assert not (tmp_path / "_lmd_db.json").exists()


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
        config = tmp_path / "config.toml"
        config.write_text('[providers]\nowned-sets-providers = ["brickset"]\n')
        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert "Error:" in capsys.readouterr().out

    def test_unknown_config_key_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tmp_path / "config.toml"
        config.write_text('[bogus]\nfoo = "bar"\n')
        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert "unknown config key" in capsys.readouterr().out

    def test_successful_run_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_factory: ProviderFactory
    ) -> None:
        monkeypatch.setattr(ProviderFactory, "create", staticmethod(lambda config: stub_factory))
        config = tmp_path / "config.toml"
        config.write_text('[brickset]\nusername = "u"\npassword = "p"\n')

        assert main([str(tmp_path), "--config", str(config)]) == 0
        assert (tmp_path / "_lmd_db.json").exists()

    def test_unreadable_database_exits_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stub_factory: ProviderFactory,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(ProviderFactory, "create", staticmethod(lambda config: stub_factory))
        (tmp_path / "_lmd_db.json").write_text("{ not json")
        config = tmp_path / "config.toml"
        config.write_text('[brickset]\nusername = "u"\npassword = "p"\n')

        assert main([str(tmp_path), "--config", str(config)]) == 1
        assert "Error loading database" in capsys.readouterr().out
