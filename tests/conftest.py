from collections.abc import Iterator
from pathlib import Path

import pytest

from lego_manual_downloader import config as config_module
from lego_manual_downloader.config import BricksetConfig, Config, PeeronConfig
from lego_manual_downloader.lego import LegoSet

BRICKSET_BASE = "https://brickset.example"
PEERON_LOGIN = "http://peeron.example/cgi-bin/login"
PEERON_SCANS = "http://peeron.example/scans/"
PEERON_THUMBS = "http://thumbs.peeron.example/thumbs"


@pytest.fixture(autouse=True)
def isolate_default_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Never let a test read the developer's real ~/.config file."""
    monkeypatch.setattr(config_module, "_DEFAULT_CONFIG_PATH", tmp_path / "absent" / "config.toml")
    yield


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


@pytest.fixture
def full_config(brickset_config: BricksetConfig, peeron_config: PeeronConfig) -> Config:
    return Config(brickset=brickset_config, peeron=peeron_config)


@pytest.fixture
def lego_sets() -> list[LegoSet]:
    return [
        LegoSet("10179", "Millennium Falcon", "2007"),
        LegoSet("6080", "King's Castle", "1984"),
    ]


OWNED_SETS_CSV = """Number,Set name,Year
10179,Millennium Falcon,2007
6080,King's Castle,1984
"""

INSTRUCTIONS_CSV = """SetNumber,URL
10179,https://lego.example/10179.pdf
6080,
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
