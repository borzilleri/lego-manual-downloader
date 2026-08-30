from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Generic, TypeGuard, TypeVar

from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.providers import (
    BaseProvider,
    InstructionsProvider,
    OwnedSetsProvider,
    Provider,
    ProviderUnavailableError,
)

P = TypeVar("P")
PT = TypeVar("PT", bound=Provider)


def _select_providers(
    names: Sequence[str],
    instances: dict[str, BaseProvider],
    is_role: Callable[[BaseProvider], TypeGuard[P]],
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


class SetsProviderChain(BaseProviderChain[OwnedSetsProvider]):
    """Chain together multiple OwnedSetsProvider instances.

    Each provider is called in order until one returns a list of sets.
    If a provider raises ProviderUnavailableError, it is dropped from the chain for
    the rest of the run.
    """

    def get_owned_sets(self) -> list[LegoSet]:
        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                return provider.get_owned_sets()
            except ProviderUnavailableError as e:
                provider.retire(e)
            except Exception as e:
                print(f"Error fetching owned sets from {type(provider).__name__}: {e}")
        return []

    @staticmethod
    def _is_valid_provider(provider: BaseProvider) -> TypeGuard[OwnedSetsProvider]:
        return isinstance(provider, OwnedSetsProvider)

    @staticmethod
    def create(
        provider_names: list[str], provider_instances: dict[str, BaseProvider]
    ) -> "SetsProviderChain":
        """Create a SetsProviderChain with the configured provider instances."""
        providers = _select_providers(
            provider_names,
            provider_instances,
            SetsProviderChain._is_valid_provider,
            "owned sets",
        )
        return SetsProviderChain(providers)


class InstructionsProviderChain(BaseProviderChain[InstructionsProvider]):
    """Chain together multiple InstructionsProvider instances.

    Each provider is called in order until one returns True (indicating it downloaded an
    instruction manual succesfully). If a provider raises ProviderUnavailableError, it is
    dropped from the chain for the rest of the run.
    """

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                if provider.download_manual(lego_set, output_path, dry_run=dry_run):
                    return True
            except ProviderUnavailableError as e:
                provider.retire(e)
            except Exception as e:
                name = type(provider).__name__
                print(f"Error downloading manual for {lego_set.set_number} from {name}: {e}")
        return False

    @staticmethod
    def _is_valid_provider(provider: BaseProvider) -> TypeGuard[InstructionsProvider]:
        return isinstance(provider, InstructionsProvider)

    @staticmethod
    def create(
        provider_names: list[str], provider_instances: dict[str, BaseProvider]
    ) -> "InstructionsProviderChain":
        """Create an InstructionsProviderChain with the configured provider instances"""
        providers = _select_providers(
            provider_names,
            provider_instances,
            InstructionsProviderChain._is_valid_provider,
            "manual",
        )
        return InstructionsProviderChain(providers)
