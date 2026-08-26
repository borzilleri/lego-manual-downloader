import argparse
import os
from pathlib import Path

from lego_manual_downloader.config import Config, ConfigError
from lego_manual_downloader.db import ManualDb
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.provider_factory import ProviderFactory


def process_owned_sets(
    sets: list[LegoSet], download_path: Path, db: ManualDb, providers: ProviderFactory
) -> None:
    """Download a manual for each owned set that is not already in the database."""
    if not sets:
        print("No owned sets found.")
        return
    for lego_set in sets:
        if not providers.has_manual_providers:
            print("No usable manual providers left, stopping.")
            break
        description = f"{lego_set.number} - {lego_set.name} ({lego_set.year})"
        print(f"Processing {description}")
        if db.has_manual(lego_set.number):
            continue
        if providers.download_manual(lego_set, download_path / lego_set.file_name):
            db.add_manual(lego_set)
        else:
            print(f"Unable to download manual for {description}")
    db.write_db()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("download_dir", help="Path to directory to write manuals to.", type=Path)
    parser.add_argument(
        "--config", help="Path to config file.", default=None, required=False, type=Path
    )
    return parser


def validate_output_dir(path: Path) -> bool:
    if not path.exists():
        print(f"Error: Output directory '{path}' does not exist.")
        return False
    if not path.is_dir():
        print(f"Error: Output path '{path}' is not a directory.")
        return False
    if not os.access(path, os.W_OK):
        print(f"Error: Output directory '{path}' is not writable.")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not validate_output_dir(args.download_dir):
        return 1

    try:
        config = Config.load(args.config)
        providers = ProviderFactory.create(config)
    except ConfigError as e:
        print(f"Error: {e}")
        return 1

    try:
        db = ManualDb.load(args.download_dir, config.db)
    except Exception as e:
        print(f"Error loading database: {e}")
        return 1

    process_owned_sets(providers.get_owned_sets(), args.download_dir, db, providers)
    return 0
