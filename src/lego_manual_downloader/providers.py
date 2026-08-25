from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from lego_manual_downloader.config import Config
from lego_manual_downloader.lego import LegoSet


class ManualProvider(ABC):
    @abstractmethod
    def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool: ...


class OwnedSetsProvider(ABC):
    @abstractmethod
    def get_owned_sets(self) -> list[LegoSet]: ...


class ProviderInit(Protocol):
    def __init__(self, config: Config) -> None: ...
