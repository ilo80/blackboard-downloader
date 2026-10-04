"""Test login, API pagination, HTTP retries, and cookie isolation offline."""

import asyncio
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

from blackboard_downloader.auth import import_cookies
from blackboard_downloader.client import NONCE, retry_delay, validate_url
from blackboard_downloader.errors import (
    ApiError,
    AuthenticationError,
    BlackboardError,
)

BASE = "https://blackboard.example"


@pytest.mark.parametrize(
    "url",
    [
        "http://blackboard.example",
        "https://alice:secret@blackboard.example",
        BASE + "/ultra",
        BASE + "?token=secret",
        BASE + "#fragment",
        "not-a-url",
    ],
)
def test_invalid_server_roots(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_valid_server_root():
    assert validate_url(BASE + "/") == BASE


async def test_classic_login_preserves_nonce_fields_and_literal_password(
    client_factory,
):
    requests = []
    html = (
        '<form action="/webapps/login/">'
        f'<input type="hidden" name="{NONCE}" value="a&amp;b">'
        '<input type="hidden" name="new_loc" value="/ultra">'
        '<input name="password" type="password"></form>'
    )

    def handler(request):
        requests.append(request)
        if request.url.path == "/":
            return httpx.Response(
                200,
                text=html,
                headers={"Set-Cookie": "JSESSIONID=web-session; Path=/; Secure"},
            )
        if request.method == "POST":
            return httpx.Response(
                302,
                headers={
                    "Location": "/ultra",
                    "Set-Cookie": "JSESSIONID=api-session; Path=/learn/api; Secure",
                },
            )
        return httpx.Response(200, json={"id": "_1_1", "userName": "alice"})

    async with client_factory(handler) as client:
        await client.login("alice+test", "p&=é+${secret}")
    fields = parse_qs(requests[1].content.decode())
    assert fields[NONCE] == ["a&b"]
    assert fields["new_loc"] == ["/ultra"]
    assert fields["password"] == ["p&=é+${secret}"]
    assert "web-session" in requests[2].headers["Cookie"]
    assert "api-session" in requests[2].headers["Cookie"]


@pytest.mark.parametrize("status", [401, 403])
async def test_login_requires_authenticated_api_response(client_factory, status):
    def handler(request):
        if request.url.path == "/":
            return httpx.Response(
                200,
                text=f'<form><input name="{NONCE}" type="hidden"></form>',
            )
        if request.method == "POST":
            return httpx.Response(302, headers={"Location": "/ultra"})
        return httpx.Response(status, json={})

    async with client_factory(handler) as client:
        with pytest.raises((AuthenticationError, ApiError)):
            await client.login("alice", "secret")


async def test_sso_form_explains_browser_option(client_factory):
    async with client_factory(lambda _: httpx.Response(200, text="SSO")) as client:
        with pytest.raises(AuthenticationError, match="browser"):
            await client.login("alice", "secret")


async def test_pagination_keeps_server_query_and_short_pages(client_factory):
    urls = []

    def handler(request):
        urls.append(str(request.url))
        if len(urls) == 1:
            return httpx.Response(
                200,
                json={
                    "results": [{"id": "first"}],
                    "paging": {"nextPage": "?limit=1&offset=1"},
                },
            )
        return httpx.Response(200, json={"results": [{"id": "second"}]})

    async with client_factory(handler) as client:
        assert await client.results("/items", params={"expand": "course"}) == [
            {"id": "first"},
            {"id": "second"},
        ]
    assert urls[0] == BASE + "/items?limit=100&expand=course"
    assert urls[1] == BASE + "/items?limit=1&offset=1"


@pytest.mark.parametrize(
    "next_page", ["/items?limit=100", "https://evil.example/items"]
)
async def test_pagination_loop_and_foreign_origin_fail(client_factory, next_page):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"results": [], "paging": {"nextPage": next_page}}
        )

    async with client_factory(handler) as client:
        with pytest.raises(BlackboardError):
            await client.results("/items")
    assert len(requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>Login</html>"),
        httpx.Response(302, headers={"Location": "/webapps/login/"}),
        httpx.Response(401),
    ],
)
async def test_expired_session_rejected(client_factory, response):
    async with client_factory(lambda _: response) as client:
        with pytest.raises(AuthenticationError):
            await client.get_json("/items")


