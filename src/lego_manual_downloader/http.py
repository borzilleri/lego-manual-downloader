from importlib.metadata import PackageNotFoundError, version
import requests

try:
    _VERSION = version("lego-manual-downloader")
except PackageNotFoundError:
    _VERSION = "0+unknown"

USER_AGENT = f"lego-manual-downloader/{_VERSION}"


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session
