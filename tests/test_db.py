import json
import logging
from pathlib import Path

import pytest

from conftest import records_at
from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.db import JsonInstructionsDb, ManualStatus, StoredManual
from lego_manual_downloader.lego import LegoSet

FALCON = LegoSet("10179", "1", "Millennium Falcon", "2007")
LEGACY_NAME = "10179 Falcon.pdf"
FALCON_FIELDS = {
    "number": "10179",
    "variant": "1",
    "name": "Millennium Falcon",
    "year": "2007",
}


def _place_manual(download_path: Path, name: str) -> None:
    (download_path / name).write_bytes(b"%PDF-1.4 stub")


def _db_recording(tmp_path: Path, file_name: str, on_disk: bool = False) -> JsonInstructionsDb:
    """A DB whose one entry says FALCON's manual is called `file_name`."""
    entry = {**FALCON_FIELDS, "file": file_name}
    if on_disk:
        _place_manual(tmp_path, file_name)
    return JsonInstructionsDb(tmp_path, tmp_path / "_lmd_db.json", {"10179-1": entry})


def _record(db: JsonInstructionsDb, lego_set: LegoSet, on_disk: bool = True) -> None:
    """Record a set, optionally creating the manual it points at."""
    db.add_manual(lego_set)
    if on_disk:
        _place_manual(db.download_path, lego_set.file_name)


def test_load_missing_file_starts_empty(tmp_path: Path) -> None:
    db = JsonInstructionsDb.load(tmp_path, DbConfig())
    assert db.db == {}
    assert db.db_file == tmp_path / "_lmd_db.json"


def test_load_honours_configured_filename(tmp_path: Path) -> None:
    db = JsonInstructionsDb.load(tmp_path, DbConfig(file="custom.json"))
    assert db.db_file == tmp_path / "custom.json"


def test_add_then_write_then_reload_round_trips(tmp_path: Path) -> None:
    db = JsonInstructionsDb.load(tmp_path, DbConfig())
    _record(db, FALCON)
    db.write_db()

    reloaded = JsonInstructionsDb.load(tmp_path, DbConfig())
    assert reloaded.check(FALCON, dry_run=False) is ManualStatus.PRESENT
    assert reloaded.db["10179-1"].lego_set == FALCON
    assert json.loads((tmp_path / "_lmd_db.json").read_text())["10179-1"] == {
        **FALCON_FIELDS,
        "file": "10179-1 Millennium Falcon (2007).pdf",
    }


def test_variants_of_one_set_number_do_not_collide(tmp_path: Path) -> None:
    db = JsonInstructionsDb.load(tmp_path, DbConfig())
    variant_two = LegoSet("10179", "2", "Millennium Falcon", "2017")
    _record(db, FALCON)
    _record(db, variant_two)

    assert sorted(db.db) == ["10179-1", "10179-2"]
    assert db.check(FALCON, dry_run=False) is ManualStatus.PRESENT
    assert db.check(variant_two, dry_run=False) is ManualStatus.PRESENT


class TestStoredManual:
    def test_reads_every_field(self) -> None:
        stored = StoredManual.from_dict({**FALCON_FIELDS, "file": LEGACY_NAME})
        assert stored is not None
        assert stored.lego_set == FALCON
        assert stored.file_name == LEGACY_NAME

    def test_a_missing_file_key_falls_back_to_the_derived_name(self) -> None:
        """An entry without a recorded name is still usable, not discarded."""
        stored = StoredManual.from_dict(FALCON_FIELDS)
        assert stored is not None
        assert stored.file_name == FALCON.file_name

    @pytest.mark.parametrize("recorded", ["../escape.pdf", "/etc/passwd", "..\\escape.pdf"])
    def test_a_recorded_name_cannot_escape_the_download_directory(self, recorded: str) -> None:
        """The DB is not a trusted source of paths."""
        stored = StoredManual.from_dict({**FALCON_FIELDS, "file": recorded})
        assert stored is not None
        assert Path(stored.file_name).name == stored.file_name
        assert not Path(stored.file_name).is_absolute()

    @pytest.mark.parametrize("missing", ["number", "variant", "name", "year"])
    def test_a_missing_required_field_yields_none(self, missing: str) -> None:
        assert StoredManual.from_dict({k: v for k, v in FALCON_FIELDS.items() if k != missing}) is (
            None
        )

    @pytest.mark.parametrize("data", ["not an entry", 42, None, []])
    def test_a_non_dict_yields_none(self, data: object) -> None:
        assert StoredManual.from_dict(data) is None

    def test_to_dict_writes_the_persisted_schema(self) -> None:
        assert StoredManual(lego_set=FALCON, file_name=LEGACY_NAME).to_dict() == {
            **FALCON_FIELDS,
            "file": LEGACY_NAME,
        }

    def test_it_round_trips(self) -> None:
        original = StoredManual(lego_set=FALCON, file_name=LEGACY_NAME)
        assert StoredManual.from_dict(original.to_dict()) == original


