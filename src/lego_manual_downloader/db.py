import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pathvalidate

from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.files import atomic_write
from lego_manual_downloader.lego import LegoSet

logger = logging.getLogger(__name__)


class ManualStatus(Enum):
    MISSING = "missing"
    PRESENT = "present"
    RENAMED = "renamed"


@dataclass(frozen=True)
class StoredManual:
    lego_set: LegoSet
    file_name: str

    @staticmethod
    def from_dict(data: object) -> "StoredManual | None":
        if not isinstance(data, dict):
            return None
        try:
            lego_set = LegoSet(
                number=data["number"],
                variant=data["variant"],
                name=data["name"],
                year=data["year"],
            )
            file_name = data.get("file", lego_set.file_name)
            return StoredManual(
                lego_set=lego_set, file_name=pathvalidate.sanitize_filename(file_name)
            )
        except KeyError:
            return None

    def to_dict(self) -> dict[str, str]:
        return {
            "number": self.lego_set.number,
            "variant": self.lego_set.variant,
            "name": self.lego_set.name,
            "year": self.lego_set.year,
            "file": self.file_name,
        }


class InstructionsDb(ABC):
    @abstractmethod
    def check(self, lego_set: LegoSet, dry_run: bool) -> ManualStatus: ...
    @abstractmethod
    def add_manual(self, lego_set: LegoSet) -> None: ...
    @abstractmethod
    def write_db(self) -> None: ...


class JsonInstructionsDb(InstructionsDb):
    def __init__(self, download_path: Path, db_file: Path, db: dict[str, object]) -> None:
        self.download_path = download_path
        self.db_file = db_file
        self.db: dict[str, StoredManual] = {}
        for key, entry in db.items():
            stored_manual = StoredManual.from_dict(entry)
            if stored_manual is None:
                logger.warning("Ignoring unreadable database entry '%s'.", key)
                continue
            self.db[stored_manual.lego_set.set_number] = stored_manual

    def check(self, lego_set: LegoSet, dry_run: bool) -> ManualStatus:
        expected = self.download_path / lego_set.file_name
        entry = self.db.get(lego_set.set_number)
        if entry is None:
            if not expected.exists():
                return ManualStatus.MISSING
            self.add_manual(lego_set)
            return ManualStatus.PRESENT
        if (self.download_path / entry.file_name).exists():
            if entry.file_name == lego_set.file_name:
                return ManualStatus.PRESENT
            else:
                self._rename(lego_set, dry_run=dry_run)
                return ManualStatus.RENAMED
        if expected.exists():
            return ManualStatus.PRESENT
        return ManualStatus.MISSING

    def add_manual(self, lego_set: LegoSet) -> None:
        self.db[lego_set.set_number] = StoredManual(lego_set=lego_set, file_name=lego_set.file_name)

    def _rename(self, lego_set: LegoSet, dry_run: bool) -> None:
        source = self.download_path / self.db[lego_set.set_number].file_name
        target = self.download_path / lego_set.file_name
        if target.exists():
            logger.warning(
                "Cannot rename %s to %s, target already exists.", source.name, target.name
            )
            return
        logger.info("Renaming manual for %s to %s.", lego_set, target.name)
        if dry_run:
            return
        try:
            source.rename(target)
        except OSError as e:
            logger.warning("Could not rename %s to %s: %s", source.name, target.name, e)
            return
        self.db[lego_set.set_number] = StoredManual(lego_set=lego_set, file_name=lego_set.file_name)

    def write_db(self) -> None:
        db_data = {k: v.to_dict() for k, v in self.db.items()}
        with atomic_write(self.db_file) as temp_file:
            temp_file.write(json.dumps(db_data, indent=2).encode("utf-8"))

    @staticmethod
    def load(download_path: Path, config: DbConfig) -> "JsonInstructionsDb":
        db_path = download_path / config.file
        db = json.loads(db_path.read_text()) if db_path.exists() else {}
        return JsonInstructionsDb(download_path, db_path, db)
