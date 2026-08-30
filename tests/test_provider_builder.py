from pathlib import Path

import pytest

from conftest import FakeBoth, FakeManualOnly
from lego_manual_downloader import provider_builder
from lego_manual_downloader.config import BricksetConfig, Config, PeeronConfig, ProvidersConfig
from lego_manual_downloader.http import ConnectionManager
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.provider_builder import create_providers
from lego_manual_downloader.provider_chain import InstructionsProviderChain, SetsProviderChain
from lego_manual_downloader.providers import (
    BaseProvider,
    ProviderBuilder,
    ProviderConfigError,
)


class FakeUnconfigurable(BaseProvider):
    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        return True

    @staticmethod
    def builder(config: Config, connection_manager: ConnectionManager) -> ProviderBuilder:
        return UnconfigurableBuilder(config, connection_manager)


class UnconfigurableBuilder(ProviderBuilder):
    def build(self) -> BaseProvider:
        raise ProviderConfigError("requires a [fake] section in config")


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider_builder,
        "_provider_registry",
        {"both": FakeBoth, "manualonly": FakeManualOnly, "broken": FakeUnconfigurable},
    )


def _config_with(owned: tuple[str, ...], manual: tuple[str, ...]) -> Config:
    return Config(providers=ProvidersConfig(owned_sets_providers=owned, manual_providers=manual))


@pytest.mark.usefixtures("fake_registry")
class TestCreateProviders:
    def test_builds_every_named_provider(self, connection_manager: ConnectionManager) -> None:
        providers = create_providers(_config_with(("both",), ("both",)), connection_manager)
        assert list(providers) == ["both"]

    def test_provider_in_both_roles_is_instantiated_once(
        self, connection_manager: ConnectionManager
    ) -> None:
        """Both roles name it, but the registry builds it once and shares the instance."""
        create_providers(_config_with(("both",), ("both",)), connection_manager)
        assert FakeBoth.instances_created == 1

    def test_unknown_name_warns_and_is_skipped(
        self, connection_manager: ConnectionManager, capsys: pytest.CaptureFixture[str]
    ) -> None:
        create_providers(_config_with(("both",), ("both", "nosuch")), connection_manager)
        assert "Unknown provider 'nosuch'" in capsys.readouterr().out

    def test_unconfigurable_provider_is_skipped_not_fatal(
        self, connection_manager: ConnectionManager, capsys: pytest.CaptureFixture[str]
    ) -> None:
        providers = create_providers(
            _config_with(("both",), ("both", "broken")), connection_manager
        )
        assert "Failed to build provider 'broken'" in capsys.readouterr().out
        assert list(providers) == ["both"]

    def test_no_usable_provider_at_all_raises(self, connection_manager: ConnectionManager) -> None:
        with pytest.raises(ProviderConfigError, match="no usable providers"):
            create_providers(_config_with(("nosuch",), ("nosuch",)), connection_manager)

    def test_duplicate_names_build_one_instance(
        self, connection_manager: ConnectionManager
    ) -> None:
        create_providers(_config_with(("both", "both"), ("both",)), connection_manager)
        assert FakeBoth.instances_created == 1


def test_real_registry_maps_the_shipped_providers() -> None:
    from lego_manual_downloader.brickset import Brickset
    from lego_manual_downloader.peeron import Peeron

    assert provider_builder._provider_registry == {"brickset": Brickset, "peeron": Peeron}


def test_chains_can_be_built_from_the_real_providers(
    connection_manager: ConnectionManager,
) -> None:
    config = Config(
        brickset=BricksetConfig(username="u", password="p"),
        peeron=PeeronConfig(username="u", password="p"),
    )
    providers = create_providers(config, connection_manager)

    sets_chain = SetsProviderChain.create(list(config.providers.owned_sets_providers), providers)
    manual_chain = InstructionsProviderChain.create(
        list(config.providers.manual_providers), providers
    )

    assert [type(p).__name__ for p in sets_chain.providers] == ["Brickset"]
    assert [type(p).__name__ for p in manual_chain.providers] == ["Brickset", "Peeron"]


def test_a_provider_missing_its_section_is_skipped_with_a_warning(
    connection_manager: ConnectionManager, capsys: pytest.CaptureFixture[str]
) -> None:
    config = Config(brickset=BricksetConfig(username="u", password="p"))
    providers = create_providers(config, connection_manager)

    assert "Failed to build provider 'peeron'" in capsys.readouterr().out
    assert list(providers) == ["brickset"]
