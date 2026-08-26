from collections.abc import Iterable, Iterator
from pathlib import Path

import bs4
import pytest
import requests
import responses

from conftest import BRICKSET_BASE, INSTRUCTIONS_CSV, LOGIN_FORM_HTML, OWNED_SETS_CSV
from lego_manual_downloader.brickset import (
    Brickset,
    BricksetLoginError,
    _build_login_payload,
    _find_error_message,
)
from lego_manual_downloader.config import BricksetConfig, Config
from lego_manual_downloader.lego import LegoSet
from lego_manual_downloader.providers import ProviderUnavailable

LOGIN_URL = f"{BRICKSET_BASE}/login"
OWNED_URL = f"{BRICKSET_BASE}/exportscripts/sets/owned/"
INSTRUCTIONS_URL = f"{BRICKSET_BASE}/exportscripts/instructions"


def _body(raw: object) -> str:
    """responses records a request body as bytes or str depending on the call."""
    if isinstance(raw, bytes):
        return raw.decode()
    return raw if isinstance(raw, str) else ""


@pytest.fixture
def brickset(full_config: Config) -> Brickset:
    return Brickset(full_config)


class FakeResponse:
    def __init__(self, text: str = "", content: bytes = b"") -> None:
        self.text = text
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 8192) -> Iterable[bytes]:
        return [self.content[i : i + chunk_size] for i in range(0, len(self.content), chunk_size)]

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class DroppedResponse(FakeResponse):
    """Streams one chunk, then loses the connection."""

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        yield b"%PDF-1.4 par"
        raise requests.ConnectionError("dropped mid-download")


class FakeSession:
    """Injected over the cached_property so provider methods skip the network."""

    def __init__(self, responses_by_url: dict[str, FakeResponse]) -> None:
        self.responses_by_url = responses_by_url
        self.requested: list[str] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.requested.append(url)
        return self.responses_by_url[url]


class TestUrlComposition:
    def test_urls_are_joined_to_the_base(self, brickset: Brickset) -> None:
        assert brickset.owned_sets_url == OWNED_URL
        assert brickset.instructions_url == INSTRUCTIONS_URL

    def test_trailing_slash_on_base_url_does_not_double(self) -> None:
        config = Config(
            brickset=BricksetConfig(username="u", password="p", base_url=f"{BRICKSET_BASE}/")
        )
        assert Brickset(config).owned_sets_url == OWNED_URL

    def test_missing_section_raises(self) -> None:
        with pytest.raises(ValueError, match="brickset"):
            Brickset(Config())


class TestLoginPayload:
    def test_preserves_hidden_state_and_fills_credentials(self) -> None:
        form = bs4.BeautifulSoup(LOGIN_FORM_HTML, "html5lib").find("form")
        assert isinstance(form, bs4.Tag)
        payload = _build_login_payload(form, "alice", "s3cret")

        assert payload["__VIEWSTATE"] == "abc123"
        assert payload["__EVENTVALIDATION"] == "def456"
        assert payload["ctl00$mainContent$ctl11$Username"] == "alice"
        assert payload["ctl00$mainContent$ctl11$Password"] == "s3cret"
        assert payload["ctl00$mainContent$ctl11$RememberMe"] == "on"

    def test_raises_when_the_form_has_no_password_field(self) -> None:
        html = '<form><input type="text" name="u" /></form>'
        form = bs4.BeautifulSoup(html, "html5lib").find("form")
        assert isinstance(form, bs4.Tag)
        with pytest.raises(BricksetLoginError, match="password"):
            _build_login_payload(form, "alice", "s3cret")

    def test_ignores_inputs_without_a_name(self) -> None:
        html = (
            '<form><input type="text" />'
            '<input type="text" name="u" />'
            '<input type="password" name="p" /></form>'
        )
        form = bs4.BeautifulSoup(html, "html5lib").find("form")
        assert isinstance(form, bs4.Tag)
        assert set(_build_login_payload(form, "a", "b")) == {"u", "p"}


