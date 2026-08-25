import json
from pathlib import Path

from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.lego import LegoSet


class ManualDb:
    def __init__(self, db_file: Path, db: dict[str, dict[str, str]]) -> None:
        self.db_file = db_file
        self.db = db

    def has_manual(self, set_number: str) -> bool:
        return set_number in self.db

    def add_manual(self, lego_set: LegoSet) -> None:
        self.db[lego_set.number] = {
            "number": lego_set.number,
            "name": lego_set.name,
            "year": lego_set.year,
            "file": lego_set.file_name,
        }

    def write_db(self) -> None:
        self.db_file.write_text(json.dumps(self.db, indent=4))

    @staticmethod
    def load(output_path: Path, config: DbConfig) -> "ManualDb":
        db_path = output_path / config.file
        db = json.loads(db_path.read_text()) if db_path.exists() else {}
        return ManualDb(db_path, db)
