import re

from lego_manual_downloader.http import USER_AGENT, new_session


def test_user_agent_identifies_the_tool() -> None:
    assert re.fullmatch(r"lego-manual-downloader/\S+", USER_AGENT)


def test_new_session_sets_the_user_agent() -> None:
    assert new_session().headers["User-Agent"] == USER_AGENT


def test_new_session_returns_a_fresh_session_each_time() -> None:
    first, second = new_session(), new_session()
    assert first is not second
    first.headers["X-Test"] = "1"
    assert "X-Test" not in second.headers


def test_new_session_has_an_empty_cookie_jar() -> None:
    assert len(new_session().cookies) == 0
