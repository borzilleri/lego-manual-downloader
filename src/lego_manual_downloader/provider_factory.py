from pathlib import Path
from typing import Any, TypeVar

from lego_manual_downloader.brickset import Brickset
from lego_manual_downloader.config import Config, ConfigError
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.peeron import Peeron
from lego_manual_downloader.providers import ManualProvider, OwnedSetsProvider, ProviderInit

P = TypeVar("P")

_provider_registry: dict[str, type[ProviderInit]] = {
    "brickset": Brickset,
    "peeron": Peeron,
}


def _build_providers(config: Config, names: list[str]) -> dict[str, Any]:
    """Instantiate each named provider once, skipping any that cannot be configured."""
    instances: dict[str, Any] = {}
    for name in dict.fromkeys(names):
        provider_class = _provider_registry.get(name)
        if provider_class is None:
            print(f"Warning: Unknown provider '{name}' specified in config.")
            continue
        try:
            instances[name] = provider_class(config)
        except ValueError as e:
            print(f"Warning: Provider '{name}' is unavailable: {e}")
    return instances


def _select_providers(
    names: list[str], instances: dict[str, Any], role: type[P], label: str
) -> list[P]:
    """Pick the instances that implement `role`, warning about those that do not.

    `role` is only ever used for isinstance, never instantiated, so the abstract
    provider base classes are valid arguments here.
    """
    selected: list[P] = []
    for name in names:
        provider = instances.get(name)
        if provider is None:
            continue
        if isinstance(provider, role):
            selected.append(provider)
        else:
            print(f"Warning: Provider '{name}' is not a valid {label} provider.")
    return selected


class ProviderFactory:
    def __init__(
        self, sets_providers: list[OwnedSetsProvider], manual_providers: list[ManualProvider]
    ) -> None:
        self.sets_providers = sets_providers
        self.manual_providers = manual_providers

    def get_owned_sets(self) -> list[LegoSet]:
        for provider in self.sets_providers:
            try:
                owned_sets = provider.get_owned_sets()
                if owned_sets:
                    return owned_sets
            except Exception as e:
                print(f"Error fetching owned sets from {type(provider).__name__}: {e}")
        return []

    def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool:
        for provider in self.manual_providers:
            try:
                if provider.download_manual(lego_set, output_path):
                    return True
            except Exception as e:
                name = type(provider).__name__
                print(f"Error downloading manual for {lego_set.number} from {name}: {e}")
        return False

    @staticmethod
    def create(config: Config) -> "ProviderFactory":
        sets_provider_names = [n.lower() for n in config.providers.owned_sets_providers]
        manual_provider_names = [n.lower() for n in config.providers.manual_providers]

        instances = _build_providers(config, sets_provider_names + manual_provider_names)
        sets_providers = _select_providers(
            sets_provider_names,
            instances,
            OwnedSetsProvider,  # type: ignore[type-abstract]  # isinstance only
            "owned sets",
        )
        manual_providers = _select_providers(
            manual_provider_names,
            instances,
            ManualProvider,  # type: ignore[type-abstract]  # isinstance only
            "manual",
        )
        if not sets_providers:
            raise ConfigError("no usable owned sets providers configured")
        if not manual_providers:
            raise ConfigError("no usable manual providers configured")
        return ProviderFactory(sets_providers, manual_providers)
