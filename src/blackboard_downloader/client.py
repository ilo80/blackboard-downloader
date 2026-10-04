"""Asynchronous, bounded HTTP access to Blackboard and file storage."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .errors import ApiError, AuthenticationError, BlackboardError
from .models import Course

PUBLIC_API = "/learn/api/public/v1"
NONCE = "blackboard.platform.security.NonceUtil.nonce.ajax"
RETRY_STATUSES = {429, 500, 502, 503, 504}


def validate_url(value: str) -> str:
    """Require an HTTPS server root without embedded credentials."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.path not in ("", "/")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Enter the Blackboard HTTPS server root, e.g. https://bb.edu.")
    return value.rstrip("/")


def identifier(value: str) -> str:
    return quote(value, safe="")


def retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Honor Retry-After seconds or HTTP dates; otherwise use bounded backoff."""
    header = response.headers.get("Retry-After", "") if response else ""
    try:
        return max(0.0, float(header))
    except ValueError:
        try:
            when = parsedate_to_datetime(header)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            return max(0.0, (when - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return min(2**attempt, 8)


class BlackboardClient:
    """Reuse connections and cookies, limiting all in-flight HTTP requests."""

    def __init__(
        self,
        base_url: str,
        *,
        concurrency: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = validate_url(base_url)
        if concurrency < 1:
            raise ValueError("Concurrency must be positive.")
        self.concurrency = concurrency
        self._slots = asyncio.Semaphore(concurrency)
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=20),
            limits=httpx.Limits(
                max_connections=concurrency, max_keepalive_connections=concurrency
            ),
            headers={"User-Agent": "BlackboardDownloader/0.1"},
            transport=transport,
            follow_redirects=False,
        )
        self.storage = httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=20),
            limits=httpx.Limits(max_connections=concurrency),
            transport=transport,
            follow_redirects=False,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.http.aclose()
        await self.storage.aclose()

    def url(self, path: str, relative_to: str | None = None) -> str:
        result = urljoin(relative_to or self.base_url + "/", path)
        parsed = urlsplit(result)
        origin = urlsplit(self.base_url)
        if (
            (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc)
            or parsed.username
            or parsed.password
        ):
            raise BlackboardError("An API URL points outside the Blackboard server.")
        return result

    @staticmethod
    def check(response: httpx.Response) -> None:
        path = response.url.path
        location = response.headers.get("Location", "")
        if response.status_code == 401 or (
            response.is_redirect and "/login" in urlsplit(location).path
        ):
            raise AuthenticationError("The Blackboard session expired. Sign in again.")
        if not response.is_success:
            raise ApiError(response.status_code, path)

    @asynccontextmanager
    async def open_response(self, url: str, *, method: str = "GET", **kwargs):
        """Retry idempotent requests before yielding; stream bodies without buffering."""
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise BlackboardError("Invalid HTTPS download URL.")
        local = (parsed.scheme, parsed.netloc) == (
            urlsplit(self.base_url).scheme,
            urlsplit(self.base_url).netloc,
        )
        session = self.http if local else self.storage
        # An external storage host receives neither Blackboard cookies nor auth.
        request = session.build_request(method, url, **kwargs)
        if not local:
            request.headers.pop("Cookie", None)
            request.headers.pop("Authorization", None)
        response = None
        for attempt in range(4):
            await self._slots.acquire()
            try:
                response = await session.send(request, stream=True)
            except httpx.TransportError as exc:
                self._slots.release()
                if method != "GET" or attempt == 3:
                    raise BlackboardError(
                        f"Network failure ({type(exc).__name__}): {parsed.path}"
                    ) from None
                await asyncio.sleep(retry_delay(None, attempt))
                continue
            except BaseException:
                self._slots.release()
                raise
            if (
                method == "GET"
                and response.status_code in RETRY_STATUSES
                and attempt < 3
            ):
                delay = retry_delay(response, attempt)
                await response.aclose()
                self._slots.release()
                await asyncio.sleep(delay)
                continue
            break
        try:
            yield response
        except httpx.TransportError as exc:
            raise BlackboardError(
                f"Transfer interrupted ({type(exc).__name__}): {parsed.path}"
            ) from None
        finally:
            await response.aclose()
            self._slots.release()

    async def get_json(self, path: str, *, params: dict | None = None) -> dict:
        async with self.open_response(
            self.url(path), params=params, headers={"Accept": "application/json"}
        ) as response:
            self.check(response)
            if "json" not in response.headers.get("Content-Type", "").lower():
                raise AuthenticationError("Blackboard returned a login page, not JSON.")
            await response.aread()
            try:
                data = response.json()
            except ValueError:
                raise BlackboardError("Blackboard returned invalid JSON.") from None
            if not isinstance(data, dict):
                raise BlackboardError("Blackboard returned an invalid JSON object.")
            return data

    async def results(self, path: str, *, params: dict | None = None) -> list[dict]:
        url = self.url(path)
        query = {"limit": 100, **(params or {})}
        seen = set()
        items = []
        while url:
            page_url = str(httpx.Request("GET", url, params=query).url)
            if page_url in seen:
                raise BlackboardError("Blackboard returned a pagination loop.")
            seen.add(page_url)
            data = await self.get_json(url, params=query)
            batch = data.get("results")
            if not isinstance(batch, list) or any(
                not isinstance(item, dict) for item in batch
            ):
                raise BlackboardError("Blackboard returned an invalid results list.")
            items.extend(batch)
            next_page = data.get("paging", {}).get("nextPage")
            url = self.url(next_page, page_url) if next_page else ""
            query = None
        return items

    async def verify_session(self) -> dict:
        """The web session endpoint is used by the prototype, not public OAuth."""
        user = await self.get_json("/learn/api/v1/users/me")
        if not user.get("id") or user.get("userName", "").casefold() in {
            "guest",
            "anonymous",
        }:
            raise AuthenticationError(
                "Blackboard did not confirm an authenticated user."
            )
        return user

    async def login(self, username: str, password: str) -> None:
        """Support the classic login form using credentials from configuration."""
        if not username or not password:
            raise AuthenticationError("Configure both username and password first.")
        url = self.base_url + "/"
        for _ in range(10):
            async with self.open_response(url) as response:
                if response.is_redirect:
                    url = self.url(response.headers.get("Location", ""), url)
                    continue
                self.check(response)
                await response.aread()
                soup = BeautifulSoup(response.text, "html.parser")
                nonce = soup.find("input", attrs={"name": NONCE})
                form = nonce.find_parent("form") if nonce else None
                if form is None:
                    raise AuthenticationError(
                        "Classic login is unavailable. Choose browser login for SSO/MFA."
                    )
                fields = {
                    field["name"]: field.get("value", "")
                    for field in form.select('input[type="hidden"][name]')
                }
                action = self.url(form.get("action") or "/webapps/login/", url)
                break
        else:
            raise AuthenticationError("Too many login redirects. Use browser login.")
        fields.update(
            user_id=username, password=password, action="login", login="Login"
        )
        async with self.open_response(
            action,
            method="POST",
            data=fields,
            headers={"Referer": self.base_url + "/"},
        ) as response:
            if not response.is_redirect:
                self.check(response)
                await response.aread()
                if BeautifulSoup(response.text, "html.parser").find(
                    "input", attrs={"name": "password"}
                ):
                    raise AuthenticationError(
                        "Blackboard rejected the configured login."
                    )
        await self.verify_session()

    async def courses(self) -> list[Course]:
        memberships = await self.results(
            f"{PUBLIC_API}/users/me/courses", params={"expand": "course"}
        )
        courses = []
        seen = set()
        for membership in memberships:
            course_id = membership.get("courseId")
            if not course_id or course_id in seen:
                continue
            seen.add(course_id)
            details = membership.get("course") or {}
            if not details.get("name"):
                details = await self.get_json(
                    f"/learn/api/public/v3/courses/{identifier(course_id)}"
                )
            name = details.get("name")
            if not name:
                raise BlackboardError("A course has no display name in Blackboard.")
            courses.append(
                Course(
                    course_id,
                    name,
                    details.get("ultraStatus") in ("Ultra", "UltraPreview"),
                )
            )
        return sorted(courses, key=lambda course: (course.name.casefold(), course.id))

    async def contents(
        self, course_id: str, parent_id: str | None = None
    ) -> list[dict]:
        path = f"{PUBLIC_API}/courses/{identifier(course_id)}/contents"
        if parent_id is not None:
            path += f"/{identifier(parent_id)}/children"
        return await self.results(path)

    async def attachments(self, course_id: str, content_id: str) -> list[dict]:
        path = (
            f"{PUBLIC_API}/courses/{identifier(course_id)}"
            f"/contents/{identifier(content_id)}/attachments"
        )
        return await self.results(path)

    def attachment_url(
        self, course_id: str, content_id: str, attachment_id: str
    ) -> str:
        return (
            f"{PUBLIC_API}/courses/{identifier(course_id)}"
            f"/contents/{identifier(content_id)}/attachments"
            f"/{identifier(attachment_id)}/download"
        )

    @asynccontextmanager
    async def open_file(self, path: str):
        url = urljoin(self.base_url + "/", path)
        for _ in range(10):
            async with self.open_response(url) as response:
                if response.is_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise BlackboardError("A file redirect has no Location header.")
                    url = urljoin(url, location)
                    if "/login" in urlsplit(url).path:
                        raise AuthenticationError(
                            "The session expired during download."
                        )
                    continue
                self.check(response)
                yield response
                return
        raise BlackboardError("Too many redirects for a file.")