class TestFindErrorMessage:
    def test_extracts_a_validation_message(self) -> None:
        html = '<div class="errorMessage">Invalid username or password.</div>'
        assert _find_error_message(html) == "Invalid username or password."

    def test_falls_back_when_no_message_present(self) -> None:
        assert _find_error_message("<div>nothing here</div>") == "Brickset rejected the credentials"


class TestLogin:
    @responses.activate
    def test_successful_login_returns_a_session_with_the_cookie(self, brickset: Brickset) -> None:
        responses.get(LOGIN_URL, body=LOGIN_FORM_HTML)
        responses.post(LOGIN_URL, body="ok", headers={"Set-Cookie": ".ASPXAUTH=token; Path=/"})

        session = brickset.session
        assert ".ASPXAUTH" in session.cookies

    @responses.activate
    def test_login_posts_the_form_fields(self, brickset: Brickset) -> None:
        responses.get(LOGIN_URL, body=LOGIN_FORM_HTML)
        responses.post(LOGIN_URL, body="ok", headers={"Set-Cookie": ".ASPXAUTH=token; Path=/"})

        _ = brickset.session
        posted = _body(responses.calls[1].request.body)
        assert "__VIEWSTATE=abc123" in posted
        assert "Username=user" in posted

    @responses.activate
    def test_missing_form_raises(self, brickset: Brickset) -> None:
        responses.get(LOGIN_URL, body="<html><body>no form here</body></html>")
        with pytest.raises(ProviderUnavailable, match="brickset login failed") as excinfo:
            _ = brickset.session
        assert "aspnetForm" in str(excinfo.value.__cause__)

    @responses.activate
    def test_absent_auth_cookie_raises_with_the_site_message(self, brickset: Brickset) -> None:
        responses.get(LOGIN_URL, body=LOGIN_FORM_HTML)
        responses.post(LOGIN_URL, body='<div class="error">Bad password.</div>')
        with pytest.raises(ProviderUnavailable, match="brickset login failed") as excinfo:
            _ = brickset.session
        assert "Bad password." in str(excinfo.value.__cause__)

    @responses.activate
    def test_http_error_is_wrapped(self, brickset: Brickset) -> None:
        responses.get(LOGIN_URL, status=503)
        with pytest.raises(ProviderUnavailable, match="brickset login failed") as excinfo:
            _ = brickset.session
        assert isinstance(excinfo.value.__cause__, requests.HTTPError)

    def test_blank_credentials_rejected_at_construction(self) -> None:
        config = Config(brickset=BricksetConfig(username="", password=""))
        with pytest.raises(ValueError, match="username"):
            Brickset(config)


class TestOwnedSets:
    def test_parses_the_export_csv(self, brickset: Brickset) -> None:
        brickset._login_result = FakeSession({OWNED_URL: FakeResponse(text=OWNED_SETS_CSV)})  # type: ignore[assignment]
        assert brickset.get_owned_sets() == [
            LegoSet("10179", "Millennium Falcon", "2007"),
            LegoSet("6080", "King's Castle", "1984"),
        ]

    def test_empty_csv_yields_no_sets(self, brickset: Brickset) -> None:
        brickset._login_result = FakeSession(
            {OWNED_URL: FakeResponse(text="Number,Set name,Year\n")}
        )  # type: ignore[assignment]
        assert brickset.get_owned_sets() == []


class TestInstructions:
    def test_maps_set_numbers_to_urls_skipping_blanks(self, brickset: Brickset) -> None:
        brickset._login_result = FakeSession(
            {INSTRUCTIONS_URL: FakeResponse(text=INSTRUCTIONS_CSV)}
        )  # type: ignore[assignment]
        assert brickset.instructions == {"10179": "https://lego.example/10179.pdf"}

    def test_is_fetched_only_once(self, brickset: Brickset) -> None:
        session = FakeSession({INSTRUCTIONS_URL: FakeResponse(text=INSTRUCTIONS_CSV)})
        brickset._login_result = session  # type: ignore[assignment]
        _ = brickset.instructions
        _ = brickset.instructions
        assert session.requested == [INSTRUCTIONS_URL]


