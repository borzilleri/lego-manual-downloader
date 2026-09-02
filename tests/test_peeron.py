import io
import logging
from pathlib import Path

import pytest
import requests
import responses
from PIL import Image

from conftest import PEERON_LOGIN, PEERON_SCANS, PEERON_THUMBS, records_at
from lego_manual_downloader.config import Config, PeeronConfig
from lego_manual_downloader.http import ConnectionManager
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.peeron import Peeron, PeeronBuilder, PeeronLoginError
from lego_manual_downloader.providers import ProviderConfigError, ProviderUnavailableError

SET_PAGE_URL = f"{PEERON_SCANS}10179/"


def png_bytes(color: str = "red", size: tuple[int, int] = (20, 20)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def scans_page(*thumb_urls: str) -> str:
    imgs = "".join(f'<img src="{url}" />' for url in thumb_urls)
    return f"<html><body>{imgs}</body></html>"


def _body(raw: object) -> str:
    """responses records a request body as bytes or str depending on the call."""
    if isinstance(raw, bytes):
        return raw.decode()
    return raw if isinstance(raw, str) else ""


@pytest.fixture
def peeron(peeron_config: PeeronConfig, connection_manager: ConnectionManager) -> Peeron:
    return Peeron(peeron_config, connection_manager)


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

    def test_scans_url_without_trailing_slash_still_joins(
        self, connection_manager: ConnectionManager
    ) -> None:
        config = PeeronConfig(username="u", password="p", scans_url="http://peeron.example/scans/")
        assert Peeron(config, connection_manager).get_url("1") == "http://peeron.example/scans/1/"

    def test_missing_section_is_rejected_by_the_builder(
        self, connection_manager: ConnectionManager
    ) -> None:
        with pytest.raises(ProviderConfigError, match="peeron"):
            PeeronBuilder(Config(), connection_manager).build()


class TestLogin:
    @responses.activate
    def test_successful_login_returns_a_session_with_the_cookie(self, peeron: Peeron) -> None:
        responses.post(PEERON_LOGIN, body="ok", headers={"Set-Cookie": "PeeronSID=abc; Path=/"})
        assert "PeeronSID" in peeron.session.cookies

    @responses.activate
    def test_login_posts_the_credentials(self, peeron: Peeron) -> None:
        responses.post(PEERON_LOGIN, body="ok", headers={"Set-Cookie": "PeeronSID=abc; Path=/"})
        _ = peeron.session
        posted = _body(responses.calls[0].request.body)
        assert "user=user" in posted
        assert "pass=pass" in posted

    @responses.activate
    def test_absent_cookie_raises(self, peeron: Peeron) -> None:
        responses.post(PEERON_LOGIN, body="login failed")
        with pytest.raises(ProviderUnavailableError, match="peeron login failed") as excinfo:
            _ = peeron.session
        assert "rejected the credentials" in str(excinfo.value.__cause__)

    def test_blank_credentials_are_rejected_by_the_builder(
        self, connection_manager: ConnectionManager
    ) -> None:
        config = Config(peeron=PeeronConfig(username="", password=""))
        with pytest.raises(ProviderConfigError, match="username"):
            PeeronBuilder(config, connection_manager).build()


class TestGetPageScanUrls:
    def test_rewrites_thumb_urls_to_scan_urls(self, peeron: Peeron) -> None:
        html = scans_page(f"{PEERON_THUMBS}/10179/1.png", f"{PEERON_THUMBS}/10179/2.png")
        peeron._login_result = FakeSession({SET_PAGE_URL: FakeResponse(text=html)})  # type: ignore[assignment]
        assert peeron.get_page_scan_urls("10179") == [
            f"{PEERON_THUMBS.replace('thumbs', 'scans')}/10179/1.png",
            f"{PEERON_THUMBS.replace('thumbs', 'scans')}/10179/2.png",
        ]

    def test_ignores_images_from_other_hosts(self, peeron: Peeron) -> None:
        html = scans_page("http://elsewhere.example/logo.png", f"{PEERON_THUMBS}/10179/1.png")
        peeron._login_result = FakeSession({SET_PAGE_URL: FakeResponse(text=html)})  # type: ignore[assignment]
        assert len(peeron.get_page_scan_urls("10179")) == 1

    def test_page_without_scans_yields_empty_list(self, peeron: Peeron) -> None:
        peeron._login_result = FakeSession({SET_PAGE_URL: FakeResponse(text=scans_page())})  # type: ignore[assignment]
        assert peeron.get_page_scan_urls("10179") == []


class TestDownloadPdf:
    def test_builds_a_multi_page_pdf_from_the_scans(self, peeron: Peeron, tmp_path: Path) -> None:
        urls = [f"{PEERON_SCANS}p{n}.png" for n in range(3)]
        peeron._login_result = FakeSession(  # type: ignore[assignment]
            {url: FakeResponse(content=png_bytes()) for url in urls}
        )
        output = tmp_path / "manual.pdf"
        peeron.download_pdf(urls, output)

        assert output.exists()
        assert output.read_bytes().startswith(b"%PDF")

    def test_a_scan_failing_mid_pdf_leaves_no_partial_file(
        self, peeron: Peeron, tmp_path: Path
    ) -> None:
        """Pages are fetched lazily by PIL during the save, so a later page can fail
        after the PDF has already been partly written."""
        urls = [f"{PEERON_SCANS}p{n}.png" for n in range(3)]

        class DroppedSession(FakeSession):
            def get(self, url: str, **kwargs: object) -> FakeResponse:
                if url == urls[1]:
                    raise requests.ConnectionError("dropped mid-manual")
                return super().get(url, **kwargs)

        peeron._login_result = DroppedSession(  # type: ignore[assignment]
            {url: FakeResponse(content=png_bytes()) for url in urls}
        )
        output = tmp_path / "manual.pdf"
        with pytest.raises(requests.ConnectionError):
            peeron.download_pdf(urls, output)

        assert not list(tmp_path.iterdir())

    def test_single_scan_produces_a_pdf(self, peeron: Peeron, tmp_path: Path) -> None:
        url = f"{PEERON_SCANS}only.png"
        peeron._login_result = FakeSession({url: FakeResponse(content=png_bytes())})  # type: ignore[assignment]
        output = tmp_path / "manual.pdf"
        peeron.download_pdf([url], output)
        assert output.read_bytes().startswith(b"%PDF")

    def test_pdf_is_titled_after_the_destination_not_the_temp_file(
        self, peeron: Peeron, tmp_path: Path
    ) -> None:
        url = f"{PEERON_SCANS}only.png"
        peeron._login_result = FakeSession({url: FakeResponse(content=png_bytes())})  # type: ignore[assignment]
        output = tmp_path / "10179 - Falcon.pdf"
        peeron.download_pdf([url], output)
        assert "10179 - Falcon".encode("utf-16-be") in output.read_bytes()


class TestDownloadManual:
    def test_returns_false_and_writes_nothing_when_no_scans(
        self, peeron: Peeron, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        peeron._login_result = FakeSession({SET_PAGE_URL: FakeResponse(text=scans_page())})  # type: ignore[assignment]
        output = tmp_path / "manual.pdf"
        assert not peeron.download_manual(
            LegoSet("10179", "1", "Falcon", "2007"), output, dry_run=False
        )
        assert not output.exists()
        assert records_at(caplog, logging.WARNING, "no images found")

    def test_writes_a_pdf_and_reports_success(self, peeron: Peeron, tmp_path: Path) -> None:
        thumb = f"{PEERON_THUMBS}/10179/1.png"
        scan = thumb.replace("thumbs", "scans")
        peeron._login_result = FakeSession(  # type: ignore[assignment]
            {
                SET_PAGE_URL: FakeResponse(text=scans_page(thumb)),
                scan: FakeResponse(content=png_bytes()),
            }
        )
        output = tmp_path / "manual.pdf"
        assert peeron.download_manual(
            LegoSet("10179", "1", "Falcon", "2007"), output, dry_run=False
        )
        assert output.read_bytes().startswith(b"%PDF")


class TestDownloadManualDryRun:
    def test_reports_the_manual_without_fetching_scans_or_writing(
        self, peeron: Peeron, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        thumb = f"{PEERON_THUMBS}/10179/1.png"
        session = FakeSession({SET_PAGE_URL: FakeResponse(text=scans_page(thumb))})
        peeron._login_result = session  # type: ignore[assignment]
        output = tmp_path / "manual.pdf"

        assert peeron.download_manual(LegoSet("10179", "1", "Falcon", "2007"), output, dry_run=True)
        assert not output.exists()
        assert session.requested == [SET_PAGE_URL]
        assert records_at(
            caplog, logging.INFO, "peeron: dry run: would download manual for 10179-1"
        )

    def test_returns_false_when_no_scans(self, peeron: Peeron, tmp_path: Path) -> None:
        peeron._login_result = FakeSession({SET_PAGE_URL: FakeResponse(text=scans_page())})  # type: ignore[assignment]
        output = tmp_path / "manual.pdf"
        assert not peeron.download_manual(
            LegoSet("10179", "1", "Falcon", "2007"), output, dry_run=True
        )
        assert not output.exists()


class TestLoginIsAttemptedOnce:
    """Mirror of the Brickset guards: a failed login must not retry per set."""

    @staticmethod
    def counting_login(peeron: Peeron, outcome: object) -> list[int]:
        calls: list[int] = []

        def fake_login() -> requests.Session:
            calls.append(1)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome  # type: ignore[return-value]

        peeron.login = fake_login  # type: ignore[method-assign]
        return calls

    @pytest.mark.parametrize(
        "failure",
        [
            PeeronLoginError("rejected"),
            requests.HTTPError("500 from peeron"),
            requests.ConnectionError("offline"),
            requests.Timeout("slow"),
        ],
        ids=["login-error", "http-error", "connection-error", "timeout"],
    )
    def test_failed_login_is_attempted_once(self, peeron: Peeron, failure: Exception) -> None:
        calls = self.counting_login(peeron, failure)
        for _ in range(5):
            with pytest.raises(ProviderUnavailableError):
                _ = peeron.session
        assert len(calls) == 1

    def test_successful_login_is_attempted_once(self, peeron: Peeron) -> None:
        calls = self.counting_login(peeron, requests.Session())
        for _ in range(5):
            assert isinstance(peeron.session, requests.Session)
        assert len(calls) == 1

    def test_failure_is_reported_once_not_per_access(
        self, peeron: Peeron, caplog: pytest.LogCaptureFixture
    ) -> None:
        self.counting_login(peeron, requests.ConnectionError("offline"))
        for _ in range(5):
            with pytest.raises(ProviderUnavailableError):
                _ = peeron.session
        assert len(records_at(caplog, logging.WARNING, "peeron: login failed")) == 1

    def test_download_manual_raises_unavailable_without_retrying(
        self, peeron: Peeron, tmp_path: Path
    ) -> None:
        calls = self.counting_login(peeron, requests.ConnectionError("offline"))
        for n in range(5):
            with pytest.raises(ProviderUnavailableError):
                peeron.download_manual(
                    LegoSet(str(n), "1", "Set", "2001"), tmp_path / "x.pdf", dry_run=False
                )
        assert len(calls) == 1
