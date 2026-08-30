import argparse
import os
from pathlib import Path

from lego_manual_downloader import http
from lego_manual_downloader.config import Config
from lego_manual_downloader.db import JsonInstructionsDb
from lego_manual_downloader.downloader import download_instruction_manuals
from lego_manual_downloader.provider_builder import create_providers
from lego_manual_downloader.provider_chain import InstructionsProviderChain, SetsProviderChain


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
        connection_manager = http.ConnectionManager(config.http)
        providers = create_providers(config, connection_manager)
        db = JsonInstructionsDb.load(args.download_dir, config.db)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    sets_provider_chain = SetsProviderChain.create(
        list(config.providers.owned_sets_providers), providers
    )
    instructions_provider_chain = InstructionsProviderChain.create(
        list(config.providers.manual_providers), providers
    )

    success = download_instruction_manuals(
        args.download_dir,
        db,
        sets_provider_chain,
        instructions_provider_chain,
        dry_run=args.dry_run,
    )
    return 0 if success else 1