class TestDownloadManual:
    def test_writes_the_pdf_and_reports_success(self, brickset: Brickset, tmp_path: Path) -> None:
        pdf_url = "https://lego.example/10179.pdf"
        brickset._login_result = FakeSession(  # type: ignore[assignment]
            {
                INSTRUCTIONS_URL: FakeResponse(text=INSTRUCTIONS_CSV),
                pdf_url: FakeResponse(content=b"%PDF-1.4 payload"),
            }
        )
        output = tmp_path / "out.pdf"
        assert brickset.download_manual(LegoSet("10179", "Falcon", "2007"), output)
        assert output.read_bytes() == b"%PDF-1.4 payload"

    def test_dropped_connection_leaves_no_partial_file(
        self, brickset: Brickset, tmp_path: Path
    ) -> None:
        pdf_url = "https://lego.example/10179.pdf"
        brickset._login_result = FakeSession(  # type: ignore[assignment]
            {
                INSTRUCTIONS_URL: FakeResponse(text=INSTRUCTIONS_CSV),
                pdf_url: DroppedResponse(),
            }
        )
        output = tmp_path / "out.pdf"
        with pytest.raises(requests.ConnectionError):
            brickset.download_manual(LegoSet("10179", "Falcon", "2007"), output)

        assert not list(tmp_path.iterdir())

    def test_unknown_set_returns_false_without_writing(
        self, brickset: Brickset, tmp_path: Path
    ) -> None:
        brickset._login_result = FakeSession(
            {INSTRUCTIONS_URL: FakeResponse(text=INSTRUCTIONS_CSV)}
        )  # type: ignore[assignment]
        output = tmp_path / "out.pdf"
        assert not brickset.download_manual(LegoSet("0000", "Nope", "1999"), output)
        assert not output.exists()

    def test_set_with_blank_url_returns_false(self, brickset: Brickset, tmp_path: Path) -> None:
        brickset._login_result = FakeSession(
            {INSTRUCTIONS_URL: FakeResponse(text=INSTRUCTIONS_CSV)}
        )  # type: ignore[assignment]
        assert not brickset.download_manual(LegoSet("6080", "Castle", "1984"), tmp_path / "o.pdf")


class TestLoginIsAttemptedOnce:
    """cached_property does not cache exceptions, so a raising login would retry
    once per set. These guard the caching of the failure, not just the success."""

    @staticmethod
    def counting_login(brickset: Brickset, outcome: object) -> list[int]:
        calls: list[int] = []

        def fake_login() -> requests.Session:
            calls.append(1)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome  # type: ignore[return-value]

        brickset.login = fake_login  # type: ignore[method-assign]
        return calls

    @pytest.mark.parametrize(
        "failure",
        [
            BricksetLoginError("rejected"),
            requests.HTTPError("500 from brickset"),
            requests.ConnectionError("offline"),
            requests.Timeout("slow"),
        ],
        ids=["login-error", "http-error", "connection-error", "timeout"],
    )
    def test_failed_login_is_attempted_once(self, brickset: Brickset, failure: Exception) -> None:
        calls = self.counting_login(brickset, failure)
        for _ in range(5):
            with pytest.raises(ProviderUnavailable):
                _ = brickset.session
        assert len(calls) == 1

    def test_successful_login_is_attempted_once(self, brickset: Brickset) -> None:
        calls = self.counting_login(brickset, requests.Session())
        for _ in range(5):
            assert isinstance(brickset.session, requests.Session)
        assert len(calls) == 1

    def test_failure_is_reported_once_not_per_access(
        self, brickset: Brickset, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self.counting_login(brickset, requests.ConnectionError("offline"))
        for _ in range(5):
            with pytest.raises(ProviderUnavailable):
                _ = brickset.session
        assert capsys.readouterr().out.count("brickset: login failed") == 1

    def test_download_manual_raises_unavailable_without_retrying(
        self, brickset: Brickset, tmp_path: Path
    ) -> None:
        calls = self.counting_login(brickset, requests.ConnectionError("offline"))
        for n in range(5):
            with pytest.raises(ProviderUnavailable):
                brickset.download_manual(LegoSet(str(n), "Set", "2001"), tmp_path / "x.pdf")
        assert len(calls) == 1
