import argparse
import logging
import os
from pathlib import Path

from lego_manual_downloader import http, log
from lego_manual_downloader.config import Config
from lego_manual_downloader.db import JsonInstructionsDb
from lego_manual_downloader.downloader import download_instruction_manuals
from lego_manual_downloader.provider_builder import create_providers
from lego_manual_downloader.provider_chain import InstructionsProviderChain, SetsProviderChain

logger = logging.getLogger(__name__)


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
    parser.add_argument(
        "--log-level",
        help=f"How much to report. Defaults to '{log.DEFAULT_LEVEL}'.",
        choices=log.LEVELS,
        default=None,
    )
    parser.add_argument(
        "--log-file", help="Also write output to this file.", default=None, type=Path
    )
    parser.add_argument("--no-color", help="Never colorize output.", action="store_true")
    return parser


def validate_output_dir(path: Path) -> bool:
    if not path.exists():
        logger.error("Output directory '%s' does not exist.", path)
        return False
    if not path.is_dir():
        logger.error("Output path '%s' is not a directory.", path)
        return False
    if not os.access(path, os.W_OK):
        logger.error("Output directory '%s' is not writable.", path)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    color = False if args.no_color else None

    try:
        config = Config.load(args.config)
    except Exception as e:
        log.configure(
            level=args.log_level or log.DEFAULT_LEVEL, log_file=args.log_file, color=color
        )
        logger.error("%s", e)
        return 1

    log.configure(
        level=args.log_level or config.logging.level,
        log_file=args.log_file or config.logging.path,
        color=color,
    )

    if not validate_output_dir(args.download_dir):
        return 1

    try:
        connection_manager = http.ConnectionManager(config.http)
        providers = create_providers(config, connection_manager)
        db = JsonInstructionsDb.load(args.download_dir, config.db)
    except Exception as e:
        logger.error("%s", e)
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
