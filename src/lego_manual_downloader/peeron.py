import io
import logging
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import bs4
import requests
from PIL import Image

from lego_manual_downloader.config import Config, PeeronConfig
from lego_manual_downloader.files import atomic_write
from lego_manual_downloader.http import ConnectionManager
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.providers import (
    AuthenticatedProvider,
    BaseProvider,
    InstructionsProvider,
    ProviderBuilder,
    require_credentials,
)

logger = logging.getLogger(__name__)

_AUTH_COOKIE = "PeeronSID"


class PeeronLoginError(Exception):
    pass


class Peeron(AuthenticatedProvider, BaseProvider, InstructionsProvider):
    label = "peeron"

    def __init__(self, config: PeeronConfig, connection_manager: ConnectionManager) -> None:
        self.config: PeeronConfig = config
        self.connection_manager = connection_manager

    def login(self) -> requests.Session:
        """Login to peeron.com and return a session with the auth cookie.

        The CGI login form carries no CSRF or state fields, so the credentials are
        posted directly without fetching the form first.
        """
        session = self.connection_manager.session()

        login_url = self.config.login_url
        url_parts = urlsplit(login_url)
        response = session.post(
            login_url,
            data={
                "user": self.config.username,
                "pass": self.config.password,
                "openid_url": "",
                "login": "Login",
            },
            headers={
                "Origin": f"{url_parts.scheme}://{url_parts.netloc}",
                "Referer": login_url,
            },
        )
        response.raise_for_status()

        if _AUTH_COOKIE not in session.cookies:
            raise PeeronLoginError("Peeron rejected the credentials")
        return session

    def get_url(self, set_number: str) -> str:
        return urljoin(self.config.scans_url, f"{set_number}/")

    def get_page_scan_urls(self, set_number: str) -> list[str]:
        r = self.session.get(self.get_url(set_number))
        r.raise_for_status()
        html = bs4.BeautifulSoup(r.text, "html5lib")
        imgs = html.select(f"img[src^='{self.config.thumbs_url}']")
        return [str(s.get("src")).replace("thumbs", "scans") for s in imgs]

    def download_image(self, url: str) -> Image.Image:
        r = self.session.get(url)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content))

    def download_pdf(self, scan_urls: list[str], output_path: Path) -> None:
        cover_img = self.download_image(scan_urls[0])
        with atomic_write(output_path) as f:
            # PIL titles the PDF after the file it is handed, which is now a
            # temp file, so the real name is passed explicitly.
            cover_img.save(
                f,
                "PDF",
                resolution=100.0,
                save_all=True,
                append_images=(self.download_image(i) for i in scan_urls[1:]),
                title=output_path.stem,
            )

    def download_manual(self, lego_set: LegoSet, output_path: Path, dry_run: bool) -> bool:
        """Download the instruction manual for a given set number to the specified output path."""
        # Peeron indexes by the base set number, not including variant.
        page_scan_urls = self.get_page_scan_urls(lego_set.number)
        if not page_scan_urls:
            logger.warning("%s: no images found for %s", self.label, lego_set.set_number)
            return False
        if dry_run:
            logger.info(
                "%s: dry run: would download manual for %s", self.label, lego_set.set_number
            )
            return True
        self.download_pdf(page_scan_urls, output_path)
        return True

    @staticmethod
    def builder(config: Config, connection_manager: ConnectionManager) -> "PeeronBuilder":
        return PeeronBuilder(config, connection_manager)


class PeeronBuilder(ProviderBuilder):
    def build(self) -> Peeron:
        config = require_credentials("peeron", self.config.peeron)
        return Peeron(config, self.connection_manager)
