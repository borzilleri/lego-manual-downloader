import re
from typing import Any

import pytest
import requests
from requests.adapters import HTTPAdapter

from lego_manual_downloader.config import HttpConfig
from lego_manual_downloader.http import USER_AGENT, SessionBuilder, TimeoutHttpAdapter


def _prepared() -> requests.PreparedRequest:
    return requests.Request("GET", "http://example.com").prepare()


def test_user_agent_identifies_the_tool() -> None:
    assert re.fullmatch(r"lego-manual-downloader/\S+", USER_AGENT)


def test_session_sets_the_user_agent(session_builder: SessionBuilder) -> None:
    assert session_builder.session().headers["User-Agent"] == USER_AGENT


def test_session_returns_a_fresh_session_each_time(session_builder: SessionBuilder) -> None:
    first, second = session_builder.session(), session_builder.session()
    assert first is not second
    first.headers["X-Test"] = "1"
    assert "X-Test" not in second.headers


def test_session_has_an_empty_cookie_jar(session_builder: SessionBuilder) -> None:
    assert len(session_builder.session().cookies) == 0


class TestTimeout:
    """requests waits forever by default, so every adapter must carry a timeout."""

    @pytest.fixture
    def sent_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        captured: dict[str, Any] = {}

        def fake_send(self: HTTPAdapter, request: Any, **kwargs: Any) -> requests.Response:
            captured.update(kwargs)
            return requests.Response()

        monkeypatch.setattr(HTTPAdapter, "send", fake_send)
        return captured

    @pytest.mark.parametrize("scheme", ["http://", "https://"])
    def test_both_schemes_are_mounted_with_the_configured_timeout(self, scheme: str) -> None:
        session = SessionBuilder(HttpConfig(timeout=7)).session()
        adapter = session.get_adapter(f"{scheme}example.com")
        assert isinstance(adapter, TimeoutHttpAdapter)
        assert adapter.timeout == 7

    def test_configured_timeout_is_applied_when_the_caller_gives_none(
        self, sent_kwargs: dict[str, Any]
    ) -> None:
        TimeoutHttpAdapter(timeout=7).send(_prepared())
        assert sent_kwargs["timeout"] == 7

    def test_an_explicit_timeout_is_passed_through_unchanged(
        self, sent_kwargs: dict[str, Any]
    ) -> None:
        TimeoutHttpAdapter(timeout=7).send(_prepared(), timeout=0.5)
        assert sent_kwargs["timeout"] == 0.5

    def test_other_send_arguments_are_forwarded(self, sent_kwargs: dict[str, Any]) -> None:
        proxies = {"http": "http://proxy.example"}
        TimeoutHttpAdapter(timeout=7).send(_prepared(), stream=True, proxies=proxies)
        assert sent_kwargs["stream"] is True
        assert sent_kwargs["proxies"] == proxies
