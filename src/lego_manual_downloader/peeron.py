import io
from functools import cached_property
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import bs4
import requests
from PIL import Image

from lego_manual_downloader.config import Config, PeeronConfig
from lego_manual_downloader.http import new_session
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.providers import ManualProvider

_AUTH_COOKIE = "PeeronSID"


class PeeronLoginError(Exception):
    pass


class Peeron(ManualProvider):
    def __init__(self, config: Config) -> None:
        if config.peeron is None:
            raise ValueError("Peeron provider requires 'peeron' section in config")
        self.config: PeeronConfig = config.peeron

    @cached_property
    def session(self) -> requests.Session:
        """Return a requests.Session object with the Peeron auth cookie set."""
        if not self.config.username or not self.config.password:
            raise ValueError("Peeron provider requires 'username' and 'password' in config")
        return self.login(self.config.login_url, self.config.username, self.config.password)

    def login(self, login_url: str, username: str, password: str) -> requests.Session:
        """Login to peeron.com and return a session with the auth cookie.

        The CGI login form carries no CSRF or state fields, so the credentials are
        posted directly without fetching the form first.
        """
        session = new_session()

        url_parts = urlsplit(login_url)
        response = session.post(
            login_url,
            data={
                "user": username,
                "pass": password,
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
        cover_img.save(
            output_path,
            "PDF",
            resolution=100.0,
            save_all=True,
            append_images=(self.download_image(i) for i in scan_urls[1:]),
        )

    def download_manual(self, lego_set: LegoSet, output_path: Path) -> bool:
        """Download the instruction manual for a given set number to the specified output path."""
        page_scan_urls = self.get_page_scan_urls(lego_set.number)
        if not page_scan_urls:
            print(f"peeron: no images found for {lego_set.number}")
            return False
        self.download_pdf(page_scan_urls, output_path)
        return True