class TestUnreadableEntries:
    def test_an_entry_missing_a_field_is_dropped_with_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = JsonInstructionsDb(tmp_path, tmp_path / "_lmd_db.json", {"1-1": {"number": "1"}})
        assert db.db == {}
        assert records_at(caplog, logging.WARNING, "Ignoring unreadable database entry '1-1'")

    def test_a_legacy_entry_without_a_variant_is_dropped_with_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
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

        db = JsonInstructionsDb.load(tmp_path, DbConfig())
        assert db.db == {}
        assert records_at(caplog, logging.WARNING, "Ignoring unreadable database entry '1478'")

    def test_a_non_dict_entry_is_dropped_with_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = JsonInstructionsDb(tmp_path, tmp_path / "_lmd_db.json", {"1-1": "not an entry"})
        assert db.db == {}
        assert records_at(caplog, logging.WARNING, "Ignoring unreadable database entry '1-1'")

    def test_a_dropped_entry_falls_through_to_the_disk_check(self, tmp_path: Path) -> None:
        """Dropping a record must not hide a manual that is actually there."""
        db = JsonInstructionsDb(tmp_path, tmp_path / "_lmd_db.json", {"10179-1": {}})
        assert db.check(FALCON, dry_run=False) is ManualStatus.MISSING

        _place_manual(tmp_path, FALCON.file_name)
        assert db.check(FALCON, dry_run=False) is ManualStatus.PRESENT

    def test_entries_are_keyed_by_their_own_set_number(self, tmp_path: Path) -> None:
        """A record filed under the wrong key must still be found."""
        db = JsonInstructionsDb(
            tmp_path, tmp_path / "_lmd_db.json", {"wrong-key": dict(FALCON_FIELDS)}
        )
        assert sorted(db.db) == ["10179-1"]


