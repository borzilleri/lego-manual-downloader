import json
from pathlib import Path

from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.db import ManualDb
from lego_manual_downloader.lego import LegoSet


def test_load_missing_file_starts_empty(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    assert db.db == {}
    assert db.db_file == tmp_path / "_lmd_db.json"


def test_load_honours_configured_filename(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig(file="custom.json"))
    assert db.db_file == tmp_path / "custom.json"


def test_add_then_write_then_reload_round_trips(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    lego_set = LegoSet("10179", "Millennium Falcon", "2007")
    db.add_manual(lego_set)
    db.write_db()

    reloaded = ManualDb.load(tmp_path, DbConfig())
    assert reloaded.has_manual("10179")
    assert reloaded.db["10179"] == {
        "number": "10179",
        "name": "Millennium Falcon",
        "year": "2007",
        "file": "10179 Millennium Falcon (2007).pdf",
    }


def test_has_manual_is_false_for_unknown_set(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    assert not db.has_manual("0000")


def test_existing_db_file_keeps_loading(tmp_path: Path) -> None:
    """Guards the on-disk schema: an existing DB must survive a code change."""
    existing = {
        "10179": {
            "number": "10179",
            "name": "Millennium Falcon",
            "year": "2007",
            "file": "10179 Millennium Falcon (2007).pdf",
        }
    }
    (tmp_path / "_lmd_db.json").write_text(json.dumps(existing))

    db = ManualDb.load(tmp_path, DbConfig())
    assert db.db == existing
    assert db.has_manual("10179")


def test_write_preserves_previously_recorded_entries(tmp_path: Path) -> None:
    first = ManualDb.load(tmp_path, DbConfig())
    first.add_manual(LegoSet("1", "One", "2001"))
    first.write_db()

    second = ManualDb.load(tmp_path, DbConfig())
    second.add_manual(LegoSet("2", "Two", "2002"))
    second.write_db()

    third = ManualDb.load(tmp_path, DbConfig())
    assert sorted(third.db) == ["1", "2"]


def test_written_file_is_valid_indented_json(tmp_path: Path) -> None:
    db = ManualDb.load(tmp_path, DbConfig())
    db.add_manual(LegoSet("1", "One", "2001"))
    db.write_db()

    text = (tmp_path / "_lmd_db.json").read_text()
    assert json.loads(text)
    assert "\n" in text
