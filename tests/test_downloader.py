import json
import logging
from pathlib import Path

import pytest

from conftest import LEGACY_NAME, SETS, StubProvider, UnbuiltProvider, records_at
from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.db import JsonInstructionsDb, ManualStatus
from lego_manual_downloader.downloader import download_instruction_manuals
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.provider_chain import InstructionsProviderChain, SetsProviderChain
from lego_manual_downloader.providers import ProviderUnavailableError

Chains = tuple[SetsProviderChain, InstructionsProviderChain]


class DeadProvider(UnbuiltProvider):
    """A provider whose login is gone: unusable for the rest of the run."""

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        raise ProviderUnavailableError("login failed")


def _db_with_manual_under_legacy_name(tmp_path: Path) -> JsonInstructionsDb:
    """SETS[0]'s manual is on disk, but under a name the set no longer derives."""
    entry = {
        "number": "10179",
        "variant": "1",
        "name": "Millennium Falcon",
        "year": "2007",
        "file": LEGACY_NAME,
    }
    (tmp_path / "_lmd_db.json").write_text(json.dumps({"10179-1": entry}))
    (tmp_path / LEGACY_NAME).write_bytes(b"%PDF-1.4 original")
    return JsonInstructionsDb.load(tmp_path, DbConfig())


def _stub_chains(sets: list[LegoSet] | None = None) -> Chains:
    """One provider filling both roles, as Brickset does."""
    provider = StubProvider(sets)
    return SetsProviderChain([provider]), InstructionsProviderChain([provider])


@pytest.fixture
def stub_chains() -> Chains:
    return _stub_chains()


@pytest.fixture
def db(tmp_path: Path) -> JsonInstructionsDb:
    return JsonInstructionsDb.load(tmp_path, DbConfig())


