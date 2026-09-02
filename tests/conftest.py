import logging
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from lego_manual_downloader import config as config_module
from lego_manual_downloader.config import BricksetConfig, Config, HttpConfig, PeeronConfig
from lego_manual_downloader.http import ConnectionManager
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.log import PACKAGE_LOGGER
from lego_manual_downloader.providers import BaseProvider, ProviderBuilder

BRICKSET_BASE = "https://brickset.example"
PEERON_LOGIN = "http://peeron.example/cgi-bin/login"
PEERON_SCANS = "http://peeron.example/scans/"
PEERON_THUMBS = "http://thumbs.peeron.example/thumbs"


def records_at(
    caplog: pytest.LogCaptureFixture, level: int, fragment: str
) -> list[logging.LogRecord]:
    """Records logged at exactly `level` whose message contains `fragment`.

    Severity is part of the contract -- an error quietly demoted to debug would
    vanish from a default run -- so assertions name the level they expect.
    """
    return [r for r in caplog.records if level == r.levelno and fragment in r.getMessage()]


@pytest.fixture(autouse=True)
def isolate_default_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Never let a test read the developer's real ~/.config file."""
    monkeypatch.setattr(config_module, "_DEFAULT_CONFIG_PATH", tmp_path / "absent" / "config.toml")
    yield


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    """Let `caplog` see every record, and undo what `log.configure` did to the global logger."""
    logger = logging.getLogger(PACKAGE_LOGGER)
    logger.setLevel(logging.DEBUG)
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)


@pytest.fixture
def http_config() -> HttpConfig:
    return HttpConfig()


@pytest.fixture
def connection_manager(http_config: HttpConfig) -> ConnectionManager:
    return ConnectionManager(http_config)


@pytest.fixture
def brickset_config() -> BricksetConfig:
    return BricksetConfig(username="user", password="pass", base_url=BRICKSET_BASE)


@pytest.fixture
def peeron_config() -> PeeronConfig:
    return PeeronConfig(
        username="user",
        password="pass",
        login_url=PEERON_LOGIN,
        scans_url=PEERON_SCANS,
        thumbs_url=PEERON_THUMBS,
    )


OWNED_SETS_CSV = """Number,Variant,SetName,YearFrom
10179,1,Millennium Falcon,2007
6080,1,King's Castle,1984
"""

INSTRUCTIONS_CSV = """SetNumber,URL
10179-1,https://lego.example/10179.pdf
6080-1,
"""

LOGIN_FORM_HTML = """
<html><body>
  <form id="aspnetForm" method="post">
    <input type="hidden" name="__VIEWSTATE" value="abc123" />
    <input type="hidden" name="__EVENTVALIDATION" value="def456" />
    <input type="text" name="ctl00$mainContent$ctl11$Username" />
    <input type="password" name="ctl00$mainContent$ctl11$Password" />
    <input type="checkbox" name="ctl00$mainContent$ctl11$RememberMe" />
  </form>
</body></html>
"""

ONE = LegoSet("1", "1", "One", "2001")

SETS = [
    LegoSet("10179", "1", "Millennium Falcon", "2007"),
    LegoSet("6080", "1", "King's Castle", "1984"),
    LegoSet("9999", "1", "Unavailable", "2020"),
]

LEGACY_NAME = "10179 Falcon.pdf"


class UnbuiltProvider(BaseProvider):
    """A fake handed straight to a chain, so it is never built from config."""

    @staticmethod
    def builder(config: Config, connection_manager: ConnectionManager) -> ProviderBuilder:
        raise NotImplementedError


class StubProvider(UnbuiltProvider):
    """Serves every set except 9999, which no provider can supply."""

    def __init__(self, sets: list[LegoSet] | None = None) -> None:
        self.sets = list(SETS) if sets is None else sets

    def get_owned_sets(self) -> list[LegoSet]:
        return self.sets

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        if lego_set.number == "9999":
            return False
        if dry_run:
            return True
        output_path.write_bytes(b"%PDF-1.4 stub")
        return True


class _FakeBuilder(ProviderBuilder):
    """Mirrors the real builders; the fakes need no config of their own."""

    provider_class: ClassVar[type[BaseProvider]]

    def build(self) -> BaseProvider:
        return self.provider_class()


class FakeBoth(BaseProvider):
    """Stands in for Brickset: serves both roles."""

    instances_created = 0

    def __init__(self) -> None:
        self.downloads: list[str] = []
        self.dry_runs: list[bool] = []
        FakeBoth.instances_created += 1

    def get_owned_sets(self) -> list[LegoSet]:
        return [ONE]

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        self.downloads.append(lego_set.number)
        self.dry_runs.append(dry_run)
        return True

    @staticmethod
    def builder(config: Config, connection_manager: ConnectionManager) -> ProviderBuilder:
        return BothBuilder(config, connection_manager)


class BothBuilder(_FakeBuilder):
    provider_class = FakeBoth


@pytest.fixture(autouse=True)
def reset_instance_counter() -> None:
    """`instances_created` is class state shared by every module that builds a FakeBoth,
    so it is zeroed for all of them rather than by whichever fixture happens to run.
    """
    FakeBoth.instances_created = 0


class FakeManualOnly(BaseProvider):
    """Stands in for Peeron: serves manuals only."""

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        return False

    @staticmethod
    def builder(config: Config, connection_manager: ConnectionManager) -> ProviderBuilder:
        return ManualOnlyBuilder(config, connection_manager)


class ManualOnlyBuilder(_FakeBuilder):
    provider_class = FakeManualOnly


class SetsOnlyProvider(UnbuiltProvider):
    """Fills the owned-sets role and nothing else, so a role mix-up is visible."""

    def get_owned_sets(self) -> list[LegoSet]:
        return SETS[:1]


class ManualOnlyWriter(UnbuiltProvider):
    """Fills the manual role and nothing else, writing a file so a run can succeed."""

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        if not dry_run:
            output_path.write_bytes(b"%PDF-1.4 stub")
        return True
