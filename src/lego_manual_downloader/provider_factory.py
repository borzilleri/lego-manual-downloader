from collections.abc import Callable, Sequence
from functools import cached_property
from pathlib import Path
from typing import Generic, TypeGuard, TypeVar

from lego_manual_downloader.brickset import Brickset
from lego_manual_downloader.config import Config, ConfigError, ProvidersConfig
from lego_manual_downloader.http import SessionBuilder
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.peeron import Peeron
from lego_manual_downloader.providers import (
    ManualProvider,
    OwnedSetsProvider,
    Provider,
    ProviderBase,
    ProviderConfigError,
    ProviderUnavailable,
)

P = TypeVar("P")
PT = TypeVar("PT", bound=Provider)

_provider_registry: dict[str, type[ProviderBase]] = {
    "brickset": Brickset,
    "peeron": Peeron,
}


def _build_providers(
    config: Config, names: list[str], session_builder: SessionBuilder
) -> dict[str, ProviderBase]:
    """Instantiate each named provider once, skipping any that cannot be configured."""
    instances: dict[str, ProviderBase] = {}
    for name in names:
        provider_class = _provider_registry.get(name)
        if provider_class is None:
            print(f"Warning: Unknown provider '{name}' specified in config.")
            continue
        try:
            instances[name] = provider_class.builder(config, session_builder).build()
        except ProviderConfigError as e:
            print(f"Warning: Provider '{name}' is unavailable: {e}")
    return instances


def _is_owned_sets(provider: ProviderBase) -> TypeGuard[OwnedSetsProvider]:
    return isinstance(provider, OwnedSetsProvider)


def _is_manual(provider: ProviderBase) -> TypeGuard[ManualProvider]:
    return isinstance(provider, ManualProvider)


def _select_providers(
    names: Sequence[str],
    instances: dict[str, ProviderBase],
    is_role: Callable[[ProviderBase], TypeGuard[P]],
    label: str,
) -> list[P]:
    """Pick the instances that fill `role`, warning about those that do not.

    The role is passed as a predicate rather than a class: the roles are protocols,
    and `type[SomeProtocol]` would assert instantiability we never want.
    """
    selected: list[P] = []
    for name in names:
        provider = instances.get(name)
        if provider is None:
            continue
        if is_role(provider):
            selected.append(provider)
        else:
            print(f"Warning: Provider '{name}' is not a valid {label} provider.")
    return selected


class BaseProviderChain(Generic[PT]):
    """Holds an ordered list of providers filling one role, and tracks their availability."""

    def __init__(self, providers: list[PT]) -> None:
        self.providers = providers

    def has_providers(self) -> bool:
        """Return True if at least one provider in the chain is available."""
        return any(provider.is_available() for provider in self.providers)


class SetProviderChain(BaseProviderChain[OwnedSetsProvider]):
    """Chain together multiple OwnedSetsProvider instances.

    Each provider is called in order until one returns a list of sets.
    If a provider raises ProviderUnavailable, it is dropped from the chain for the
    rest of the run.
    """

    def get_owned_sets(self) -> list[LegoSet]:
        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                return provider.get_owned_sets()
            except ProviderUnavailable as e:
                provider.retire(e)
            except Exception as e:
                print(f"Error fetching owned sets from {type(provider).__name__}: {e}")
        return []


class ManualProviderChain(BaseProviderChain[ManualProvider]):
    """Chain together multiple ManualProvider instances.

    Each provider is called in order until one returns True (indicating it downloaded an
    instruction manual succesfully). If a provider raises ProviderUnavailable, it is dropped from
    the chain for the rest of the run.
    """

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                if provider.download_manual(lego_set, output_path, dry_run=dry_run):
                    return True
            except ProviderUnavailable as e:
                provider.retire(e)
            except Exception as e:
                name = type(provider).__name__
                print(f"Error downloading manual for {lego_set.set_number} from {name}: {e}")
        return False


class ProviderManager:
    def __init__(self, providers: dict[str, ProviderBase], config: ProvidersConfig) -> None:
        self.providers = providers
        self.config = config

    @cached_property
    def sets_provider_chain(self) -> SetProviderChain:
        providers = _select_providers(
            self.config.owned_sets_providers,
            self.providers,
            _is_owned_sets,
            "owned sets",
        )
        return SetProviderChain(providers)

    @cached_property
    def manual_provider_chain(self) -> ManualProviderChain:
        providers = _select_providers(
            self.config.manual_providers,
            self.providers,
            _is_manual,
            "manual",
        )
        return ManualProviderChain(providers)


def create_provider_manager(config: Config, session_builder: SessionBuilder) -> ProviderManager:
    instances = _build_providers(config, config.providers.all_providers, session_builder)
    if not instances:
        raise ConfigError("no usable providers configured")
    return ProviderManager(instances, config.providers)
