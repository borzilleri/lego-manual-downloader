import json
from pathlib import Path

import pytest

from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.db import ManualDb
from lego_manual_downloader.lego import LegoSet

FALCON = LegoSet("10179", "1", "Millennium Falcon", "2007")
LEGACY_NAME = "10179 Falcon.pdf"


def _place_manual(download_path: Path, name: str) -> None:
    (download_path / name).write_bytes(b"%PDF-1.4 stub")


def _db_recording(tmp_path: Path, file_name: str, on_disk: bool = False) -> ManualDb:
    """A DB whose one entry says FALCON's manual is called `file_name`."""
    entry = {**FALCON.to_dict(), "file": file_name}
    if on_disk:
        _place_manual(tmp_path, file_name)
    return ManualDb(tmp_path, tmp_path / "_lmd_db.json", {"10179-1": entry})


def _record(db: ManualDb, lego_set: LegoSet, on_disk: bool = True) -> None:
    """Record a set, optionally creating the manual it points at."""
    db.add_manual(lego_set)
    if on_disk:
        _place_manual(db.download_path, lego_set.file_name)


def test_load_missing_file_starts_empty(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    assert db.db == {}
    assert db.db_file == tmp_path / "_lmd_db.json"


def test_load_honours_configured_filename(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig(file="custom.json"))
    assert db.db_file == tmp_path / "custom.json"


def test_add_then_write_then_reload_round_trips(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    _record(db, FALCON)
    db.write_db()

    reloaded = ManualDb.load(tmp_path, DbConfig())
    assert reloaded.has_manual(FALCON)
    assert reloaded.db["10179-1"] == FALCON
    assert json.loads((tmp_path / "_lmd_db.json").read_text())["10179-1"] == {
        "number": "10179",
        "variant": "1",
        "name": "Millennium Falcon",
        "year": "2007",
        "file": "10179-1 Millennium Falcon (2007).pdf",
    }


def test_has_manual_is_false_for_unknown_set(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    assert not db.has_manual(LegoSet("0000", "1", "Unknown", "1999"))


def test_has_manual_is_false_when_the_recorded_file_is_missing(tmp_path: Path) -> None:
    """A deleted manual must be re-downloaded, not reported as present."""
    db = ManualDb.load(tmp_path, DbConfig())
    _record(db, FALCON, on_disk=False)
    assert not db.has_manual(FALCON)


def test_has_manual_is_true_once_the_file_appears(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    _record(db, FALCON, on_disk=False)
    assert not db.has_manual(FALCON)

    _place_manual(tmp_path, FALCON.file_name)
    assert db.has_manual(FALCON)


def test_variants_of_one_set_number_do_not_collide(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    _record(db, FALCON)
    _record(db, LegoSet("10179", "2", "Millennium Falcon", "2017"))

    assert sorted(db.db) == ["10179-1", "10179-2"]
    assert db.has_manual(FALCON)
    assert db.has_manual(LegoSet("10179", "2", "Millennium Falcon", "2017"))


class TestUnreadableEntries:
    def test_an_entry_missing_a_field_is_dropped_with_a_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = ManualDb(tmp_path, tmp_path / "_lmd_db.json", {"1-1": {"number": "1"}})
        assert db.db == {}
        assert "Ignoring unreadable database entry '1-1'" in capsys.readouterr().out

    def test_a_legacy_entry_without_a_variant_is_dropped_with_a_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The pre-variant on-disk format, keyed by bare set number."""
        legacy = {
            "1478": {
                "number": "1478",
                "name": "Mobile Satellite Up-Link",
                "year": "1991",
                "file": "1478-1 Mobile Satellite Up-Link (1991).pdf",
            }
        }
        (tmp_path / "_lmd_db.json").write_text(json.dumps(legacy))

        db = ManualDb.load(tmp_path, DbConfig())
        assert db.db == {}
        assert "Ignoring unreadable database entry '1478'" in capsys.readouterr().out

    def test_a_non_dict_entry_is_dropped_with_a_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = ManualDb(tmp_path, tmp_path / "_lmd_db.json", {"1-1": "not an entry"})
        assert db.db == {}
        assert "Ignoring unreadable database entry '1-1'" in capsys.readouterr().out

    def test_a_dropped_entry_falls_through_to_the_disk_check(self, tmp_path: Path) -> None:
        """Dropping a record must not hide a manual that is actually there."""
        db = ManualDb(tmp_path, tmp_path / "_lmd_db.json", {"10179-1": {}})
        assert not db.has_manual(FALCON)

        _place_manual(tmp_path, FALCON.file_name)
        assert db.has_manual(FALCON)

    def test_entries_are_keyed_by_their_own_set_number(self, tmp_path: Path) -> None:
        """A record filed under the wrong key must still be found."""
        entry = {"number": "10179", "variant": "1", "name": "Millennium Falcon", "year": "2007"}
        db = ManualDb(tmp_path, tmp_path / "_lmd_db.json", {"wrong-key": entry})
        assert sorted(db.db) == ["10179-1"]


class TestAdoptingAManualFromDisk:
    def test_a_manual_on_disk_but_not_in_the_db_is_adopted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _place_manual(tmp_path, FALCON.file_name)
        db = ManualDb.load(tmp_path, DbConfig())

        assert db.has_manual(FALCON)
        assert db.db == {"10179-1": FALCON}
        assert "exists in download path but not in database" in capsys.readouterr().out

    def test_an_adopted_manual_survives_a_write(self, tmp_path: Path) -> None:
        _place_manual(tmp_path, FALCON.file_name)
        db = ManualDb.load(tmp_path, DbConfig())
        db.has_manual(FALCON)
        db.write_db()

        assert ManualDb.load(tmp_path, DbConfig()).db == {"10179-1": FALCON}

    def test_nothing_is_adopted_when_the_file_is_absent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = ManualDb.load(tmp_path, DbConfig())
        assert not db.has_manual(FALCON)
        assert db.db == {}
        assert "exists in download path" not in capsys.readouterr().out


class TestRecordedFileName:
    def test_the_recorded_name_is_checked_instead_of_the_derived_one(self, tmp_path: Path) -> None:
        """A manual saved under an older name must not be re-downloaded."""
        db = _db_recording(tmp_path, LEGACY_NAME)
        assert not db.has_manual(FALCON)

        _place_manual(tmp_path, LEGACY_NAME)
        assert db.has_manual(FALCON)

    def test_the_derived_name_does_not_satisfy_a_recorded_name(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME)
        _place_manual(tmp_path, FALCON.file_name)
        assert not db.has_manual(FALCON)

    def test_the_recorded_name_survives_a_write(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME)
        db.write_db()

        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert written["10179-1"]["file"] == LEGACY_NAME

    def test_a_recorded_name_is_looked_up_inside_the_download_directory(
        self, tmp_path: Path
    ) -> None:
        """The DB is not a trusted source of paths; sanitisation is covered in test_lego."""
        db = _db_recording(tmp_path, "../escape.pdf")
        checked = tmp_path / db.db["10179-1"].current_file_name

        assert checked.parent == tmp_path
        assert not db.has_manual(FALCON)


class TestRename:
    """A set whose manual is on disk under an older name is moved, not re-downloaded."""

    def test_needs_rename_is_false_for_an_unknown_set(self, tmp_path: Path) -> None:
        db = ManualDb.load(tmp_path, DbConfig())
        assert not db.needs_rename(FALCON)

    def test_needs_rename_is_false_when_the_name_already_matches(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, FALCON.file_name, on_disk=True)
        assert not db.needs_rename(FALCON)

    def test_needs_rename_is_true_when_the_recorded_name_differs(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        assert db.needs_rename(FALCON)

    def test_needs_rename_tracks_the_incoming_sets_name(self, tmp_path: Path) -> None:
        """The provider is the authority on what a set is called today."""
        db = _db_recording(tmp_path, FALCON.file_name, on_disk=True)
        renamed_upstream = LegoSet("10179", "1", "Millennium Falcon UCS", "2007")
        assert db.needs_rename(renamed_upstream)

    def test_rename_moves_the_file(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        db.rename(FALCON)

        assert (tmp_path / FALCON.file_name).exists()
        assert not (tmp_path / LEGACY_NAME).exists()

    def test_rename_leaves_the_manual_findable(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        db.rename(FALCON)

        assert db.has_manual(FALCON)
        assert not db.needs_rename(FALCON)

    def test_rename_records_the_new_name(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        db.rename(FALCON)
        db.write_db()

        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert written["10179-1"]["file"] == FALCON.file_name

    def test_rename_adopts_the_incoming_sets_metadata(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, FALCON.file_name, on_disk=True)
        renamed_upstream = LegoSet("10179", "1", "Millennium Falcon UCS", "2007")
        db.rename(renamed_upstream)

        assert (tmp_path / renamed_upstream.file_name).exists()
        assert db.db["10179-1"].name == "Millennium Falcon UCS"

    def test_rename_is_a_no_op_for_an_unknown_set(self, tmp_path: Path) -> None:
        db = ManualDb.load(tmp_path, DbConfig())
        db.rename(FALCON)
        assert db.db == {}

    def test_a_collision_warns_and_moves_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Never destroy a manual that is already sitting at the target name."""
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        (tmp_path / FALCON.file_name).write_bytes(b"%PDF-1.4 other")
        db.rename(FALCON)

        assert (tmp_path / LEGACY_NAME).exists()
        assert (tmp_path / FALCON.file_name).read_bytes() == b"%PDF-1.4 other"
        assert "target already exists" in capsys.readouterr().out

    def test_a_collision_leaves_the_db_pointing_at_the_real_file(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        (tmp_path / FALCON.file_name).write_bytes(b"%PDF-1.4 other")
        db.rename(FALCON)
        db.write_db()

        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert written["10179-1"]["file"] == LEGACY_NAME

    def test_an_unwritable_directory_warns_rather_than_raising(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        tmp_path.chmod(0o500)
        try:
            db.rename(FALCON)
            assert "Could not rename" in capsys.readouterr().out
        finally:
            tmp_path.chmod(0o700)

        assert (tmp_path / LEGACY_NAME).exists()


def test_existing_db_file_keeps_loading(tmp_path: Path) -> None:
    """Guards the on-disk schema: an existing DB must survive a code change."""
    existing = {
        "10179-1": {
            "number": "10179",
            "variant": "1",
            "name": "Millennium Falcon",
            "year": "2007",
            "file": "10179-1 Millennium Falcon (2007).pdf",
        }
    }
    (tmp_path / "_lmd_db.json").write_text(json.dumps(existing))
    _place_manual(tmp_path, FALCON.file_name)

    db = ManualDb.load(tmp_path, DbConfig())
    assert db.db == {"10179-1": FALCON}
    assert db.has_manual(FALCON)

    db.write_db()
    assert json.loads((tmp_path / "_lmd_db.json").read_text()) == existing


def test_write_preserves_previously_recorded_entries(tmp_path: Path) -> None:
    first = ManualDb.load(tmp_path, DbConfig())
    first.add_manual(LegoSet("1", "1", "One", "2001"))
    first.write_db()

    second = ManualDb.load(tmp_path, DbConfig())
    second.add_manual(LegoSet("2", "1", "Two", "2002"))
    second.write_db()

    third = ManualDb.load(tmp_path, DbConfig())
    assert sorted(third.db) == ["1-1", "2-1"]


def test_written_file_is_valid_indented_json(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    db.add_manual(LegoSet("1", "1", "One", "2001"))
    db.write_db()

    text = (tmp_path / "_lmd_db.json").read_text()
    assert json.loads(text)
    assert "\n" in text
