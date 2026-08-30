import pytest

from conftest import FakeManualOnly
from lego_manual_downloader.config import BricksetConfig, PeeronConfig
from lego_manual_downloader.providers import (
    InstructionsProvider,
    OwnedSetsProvider,
    ProviderConfigError,
    require_credentials,
)


class TestRequireCredentials:
    def test_an_absent_section_is_rejected(self) -> None:
        with pytest.raises(ProviderConfigError, match=r"\[brickset\] section"):
            require_credentials("brickset", None)

    @pytest.mark.parametrize(
        "username,password", [("", "p"), ("u", ""), ("", "")], ids=["user", "pass", "both"]
    )
    def test_blank_credentials_are_rejected(self, username: str, password: str) -> None:
        with pytest.raises(ProviderConfigError, match="username"):
            require_credentials("peeron", PeeronConfig(username=username, password=password))

    def test_a_complete_section_is_returned_unchanged(self) -> None:
        config = BricksetConfig(username="u", password="p")
        assert require_credentials("brickset", config) is config


def test_retirement_is_per_instance() -> None:
    """Two equal-but-distinct providers must not both be dropped."""
    first, second = FakeManualOnly(), FakeManualOnly()
    first.retire(RuntimeError("dead"))
    assert not first.is_available()
    assert second.is_available()


def test_brickset_serves_both_roles_and_peeron_only_manuals() -> None:
    from lego_manual_downloader.brickset import Brickset
    from lego_manual_downloader.peeron import Peeron

    assert issubclass(Brickset, OwnedSetsProvider)
    assert issubclass(Brickset, InstructionsProvider)
    assert issubclass(Peeron, InstructionsProvider)
    assert not issubclass(Peeron, OwnedSetsProvider)