class TestCheck:
    """One case per (database entry, file on disk) state."""

    def test_unknown_set_with_no_file_is_missing(self, tmp_path: Path) -> None:
        db = JsonInstructionsDb.load(tmp_path, DbConfig())
        assert db.check(LegoSet("0000", "1", "Unknown", "1999"), dry_run=False) is (
            ManualStatus.MISSING
        )

    def test_a_manual_on_disk_but_not_in_the_db_is_adopted(self, tmp_path: Path) -> None:
        _place_manual(tmp_path, FALCON.file_name)
        db = JsonInstructionsDb.load(tmp_path, DbConfig())

        assert db.check(FALCON, dry_run=False) is ManualStatus.PRESENT
        assert db.db["10179-1"] == StoredManual(lego_set=FALCON, file_name=FALCON.file_name)

    def test_an_adopted_manual_survives_a_write(self, tmp_path: Path) -> None:
        _place_manual(tmp_path, FALCON.file_name)
        db = JsonInstructionsDb.load(tmp_path, DbConfig())
        db.check(FALCON, dry_run=False)
        db.write_db()

        reloaded = JsonInstructionsDb.load(tmp_path, DbConfig())
        assert reloaded.db["10179-1"].lego_set == FALCON

    def test_a_recorded_manual_at_its_current_name_is_present(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, FALCON.file_name, on_disk=True)
        assert db.check(FALCON, dry_run=False) is ManualStatus.PRESENT

    def test_a_recorded_manual_whose_file_is_gone_is_missing(self, tmp_path: Path) -> None:
        """A deleted manual must be re-downloaded, not reported as present."""
        db = _db_recording(tmp_path, FALCON.file_name, on_disk=False)
        assert db.check(FALCON, dry_run=False) is ManualStatus.MISSING

    def test_a_gone_recording_with_a_correctly_named_file_is_present(self, tmp_path: Path) -> None:
        """The recorded name is stale but the manual is already where it belongs."""
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=False)
        _place_manual(tmp_path, FALCON.file_name)
        assert db.check(FALCON, dry_run=False) is ManualStatus.PRESENT

    def test_a_misnamed_manual_is_renamed(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        assert db.check(FALCON, dry_run=False) is ManualStatus.RENAMED

        assert (tmp_path / FALCON.file_name).exists()
        assert not (tmp_path / LEGACY_NAME).exists()

    def test_a_rename_records_the_new_name(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        db.check(FALCON, dry_run=False)
        db.write_db()

        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert written["10179-1"]["file"] == FALCON.file_name

    def test_a_renamed_manual_is_present_on_the_next_check(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        db.check(FALCON, dry_run=False)
        assert db.check(FALCON, dry_run=False) is ManualStatus.PRESENT

    def test_a_rename_adopts_the_incoming_sets_metadata(self, tmp_path: Path) -> None:
        """The provider is the authority on what a set is called today."""
        db = _db_recording(tmp_path, FALCON.file_name, on_disk=True)
        renamed_upstream = LegoSet("10179", "1", "Millennium Falcon UCS", "2007")

        assert db.check(renamed_upstream, dry_run=False) is ManualStatus.RENAMED
        assert (tmp_path / renamed_upstream.file_name).exists()
        assert db.db["10179-1"].lego_set.name == "Millennium Falcon UCS"


class TestCheckDryRun:
    def test_a_rename_is_reported_but_not_performed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)

        assert db.check(FALCON, dry_run=True) is ManualStatus.RENAMED
        assert (tmp_path / LEGACY_NAME).exists()
        assert not (tmp_path / FALCON.file_name).exists()
        assert records_at(caplog, logging.INFO, "Renaming manual")

    def test_the_recorded_name_is_left_alone(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        db.check(FALCON, dry_run=True)
        assert db.db["10179-1"].file_name == LEGACY_NAME


class TestRenameFailures:
    def test_a_collision_warns_and_moves_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Never destroy a manual that is already sitting at the target name."""
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        (tmp_path / FALCON.file_name).write_bytes(b"%PDF-1.4 other")

        db.check(FALCON, dry_run=False)

        assert (tmp_path / LEGACY_NAME).exists()
        assert (tmp_path / FALCON.file_name).read_bytes() == b"%PDF-1.4 other"
        assert records_at(caplog, logging.WARNING, "target already exists")

    def test_a_collision_leaves_the_db_pointing_at_the_real_file(self, tmp_path: Path) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        (tmp_path / FALCON.file_name).write_bytes(b"%PDF-1.4 other")
        db.check(FALCON, dry_run=False)
        db.write_db()

        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert written["10179-1"]["file"] == LEGACY_NAME

    def test_an_unwritable_directory_warns_rather_than_raising(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _db_recording(tmp_path, LEGACY_NAME, on_disk=True)
        tmp_path.chmod(0o500)
        try:
            db.check(FALCON, dry_run=False)
            assert records_at(caplog, logging.WARNING, "Could not rename")
        finally:
            tmp_path.chmod(0o700)

        assert (tmp_path / LEGACY_NAME).exists()


def test_existing_db_file_keeps_loading(tmp_path: Path) -> None:
    """Guards the on-disk schema: an existing DB must survive a code change."""
    existing = {"10179-1": {**FALCON_FIELDS, "file": "10179-1 Millennium Falcon (2007).pdf"}}
    (tmp_path / "_lmd_db.json").write_text(json.dumps(existing))
    _place_manual(tmp_path, FALCON.file_name)

    db = JsonInstructionsDb.load(tmp_path, DbConfig())
    assert db.db["10179-1"].lego_set == FALCON
    assert db.check(FALCON, dry_run=False) is ManualStatus.PRESENT

    db.write_db()
    assert json.loads((tmp_path / "_lmd_db.json").read_text()) == existing


def test_write_preserves_previously_recorded_entries(tmp_path: Path) -> None:
    first = JsonInstructionsDb.load(tmp_path, DbConfig())
    first.add_manual(LegoSet("1", "1", "One", "2001"))
    first.write_db()

    second = JsonInstructionsDb.load(tmp_path, DbConfig())
    second.add_manual(LegoSet("2", "1", "Two", "2002"))
    second.write_db()

    third = JsonInstructionsDb.load(tmp_path, DbConfig())
    assert sorted(third.db) == ["1-1", "2-1"]


def test_written_file_is_valid_indented_json(tmp_path: Path) -> None:
    db = JsonInstructionsDb.load(tmp_path, DbConfig())
    db.add_manual(LegoSet("1", "1", "One", "2001"))
    db.write_db()

    text = (tmp_path / "_lmd_db.json").read_text()
    assert json.loads(text)
    assert "\n" in text


def test_write_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    """The DB is written atomically, like the manuals themselves."""
    db = JsonInstructionsDb.load(tmp_path, DbConfig())
    db.add_manual(LegoSet("1", "1", "One", "2001"))
    db.write_db()

    assert [p.name for p in tmp_path.iterdir()] == ["_lmd_db.json"]