@pytest.mark.parametrize("batch", [None, {}, ["bad"]])
async def test_invalid_results_are_reported(client_factory, batch):
    async with client_factory(
        lambda _: httpx.Response(200, json={"results": batch})
    ) as client:
        with pytest.raises(BlackboardError, match="results"):
            await client.results("/items")


async def test_course_names_are_resolved_and_sorted(client_factory):
    def handler(request):
        if request.url.path.endswith("/users/me/courses"):
            assert request.url.params["expand"] == "course"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"courseId": "b", "course": {"name": "Zoology"}},
                        {"courseId": "a"},
                        {"courseId": "a"},
                    ]
                },
            )
        assert request.url.path == "/learn/api/public/v3/courses/a"
        return httpx.Response(200, json={"name": "Algebra", "ultraStatus": "Ultra"})

    async with client_factory(handler) as client:
        courses = await client.courses()
    assert [course.name for course in courses] == ["Algebra", "Zoology"]
    assert courses[0].ultra


async def test_file_redirects_never_leak_cookies_or_auth(client_factory):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                302, headers={"Location": "https://storage.example/file"}
            )
        if len(requests) == 2:
            return httpx.Response(
                302,
                headers={
                    "Location": "/final",
                    "Set-Cookie": "storage=secret; Path=/",
                },
            )
        return httpx.Response(200, content=b"file")

    async with client_factory(handler) as client:
        client.http.cookies.set("JSESSIONID", "secret")
        client.http.headers["Authorization"] = "Bearer secret"
        async with client.open_file("/download") as response:
            assert await response.aread() == b"file"
    assert "secret" in requests[0].headers["Cookie"]
    for request in requests[1:]:
        assert "Cookie" not in request.headers
        assert "Authorization" not in request.headers


async def test_throttling_retries_honor_retry_after(client_factory, monkeypatch):
    requests = []
    sleep = AsyncMock()
    monkeypatch.setattr("blackboard_downloader.client.asyncio.sleep", sleep)

    def handler(request):
        requests.append(request)
        if len(requests) < 3:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"results": []})

    async with client_factory(handler) as client:
        assert await client.results("/items") == []
    assert len(requests) == 3
    assert [call.args for call in sleep.await_args_list] == [(2.0,), (2.0,)]


def test_retry_after_date_and_invalid_header():
    assert retry_delay(httpx.Response(429, headers={"Retry-After": "invalid"}), 2) == 4
    assert (
        retry_delay(
            httpx.Response(
                429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
            ),
            0,
        )
        == 0
    )


async def test_request_concurrency_is_bounded(client_factory):
    active = maximum = 0

    async def handler(request):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={})

    async with client_factory(handler, concurrency=3) as client:
        await asyncio.gather(*(client.get_json("/item") for _ in range(12)))
    assert maximum == 3


async def test_browser_cookie_import_preserves_scopes(client_factory):
    async with client_factory(lambda _: httpx.Response(200)) as client:
        import_cookies(
            client,
            [
                {"name": "JSESSIONID", "value": "web", "domain": "blackboard.example"},
                {
                    "name": "JSESSIONID",
                    "value": "api",
                    "domain": "blackboard.example",
                    "path": "/learn/api",
                },
                {"name": "sso", "value": "private", "domain": "sso.example"},
            ],
        )
        request = client.http.build_request("GET", BASE + "/learn/api/v1/users/me")
        assert "web" in request.headers["Cookie"]
        assert "api" in request.headers["Cookie"]
        assert "private" not in request.headers["Cookie"]
        assert all(cookie.secure for cookie in client.http.cookies.jar)