class TestDownloadInstructionManuals:
    def test_downloads_and_records_each_set(
        self, tmp_path: Path, db: JsonInstructionsDb, stub_chains: Chains
    ) -> None:
        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=False)

        assert (tmp_path / "10179-1 Millennium Falcon (2007).pdf").exists()
        assert sorted(db.db) == ["10179-1", "6080-1"]

    def test_failed_download_is_not_recorded(
        self, tmp_path: Path, db: JsonInstructionsDb, stub_chains: Chains
    ) -> None:
        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=False)
        assert "9999-1" not in db.db

    def test_failed_download_is_reported_and_fails_the_run(
        self,
        tmp_path: Path,
        db: JsonInstructionsDb,
        stub_chains: Chains,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        assert not download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=False)
        assert records_at(caplog, logging.ERROR, "Unable to download manual for 9999")

    def test_a_fully_successful_run_reports_success(
        self, tmp_path: Path, db: JsonInstructionsDb
    ) -> None:
        assert download_instruction_manuals(tmp_path, db, *_stub_chains(SETS[:2]), dry_run=False)

    def test_already_recorded_sets_are_skipped(
        self, tmp_path: Path, db: JsonInstructionsDb, stub_chains: Chains
    ) -> None:
        db.add_manual(SETS[0])
        db.write_db()
        (tmp_path / SETS[0].file_name).write_bytes(b"%PDF-1.4 stub")

        second = JsonInstructionsDb.load(tmp_path, DbConfig())
        download_instruction_manuals(tmp_path, second, *stub_chains, dry_run=False)
        assert (tmp_path / "10179-1 Millennium Falcon (2007).pdf").read_bytes() == b"%PDF-1.4 stub"
        assert (tmp_path / "6080-1 King's Castle (1984).pdf").exists()

    def test_recorded_set_is_downloaded_again_when_its_file_is_gone(
        self, tmp_path: Path, db: JsonInstructionsDb, stub_chains: Chains
    ) -> None:
        """The DB records intent; the file on disk is the source of truth."""
        db.add_manual(SETS[0])
        db.write_db()

        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=False)
        assert (tmp_path / "10179-1 Millennium Falcon (2007).pdf").exists()

    def test_a_manual_already_on_disk_is_adopted_rather_than_redownloaded(
        self, tmp_path: Path, db: JsonInstructionsDb, stub_chains: Chains
    ) -> None:
        """An empty database next to a full download directory must not refetch everything."""
        (tmp_path / SETS[0].file_name).write_bytes(b"%PDF-1.4 original")

        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=False)

        assert (tmp_path / SETS[0].file_name).read_bytes() == b"%PDF-1.4 original"
        assert "10179-1" in json.loads((tmp_path / "_lmd_db.json").read_text())

    def test_a_misnamed_manual_is_renamed_rather_than_redownloaded(
        self, tmp_path: Path, stub_chains: Chains
    ) -> None:
        db = _db_with_manual_under_legacy_name(tmp_path)

        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=False)

        assert (tmp_path / SETS[0].file_name).read_bytes() == b"%PDF-1.4 original"
        assert not (tmp_path / LEGACY_NAME).exists()

        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert written["10179-1"]["file"] == SETS[0].file_name

    def test_writes_the_database(
        self, tmp_path: Path, db: JsonInstructionsDb, stub_chains: Chains
    ) -> None:
        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=False)
        written = json.loads((tmp_path / "_lmd_db.json").read_text())
        assert sorted(written) == ["10179-1", "6080-1"]

    def test_an_error_on_one_set_does_not_abort_the_rest(
        self,
        tmp_path: Path,
        db: JsonInstructionsDb,
        stub_chains: Chains,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """One unreadable set must not cost the user the whole run."""
        real_check = JsonInstructionsDb.check

        def flaky(db: JsonInstructionsDb, lego_set: LegoSet, dry_run: bool) -> ManualStatus:
            if lego_set.number == "10179":
                raise RuntimeError("disk gone")
            return real_check(db, lego_set, dry_run)

        monkeypatch.setattr(JsonInstructionsDb, "check", flaky)

        assert not download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=False)

        assert records_at(caplog, logging.ERROR, "disk gone")
        assert (tmp_path / SETS[1].file_name).exists()

    def test_owning_no_sets_reports_and_writes_nothing(
        self, tmp_path: Path, db: JsonInstructionsDb, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Owning nothing is a valid outcome, not a failure."""
        assert download_instruction_manuals(tmp_path, db, *_stub_chains([]), dry_run=False)
        assert records_at(caplog, logging.INFO, "No owned sets found.")
        assert not (tmp_path / "_lmd_db.json").exists()

    def test_no_sets_provider_stops_the_run(
        self, tmp_path: Path, db: JsonInstructionsDb, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Without a usable owned-sets provider there is nothing to work from."""
        assert not download_instruction_manuals(
            tmp_path,
            db,
            SetsProviderChain([]),
            InstructionsProviderChain([StubProvider()]),
            dry_run=False,
        )
        assert records_at(caplog, logging.ERROR, "No usable owned sets providers, stopping.")
        assert not (tmp_path / "_lmd_db.json").exists()


class TestDryRun:
    def test_nothing_is_written_to_disk(
        self, tmp_path: Path, db: JsonInstructionsDb, stub_chains: Chains
    ) -> None:
        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=True)

        assert list(tmp_path.iterdir()) == []
        assert db.db == {}

    def test_the_database_file_is_not_created(
        self, tmp_path: Path, db: JsonInstructionsDb, stub_chains: Chains
    ) -> None:
        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=True)
        assert not (tmp_path / "_lmd_db.json").exists()

    def test_an_existing_database_is_left_untouched(
        self, tmp_path: Path, stub_chains: Chains
    ) -> None:
        first = JsonInstructionsDb.load(tmp_path, DbConfig())
        first.add_manual(SETS[0])
        first.write_db()
        before = (tmp_path / "_lmd_db.json").read_text()

        reloaded = JsonInstructionsDb.load(tmp_path, DbConfig())
        download_instruction_manuals(tmp_path, reloaded, *stub_chains, dry_run=True)
        assert (tmp_path / "_lmd_db.json").read_text() == before

    def test_unavailable_sets_are_still_reported(
        self,
        tmp_path: Path,
        db: JsonInstructionsDb,
        stub_chains: Chains,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=True)
        assert records_at(caplog, logging.ERROR, "Unable to download manual for 9999")

    def test_already_downloaded_sets_are_still_skipped(
        self, tmp_path: Path, stub_chains: Chains, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A dry run should report only the work a real run would do."""
        db = JsonInstructionsDb.load(tmp_path, DbConfig())
        db.add_manual(SETS[0])
        (tmp_path / SETS[0].file_name).write_bytes(b"%PDF-1.4 stub")

        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=True)
        assert records_at(caplog, logging.INFO, "already exists, skipping")

    def test_a_rename_is_reported_but_not_performed(
        self, tmp_path: Path, stub_chains: Chains, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A dry run must not touch the download directory, renames included."""
        db = _db_with_manual_under_legacy_name(tmp_path)
        before = (tmp_path / "_lmd_db.json").read_text()

        download_instruction_manuals(tmp_path, db, *stub_chains, dry_run=True)

        assert records_at(
            caplog, logging.INFO, f"Renaming manual for {SETS[0]} to {SETS[0].file_name}."
        )
        assert (tmp_path / LEGACY_NAME).exists()
        assert not (tmp_path / SETS[0].file_name).exists()
        assert (tmp_path / "_lmd_db.json").read_text() == before


class TestStopsWhenProvidersExhausted:
    def test_loop_exits_once_the_last_provider_retires(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        many = [LegoSet(str(n), "1", f"Set {n}", "2001") for n in range(20)]
        sets_chain = SetsProviderChain([StubProvider(many)])
        manual_chain = InstructionsProviderChain([DeadProvider()])

        download_instruction_manuals(
            tmp_path,
            JsonInstructionsDb.load(tmp_path, DbConfig()),
            sets_chain,
            manual_chain,
            dry_run=False,
        )

        assert records_at(caplog, logging.ERROR, "No usable manual providers left, stopping.")
        assert len(records_at(caplog, logging.ERROR, "Unable to download manual")) == 1
        assert len(records_at(caplog, logging.DEBUG, "Processing")) == 1

    def test_database_is_still_written_after_an_early_exit(self, tmp_path: Path) -> None:
        sets_chain = SetsProviderChain([StubProvider()])
        manual_chain = InstructionsProviderChain([DeadProvider()])
        db = JsonInstructionsDb.load(tmp_path, DbConfig())
        db.add_manual(LegoSet("999", "1", "Earlier", "2000"))

        download_instruction_manuals(tmp_path, db, sets_chain, manual_chain, dry_run=False)
        assert (tmp_path / "_lmd_db.json").exists()

    def test_already_recorded_sets_do_not_block_the_exit(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The check sits at the top of the loop, so a run of skipped sets exits at once."""
        sets_chain = SetsProviderChain([StubProvider()])

        download_instruction_manuals(
            tmp_path,
            JsonInstructionsDb.load(tmp_path, DbConfig()),
            sets_chain,
            InstructionsProviderChain([]),
            dry_run=False,
        )

        assert records_at(caplog, logging.ERROR, "No usable manual providers left, stopping.")
        assert not records_at(caplog, logging.DEBUG, "Processing")
