from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from lego_manual_downloader.config import HttpConfig

try:
    _VERSION = version("lego-manual-downloader")
except PackageNotFoundError:
    _VERSION = "0+unknown"

USER_AGENT = f"lego-manual-downloader/{_VERSION}"


class TimeoutHttpAdapter(HTTPAdapter):
    def __init__(self, timeout: int, **kwargs: Any) -> None:
        self.timeout = timeout
        super().__init__(**kwargs)

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> requests.Response:
        return super().send(
            request,
            stream=stream,
            timeout=self.timeout if timeout is None else timeout,
            verify=verify,
            cert=cert,
            proxies=proxies,
        )


class ConnectionManager:
    def __init__(self, config: HttpConfig) -> None:
        self.config = config

    def session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        session.mount("http://", TimeoutHttpAdapter(timeout=self.config.timeout))
        session.mount("https://", TimeoutHttpAdapter(timeout=self.config.timeout))
        return session
