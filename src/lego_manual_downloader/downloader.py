from pathlib import Path

from lego_manual_downloader.db import InstructionsDb, ManualStatus
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.provider_chain import InstructionsProviderChain, SetsProviderChain


class ProcessingException(Exception):
    """Raised when an error occurs while processing a set."""


def process_set(
    lego_set: LegoSet,
    download_path: Path,
    db: InstructionsDb,
    instructions_provider_chain: InstructionsProviderChain,
    dry_run: bool,
) -> None:
    print(f"Processing {lego_set}")
    status = db.check(lego_set, dry_run=dry_run)
    if status == ManualStatus.PRESENT:
        print(f"Manual for {lego_set} already exists, skipping.")
    elif status == ManualStatus.RENAMED:
        print(f"Manual for {lego_set} found, renamed to {lego_set.file_name}.")
    elif status == ManualStatus.MISSING:
        print(f"Manual for {lego_set} is missing, downloading.")
        output_path = download_path / lego_set.file_name
        if instructions_provider_chain.download_manual(lego_set, output_path, dry_run=dry_run):
            if not dry_run:
                db.add_manual(lego_set)
        else:
            raise ProcessingException(f"Unable to download manual for {lego_set}")


def download_instruction_manuals(
    download_path: Path,
    db: InstructionsDb,
    sets_provider_chain: SetsProviderChain,
    instructions_provider_chain: InstructionsProviderChain,
    dry_run: bool,
) -> bool:
    """Download instruction manuals for all owned sets."""
    if not sets_provider_chain.has_providers():
        print("No usable owned sets providers, stopping.")
        return False
    lego_sets = sets_provider_chain.get_owned_sets()
    success = True
    if not lego_sets:
        print("No owned sets found.")
        return success
    try:
        for lego_set in lego_sets:
            try:
                if not instructions_provider_chain.has_providers():
                    print("No usable manual providers left, stopping.")
                    success = False
                    break
                try:
                    process_set(
                        lego_set,
                        download_path,
                        db,
                        instructions_provider_chain,
                        dry_run=dry_run,
                    )
                except ProcessingException as e:
                    print(e)
                    success = False
            except Exception as e:
                print(f"Error processing owned sets: {e}")
                success = False
    finally:
        if not dry_run:
            db.write_db()
    return success
