from abc import ABC, abstractmethod
from functools import cached_property
from pathlib import Path
from typing import Protocol

import requests

from lego_manual_downloader.config import Config
from lego_manual_downloader.lego import LegoSet


class ProviderUnavailable(Exception):
    """The provider is unavailable for future calls.

    This is typically the result of a failed login, or similar non-transient
    failure that indicates the provider is unusable.
    """


class ManualProvider(ABC):
    @abstractmethod
    def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool: ...


class OwnedSetsProvider(ABC):
    @abstractmethod
    def get_owned_sets(self) -> list[LegoSet]: ...


class ProviderInit(Protocol):
    def __init__(self, config: Config) -> None: ...


class AuthenticatedProvider(ABC):
    """Perform a login for a provider and return a logged in session

    Handles caching the login result, raising ProviderUnavailable if the login
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
            print(f"{self.label}: login failed: {e}")
            return e

    @cached_property
    def session(self) -> requests.Session:
        if isinstance(self._login_result, Exception):
            raise ProviderUnavailable(f"{self.label} login failed") from self._login_result
        return self._login_result
