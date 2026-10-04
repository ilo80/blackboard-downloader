"""Test browser authentication lifecycle without opening a real browser."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from playwright.async_api import Error as BrowserError

from blackboard_downloader import auth
from blackboard_downloader.errors import AuthenticationError


def fake_playwright(monkeypatch, *, cookies=None, unavailable=False):
    page = SimpleNamespace(
        goto=AsyncMock(), evaluate=AsyncMock(return_value="Browser UA")
    )
    context = SimpleNamespace(
        new_page=AsyncMock(return_value=page),
        pages=[page],
        cookies=AsyncMock(return_value=cookies or []),
    )
    browser = SimpleNamespace(
        new_context=AsyncMock(return_value=context),
        is_connected=Mock(return_value=True),
        close=AsyncMock(),
    )
    launch = AsyncMock(return_value=browser)
    if unavailable:
        launch.side_effect = BrowserError("No browser executable")
    manager = SimpleNamespace(
        __aenter__=AsyncMock(
            return_value=SimpleNamespace(chromium=SimpleNamespace(launch=launch))
        ),
        __aexit__=AsyncMock(return_value=False),
    )

    # Special methods are looked up on the class by the async with statement.
    class Manager:
        async def __aenter__(self):
            return await manager.__aenter__()

        async def __aexit__(self, *args):
            return await manager.__aexit__(*args)

    monkeypatch.setattr(auth, "async_playwright", Manager)
    return browser, launch


async def test_browser_session_verified_and_browser_closed(client_factory, monkeypatch):
    browser, _ = fake_playwright(
        monkeypatch,
        cookies=[
            {"name": "JSESSIONID", "value": "session", "domain": "blackboard.example"}
        ],
    )
    async with client_factory(
        lambda _: httpx.Response(200, json={"id": "alice", "userName": "alice"})
    ) as client:
        await auth.browser_login(client)
        assert client.http.headers["User-Agent"] == "Browser UA"
        assert client.http.cookies.get("JSESSIONID") == "session"
    browser.close.assert_awaited_once()


async def test_missing_browser_has_installation_instructions(
    client_factory, monkeypatch
):
    _, launch = fake_playwright(monkeypatch, unavailable=True)
    async with client_factory(lambda _: httpx.Response(200)) as client:
        with pytest.raises(AuthenticationError, match="playwright install chromium"):
            await auth.browser_login(client)
    assert launch.await_count == 3


async def test_browser_timeout_closes_resources(client_factory, monkeypatch):
    browser, _ = fake_playwright(monkeypatch)
    async with client_factory(lambda _: httpx.Response(200)) as client:
        with pytest.raises(AuthenticationError, match="timed out"):
            await auth.browser_login(client, timeout=0)
    browser.close.assert_awaited_once()
