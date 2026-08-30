import argparse
import os
from pathlib import Path

from lego_manual_downloader import http
from lego_manual_downloader.config import Config, ConfigError
from lego_manual_downloader.db import ManualDb, ManualStatus
from lego_manual_downloader.provider_factory import ProviderManager, create_provider_manager


def process_owned_sets(
    download_path: Path,
    provider_manager: ProviderManager,
    db: ManualDb,
    dry_run: bool,
) -> bool:
    """Download a manual for each owned set that is not already in the database."""
    lego_sets = provider_manager.sets_provider_chain.get_owned_sets()
    success = True
    if not lego_sets:
        print("No owned sets found.")
        return success
    try:
        manual_providers = provider_manager.manual_provider_chain
        for lego_set in lego_sets:
            try:
                if not manual_providers.has_providers():
                    print("No usable manual providers left, stopping.")
                    success = False
                    break
                print(f"Processing {lego_set}")
                status = db.check(lego_set, dry_run=dry_run)
                if status == ManualStatus.PRESENT:
                    print(f"Manual for {lego_set} already exists, skipping.")
                elif status == ManualStatus.RENAMED:
                    print(f"Manual for {lego_set} found, renamed to {lego_set.file_name}.")
                elif status == ManualStatus.MISSING:
                    print(f"Manual for {lego_set} is missing, downloading.")
                    output_path = download_path / lego_set.file_name
                    if manual_providers.download_manual(lego_set, output_path, dry_run=dry_run):
                        if not dry_run:
                            db.add_manual(lego_set)
                    else:
                        print(f"Unable to download manual for {lego_set}")
                        success = False
            except Exception as e:
                print(f"Error processing owned sets: {e}")
                success = False
    finally:
        if not dry_run:
            db.write_db()
    return success


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("download_dir", help="Path to directory to write manuals to.", type=Path)
    parser.add_argument(
        "--config", help="Path to config file.", default=None, required=False, type=Path
    )
    parser.add_argument(
        "--dry-run",
        help="Report what would be downloaded without writing manuals or the database.",
        action="store_true",
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
        provider_manager = create_provider_manager(config, http.SessionBuilder(config.http))
    except ConfigError as e:
        print(f"Error: {e}")
        return 1

    try:
        db = ManualDb.load(args.download_dir, config.db)
    except Exception as e:
        print(f"Error loading database: {e}")
        return 1

    success = process_owned_sets(
        args.download_dir,
        provider_manager,
        db,
        dry_run=args.dry_run,
    )
    return 0 if success else 1
