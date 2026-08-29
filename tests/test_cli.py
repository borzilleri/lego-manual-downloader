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
from lego_manual_downloader.providers import (
    ManualProvider,
    OwnedSetsProvider,
    ProviderUnavailable,
)

SETS = [
    LegoSet("10179", "1", "Millennium Falcon", "2007"),
    LegoSet("6080", "1", "King's Castle", "1984"),
    LegoSet("9999", "1", "Unavailable", "2020"),
]
LEGACY_NAME = "10179 Falcon.pdf"


def _db_with_manual_under_legacy_name(tmp_path: Path) -> ManualDb:
    """SETS[0]'s manual is on disk, but under a name the set no longer derives."""
    entry = {**SETS[0].to_dict(), "file": LEGACY_NAME}
    (tmp_path / "_lmd_db.json").write_text(json.dumps({"10179-1": entry}))
    (tmp_path / LEGACY_NAME).write_bytes(b"%PDF-1.4 original")
    return ManualDb.load(tmp_path, DbConfig())


class StubProvider(OwnedSetsProvider, ManualProvider):
    """Serves every set except 9999, which no provider can supply."""

    def __init__(self, sets: list[LegoSet] | None = None) -> None:
        self.sets = SETS if sets is None else sets

    def get_owned_sets(self) -> list[LegoSet]:
        return self.sets

    def download_manual(
        self, lego_set: LegoSet, output_path: Path, *, dry_run: bool = False
    ) -> bool:
        if lego_set.number == "9999":
            return False
        if dry_run:
            return True
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

        assert (tmp_path / "10179-1 Millennium Falcon (2007).pdf").exists()
        assert sorted(db.db) == ["10179-1", "6080-1"]

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
        (tmp_path / SETS[0].file_name).write_bytes(b"%PDF-1.4 stub")

        second = ManualDb.load(tmp_path, DbConfig())
        process_owned_sets(SETS, tmp_path, second, stub_factory)
        assert (tmp_path / "10179-1 Millennium Falcon (2007).pdf").read_bytes() == b"%PDF-1.4 stub"
        assert (tmp_path / "6080-1 King's Castle (1984).pdf").exists()

    def test_recorded_set_is_downloaded_again_when_its_file_is_gone(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        """The DB records intent; the file on disk is the source of truth."""
        db = ManualDb.load(tmp_path, DbConfig())
        db.add_manual(SETS[0])
        db.write_db()

        process_owned_sets(SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory)
        assert (tmp_path / "10179-1 Millennium Falcon (2007).pdf").exists()

    def test_a_manual_already_on_disk_is_adopted_rather_than_redownloaded(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        """An empty database next to a full download directory must not refetch everything."""
        (tmp_path / SETS[0].file_name).write_bytes(b"%PDF-1.4 original")

        process_owned_sets(SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory)

        assert (tmp_path / SETS[0].file_name).read_bytes() == b"%PDF-1.4 original"
        assert "10179-1" in json.loads((tmp_path / "_lmd_db.json").read_text())

    def test_a_misnamed_manual_is_renamed_rather_than_redownloaded(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        db = _db_with_manual_under_legacy_name(tmp_path)

        process_owned_sets(SETS, tmp_path, db, stub_factory)

        assert (tmp_path / SETS[0].file_name).read_bytes() == b"%PDF-1.4 original"
        assert not (tmp_path / LEGACY_NAME).exists()

        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert written["10179-1"]["file"] == SETS[0].file_name

    def test_writes_the_database(self, tmp_path: Path, stub_factory: ProviderFactory) -> None:
        process_owned_sets(SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory)
        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert sorted(written) == ["10179-1", "6080-1"]

    def test_empty_set_list_reports_and_writes_nothing(
        self, tmp_path: Path, stub_factory: ProviderFactory, capsys: pytest.CaptureFixture[str]
    ) -> None:
        process_owned_sets([], tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory)
        assert "No owned sets found." in capsys.readouterr().out
        assert not (tmp_path / "_lmd_db.json").exists()


class TestDryRun:
    def test_nothing_is_written_to_disk(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        db = ManualDb.load(tmp_path, DbConfig())
        process_owned_sets(SETS, tmp_path, db, stub_factory, dry_run=True)

        assert list(tmp_path.iterdir()) == []
        assert db.db == {}

    def test_the_database_file_is_not_created(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        process_owned_sets(
            SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory, dry_run=True
        )
        assert not (tmp_path / "_lmd_db.json").exists()

    def test_an_existing_database_is_left_untouched(
        self, tmp_path: Path, stub_factory: ProviderFactory
    ) -> None:
        first = ManualDb.load(tmp_path, DbConfig())
        first.add_manual(SETS[0])
        first.write_db()
        before = (tmp_path / "_lmd_db.json").read_text()

        process_owned_sets(
            SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory, dry_run=True
        )
        assert (tmp_path / "_lmd_db.json").read_text() == before

    def test_unavailable_sets_are_still_reported(
        self, tmp_path: Path, stub_factory: ProviderFactory, capsys: pytest.CaptureFixture[str]
    ) -> None:
        process_owned_sets(
            SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), stub_factory, dry_run=True
        )
        assert "Unable to download manual for 9999" in capsys.readouterr().out

    def test_already_downloaded_sets_are_still_skipped(
        self, tmp_path: Path, stub_factory: ProviderFactory, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A dry run should report only the work a real run would do."""
        db = ManualDb.load(tmp_path, DbConfig())
        db.add_manual(SETS[0])
        (tmp_path / SETS[0].file_name).write_bytes(b"%PDF-1.4 stub")

        process_owned_sets(SETS, tmp_path, db, stub_factory, dry_run=True)
        assert "already exists, skipping" in capsys.readouterr().out

    def test_a_rename_is_reported_but_not_performed(
        self, tmp_path: Path, stub_factory: ProviderFactory, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = _db_with_manual_under_legacy_name(tmp_path)
        before = (tmp_path / "_lmd_db.json").read_text()

        process_owned_sets(SETS, tmp_path, db, stub_factory, dry_run=True)

        assert f"Renaming manual for {SETS[0]} to {SETS[0].file_name}." in capsys.readouterr().out
        assert (tmp_path / LEGACY_NAME).exists()
        assert not (tmp_path / SETS[0].file_name).exists()
        assert (tmp_path / "_lmd_db.json").read_text() == before

    def test_main_exits_zero_and_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_factory: ProviderFactory
    ) -> None:
        monkeypatch.setattr(ProviderFactory, "create", staticmethod(lambda config: stub_factory))
        config = tmp_path / "config.toml"
        config.write_text('[brickset]\nusername = "u"\npassword = "p"\n')

        assert main([str(tmp_path), "--config", str(config), "--dry-run"]) == 0
        assert not (tmp_path / "_lmd_db.json").exists()
        assert list(tmp_path.iterdir()) == [config]


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


class TestStopsWhenProvidersExhausted:
    def test_loop_exits_once_the_last_provider_retires(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class Dead(ManualProvider):
            def download_manual(
                self, lego_set: LegoSet, output_path: Path, *, dry_run: bool = False
            ) -> bool:
                raise ProviderUnavailable("login failed")

        many = [LegoSet(str(n), "1", f"Set {n}", "2001") for n in range(20)]
        factory = ProviderFactory([], [Dead()])
        process_owned_sets(many, tmp_path, ManualDb.load(tmp_path, DbConfig()), factory)

        out = capsys.readouterr().out
        assert "No usable manual providers left, stopping." in out
        assert out.count("Unable to download manual") == 1
        assert out.count("Processing") == 1

    def test_database_is_still_written_after_an_early_exit(self, tmp_path: Path) -> None:
        class Dead(ManualProvider):
            def download_manual(
                self, lego_set: LegoSet, output_path: Path, *, dry_run: bool = False
            ) -> bool:
                raise ProviderUnavailable("login failed")

        db = ManualDb.load(tmp_path, DbConfig())
        db.add_manual(LegoSet("999", "1", "Earlier", "2000"))
        process_owned_sets(SETS, tmp_path, db, ProviderFactory([], [Dead()]))
        assert (tmp_path / "_lmd_db.json").exists()

    def test_already_recorded_sets_do_not_block_the_exit(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The check sits at the top of the loop, so a run of skipped sets exits at once."""
        factory = ProviderFactory([], [])
        process_owned_sets(SETS, tmp_path, ManualDb.load(tmp_path, DbConfig()), factory)
        out = capsys.readouterr().out
        assert "No usable manual providers left, stopping." in out
        assert "Processing" not in out
