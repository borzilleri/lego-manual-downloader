import json
from pathlib import Path

from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.db import ManualDb
from lego_manual_downloader.lego import LegoSet

FALCON = LegoSet("10179", "1", "Millennium Falcon", "2007")


def _record(db: ManualDb, lego_set: LegoSet, on_disk: bool = True) -> None:
    """Record a set, optionally creating the manual it points at."""
    db.add_manual(lego_set)
    if on_disk:
        (db.download_path / lego_set.file_name).write_bytes(b"%PDF-1.4 stub")


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
    assert reloaded.has_manual("10179-1")
    assert reloaded.db["10179-1"] == {
        "number": "10179",
        "variant": "1",
        "name": "Millennium Falcon",
        "year": "2007",
        "file": "10179-1 Millennium Falcon (2007).pdf",
    }


def test_has_manual_is_false_for_unknown_set(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    assert not db.has_manual("0000-1")


def test_has_manual_is_false_when_the_recorded_file_is_missing(tmp_path: Path) -> None:
    """A deleted manual must be re-downloaded, not reported as present."""
    db = ManualDb.load(tmp_path, DbConfig())
    _record(db, FALCON, on_disk=False)
    assert not db.has_manual("10179-1")


def test_has_manual_is_true_once_the_file_appears(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    _record(db, FALCON, on_disk=False)
    assert not db.has_manual("10179-1")

    (tmp_path / FALCON.file_name).write_bytes(b"%PDF-1.4 stub")
    assert db.has_manual("10179-1")


def test_has_manual_is_false_for_an_entry_without_a_usable_filename(tmp_path: Path) -> None:
    """An empty filename would otherwise resolve to the download directory itself."""
    db = ManualDb(tmp_path, tmp_path / "_lmd_db.json", {"1-1": {"file": ""}, "2-1": {}})
    assert not db.has_manual("1-1")
    assert not db.has_manual("2-1")


def test_variants_of_one_set_number_do_not_collide(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    _record(db, FALCON)
    _record(db, LegoSet("10179", "2", "Millennium Falcon", "2017"))

    assert sorted(db.db) == ["10179-1", "10179-2"]
    assert db.has_manual("10179-1")
    assert db.has_manual("10179-2")


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
    (tmp_path / "10179-1 Millennium Falcon (2007).pdf").write_bytes(b"%PDF-1.4 stub")

    db = ManualDb.load(tmp_path, DbConfig())
    assert db.db == existing
    assert db.has_manual("10179-1")


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
