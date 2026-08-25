import io
from pathlib import Path

import pytest
import responses
from PIL import Image

from conftest import PEERON_LOGIN, PEERON_SCANS, PEERON_THUMBS
from lego_manual_downloader.config import Config, PeeronConfig
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.peeron import Peeron, PeeronLoginError

SET_PAGE_URL = f"{PEERON_SCANS}10179/"


def png_bytes(color: str = "red", size: tuple[int, int] = (20, 20)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def scans_page(*thumb_urls: str) -> str:
    imgs = "".join(f'<img src="{url}" />' for url in thumb_urls)
    return f"<html><body>{imgs}</body></html>"


@pytest.fixture
def peeron(full_config: Config) -> Peeron:
    return Peeron(full_config)


class FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"") -> None:
        self.text = text
        self.content = content

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, responses_by_url: dict[str, FakeResponse]) -> None:
        self.responses_by_url = responses_by_url
        self.requested: list[str] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.requested.append(url)
        return self.responses_by_url[url]


class TestUrlComposition:
    def test_scan_page_url_has_no_double_slash(self, peeron: Peeron) -> None:
        assert peeron.get_url("10179") == SET_PAGE_URL
        assert "//" not in peeron.get_url("10179").removeprefix("http://")

    def test_scans_url_without_trailing_slash_still_joins(self) -> None:
        config = Config(
            peeron=PeeronConfig(
                username="u", password="p", scans_url="http://peeron.example/scans/"
            )
        )
        assert Peeron(config).get_url("1") == "http://peeron.example/scans/1/"

    def test_missing_section_raises(self) -> None:
        with pytest.raises(ValueError, match="peeron"):
            Peeron(Config())


class TestLogin:
    @responses.activate
    def test_successful_login_returns_a_session_with_the_cookie(self, peeron: Peeron) -> None:
        responses.post(PEERON_LOGIN, body="ok", headers={"Set-Cookie": "PeeronSID=abc; Path=/"})
        assert "PeeronSID" in peeron.session.cookies

    @responses.activate
    def test_login_posts_the_credentials(self, peeron: Peeron) -> None:
        responses.post(PEERON_LOGIN, body="ok", headers={"Set-Cookie": "PeeronSID=abc; Path=/"})
        _ = peeron.session
        posted = responses.calls[0].request.body or ""
        assert "user=user" in posted
        assert "pass=pass" in posted

    @responses.activate
    def test_absent_cookie_raises(self, peeron: Peeron) -> None:
        responses.post(PEERON_LOGIN, body="login failed")
        with pytest.raises(PeeronLoginError, match="rejected the credentials"):
            _ = peeron.session

    def test_blank_credentials_raise_before_any_request(self) -> None:
        config = Config(peeron=PeeronConfig(username="", password=""))
        with pytest.raises(ValueError, match="username"):
            _ = Peeron(config).session


class TestGetPageScanUrls:
    def test_rewrites_thumb_urls_to_scan_urls(self, peeron: Peeron) -> None:
        html = scans_page(f"{PEERON_THUMBS}/10179/1.png", f"{PEERON_THUMBS}/10179/2.png")
        peeron.session = FakeSession({SET_PAGE_URL: FakeResponse(text=html)})  # type: ignore[assignment]
        assert peeron.get_page_scan_urls("10179") == [
            f"{PEERON_THUMBS.replace('thumbs', 'scans')}/10179/1.png",
            f"{PEERON_THUMBS.replace('thumbs', 'scans')}/10179/2.png",
        ]

    def test_ignores_images_from_other_hosts(self, peeron: Peeron) -> None:
        html = scans_page("http://elsewhere.example/logo.png", f"{PEERON_THUMBS}/10179/1.png")
        peeron.session = FakeSession({SET_PAGE_URL: FakeResponse(text=html)})  # type: ignore[assignment]
        assert len(peeron.get_page_scan_urls("10179")) == 1

    def test_page_without_scans_yields_empty_list(self, peeron: Peeron) -> None:
        peeron.session = FakeSession({SET_PAGE_URL: FakeResponse(text=scans_page())})  # type: ignore[assignment]
        assert peeron.get_page_scan_urls("10179") == []


class TestDownloadPdf:
    def test_builds_a_multi_page_pdf_from_the_scans(self, peeron: Peeron, tmp_path: Path) -> None:
        urls = [f"{PEERON_SCANS}p{n}.png" for n in range(3)]
        peeron.session = FakeSession(  # type: ignore[assignment]
            {url: FakeResponse(content=png_bytes()) for url in urls}
        )
        output = tmp_path / "manual.pdf"
        peeron.download_pdf(urls, output)

        assert output.exists()
        assert output.read_bytes().startswith(b"%PDF")

    def test_single_scan_produces_a_pdf(self, peeron: Peeron, tmp_path: Path) -> None:
        url = f"{PEERON_SCANS}only.png"
        peeron.session = FakeSession({url: FakeResponse(content=png_bytes())})  # type: ignore[assignment]
        output = tmp_path / "manual.pdf"
        peeron.download_pdf([url], output)
        assert output.read_bytes().startswith(b"%PDF")


class TestDownloadManual:
    def test_returns_false_and_writes_nothing_when_no_scans(
        self, peeron: Peeron, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        peeron.session = FakeSession({SET_PAGE_URL: FakeResponse(text=scans_page())})  # type: ignore[assignment]
        output = tmp_path / "manual.pdf"
        assert not peeron.download_manual(LegoSet("10179", "Falcon", "2007"), output)
        assert not output.exists()
        assert "no images found" in capsys.readouterr().out

    def test_writes_a_pdf_and_reports_success(self, peeron: Peeron, tmp_path: Path) -> None:
        thumb = f"{PEERON_THUMBS}/10179/1.png"
        scan = thumb.replace("thumbs", "scans")
        peeron.session = FakeSession(  # type: ignore[assignment]
            {
                SET_PAGE_URL: FakeResponse(text=scans_page(thumb)),
                scan: FakeResponse(content=png_bytes()),
            }
        )
        output = tmp_path / "manual.pdf"
        assert peeron.download_manual(LegoSet("10179", "Falcon", "2007"), output)
        assert output.read_bytes().startswith(b"%PDF")
