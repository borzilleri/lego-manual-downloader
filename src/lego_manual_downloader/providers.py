import logging
from abc import ABC, abstractmethod
from functools import cached_property
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

import requests

from lego_manual_downloader.config import Config, CredentialedConfig
from lego_manual_downloader.http import ConnectionManager
from lego_manual_downloader.lego import LegoSet

logger = logging.getLogger(__name__)

C = TypeVar("C", bound=CredentialedConfig)


class ProviderUnavailableError(Exception):
    """The provider is unavailable for future calls.

    This is typically the result of a failed login, or similar non-transient
    failure that indicates the provider is unusable.
    """


class ProviderConfigError(Exception):
    """The provider could not be instantiated with the current configuration."""


def require_credentials(section_name: str, section: C | None) -> C:
    """Return the named config section, rejecting one that is absent or has no credentials."""
    if section is None:
        raise ProviderConfigError(f"requires a [{section_name}] section in config")
    if not section.username or not section.password:
        raise ProviderConfigError(f"requires 'username' and 'password' in [{section_name}]")
    return section


class BaseProvider(ABC):
    """Behaviour shared by every provider implementation.

    `_available` is a class attribute rather than set in __init__ so that subclasses
    do not have to remember to call super().__init__(); retire() shadows it per instance.
    """

    _available: bool = True

    def is_available(self) -> bool:
        return self._available

    def retire(self, reason: Exception) -> None:
        """Mark this provider as unavailable for future calls."""
        logger.warning("Dropping %s for this run: %s", type(self).__name__, reason)
        self._available = False

    @staticmethod
    @abstractmethod
    def builder(config: Config, connection_manager: ConnectionManager) -> "ProviderBuilder":
        """Return the builder that validates config and constructs this provider."""
        ...


@runtime_checkable
class Provider(Protocol):
    """The lifecycle every provider exposes to a chain, regardless of its role."""

    def is_available(self) -> bool: ...
    def retire(self, reason: Exception) -> None: ...


@runtime_checkable
class InstructionsProvider(Provider, Protocol):
    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        """Download the manual for lego_set to output_path, returning whether it was found.

        Implementations must write via files.atomic_write so a failed or interrupted
        download never leaves a partial file at output_path.

        Under dry_run the availability check still runs, but nothing is written: the
        return value reports whether the manual could have been downloaded.
        """
        ...


@runtime_checkable
class OwnedSetsProvider(Provider, Protocol):
    def get_owned_sets(self) -> list[LegoSet]: ...


class ProviderBuilder(ABC):
    def __init__(self, config: Config, connection_manager: ConnectionManager) -> None:
        self.config = config
        self.connection_manager = connection_manager

    @abstractmethod
    def build(self) -> BaseProvider: ...


class AuthenticatedProvider(ABC):
    """Provides functionality for authenticators that need an authenticated session.

    Performs a login for a provider and returns a logged in session.

    Handles caching the login result, raising ProviderUnavailableError if the login
    fails, and returning the session for future calls, ensuring we only try
    to login once per provider instance.
    """

    label: str

    @abstractmethod
    def login(self) -> requests.Session:
        """Authenticate and return a session carrying the site's auth cookie."""

    @cached_property
    def _login_result(self) -> requests.Session | Exception:
        """cached_property stores return values but not exceptions, so a failure
        is returned rather than raised -- otherwise every set would retry the login.
        """
        try:
            return self.login()
        except Exception as e:
            logger.warning("%s: login failed: %s", self.label, e)
            return e

    @cached_property
    def session(self) -> requests.Session:
        if isinstance(self._login_result, Exception):
            raise ProviderUnavailableError(f"{self.label} login failed") from self._login_result
        return self._login_result
