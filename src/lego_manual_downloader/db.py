import json
from pathlib import Path

from lego_manual_downloader.config import DbConfig
from lego_manual_downloader.lego import LegoSet


class ManualDb:
    def __init__(self, download_path: Path, db_file: Path, db: dict[str, object]) -> None:
        self.download_path = download_path
        self.db_file = db_file
        self.db: dict[str, LegoSet] = {}
        for key, entry in db.items():
            lego_set = LegoSet.from_dict(entry)
            if lego_set is None:
                print(f"Warning: Ignoring unreadable database entry '{key}'.")
                continue
            self.db[lego_set.set_number] = lego_set

    def has_manual(self, lego_set: LegoSet) -> bool:
        entry = self.db.get(lego_set.set_number)
        if entry:
            return (self.download_path / entry.current_file_name).exists()
        if not (self.download_path / lego_set.file_name).exists():
            return False
        print(f"Warning: Manual for {lego_set} exists in download path but not in database.")
        self.add_manual(lego_set)
        return True

    def add_manual(self, lego_set: LegoSet) -> None:
        self.db[lego_set.set_number] = lego_set

    def needs_rename(self, lego_set: LegoSet) -> bool:
        entry = self.db.get(lego_set.set_number)
        return entry is not None and entry.current_file_name != lego_set.file_name

    def rename(self, lego_set: LegoSet, *, dry_run: bool = False) -> None:
        if not self.needs_rename(lego_set):
            return
        source = self.download_path / self.db[lego_set.set_number].current_file_name
        target = self.download_path / lego_set.file_name
        if target.exists():
            print(f"Warning: Cannot rename {source.name} to {target.name}, target already exists.")
            return
        print(f"Renaming manual for {lego_set} to {target.name}.")
        if dry_run:
            return
        try:
            source.rename(target)
        except OSError as e:
            print(f"Warning: Could not rename {source.name} to {target.name}: {e}")
            return
        self.add_manual(lego_set)

    def write_db(self) -> None:
        db_data = {k: v.to_dict() for k, v in self.db.items()}
        self.db_file.write_text(json.dumps(db_data, indent=4))

    @staticmethod
    def load(download_path: Path, config: DbConfig) -> "ManualDb":
        db_path = download_path / config.file
        db = json.loads(db_path.read_text()) if db_path.exists() else {}
        return ManualDb(download_path, db_path, db)
