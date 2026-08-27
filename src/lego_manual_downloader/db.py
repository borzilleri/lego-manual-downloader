import json
from pathlib import Path

from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.lego import LegoSet


class ManualDb:
    def __init__(self, download_path: Path, db_file: Path, db: dict[str, dict[str, str]]) -> None:
        self.download_path = download_path
        self.db_file = db_file
        self.db = db

    def has_manual(self, set_number: str) -> bool:
        entry = self.db.get(set_number)
        if not entry or not entry.get("file"):
            return False
        return (self.download_path / entry["file"]).exists()

    def add_manual(self, lego_set: LegoSet) -> None:
        self.db[lego_set.set_number] = {
            "number": lego_set.number,
            "variant": lego_set.variant,
            "name": lego_set.name,
            "year": lego_set.year,
            "file": lego_set.file_name,
        }

    def write_db(self) -> None:
        self.db_file.write_text(json.dumps(self.db, indent=4))

    @staticmethod
    def load(download_path: Path, config: DbConfig) -> "ManualDb":
        db_path = download_path / config.file
        db = json.loads(db_path.read_text()) if db_path.exists() else {}
        return ManualDb(download_path, db_path, db)
