"""Interactive browser authentication, including institution SSO and MFA."""

import asyncio
from http.cookiejar import Cookie
from urllib.parse import urlsplit

from playwright.async_api import Error as BrowserError
from playwright.async_api import async_playwright

from .client import BlackboardClient
from .errors import ApiError, AuthenticationError, BlackboardError


def import_cookies(client: BlackboardClient, cookies: list[dict]) -> None:
    """Preserve domain, path, expiry, and secure flags; ignore SSO host cookies."""
    hostname = urlsplit(client.base_url).hostname
    client.http.cookies.clear()
    for value in cookies:
        domain = value["domain"]
        if hostname != domain.lstrip(".") and not (
            domain.startswith(".") and hostname.endswith(domain)
        ):
            continue
        expiry = value.get("expires", -1)
        client.http.cookies.jar.set_cookie(
            Cookie(
                version=0,
                name=value["name"],
                value=value["value"],
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=domain.startswith("."),
                domain_initial_dot=domain.startswith("."),
                path=value.get("path", "/"),
                path_specified=True,
                secure=value.get("secure", True),
                expires=int(expiry) if expiry > 0 else None,
                discard=expiry <= 0,
                comment=None,
                comment_url=None,
                rest={"HttpOnly": value.get("httpOnly", False)},
            )
        )


async def browser_login(client: BlackboardClient, *, timeout: float = 300) -> None:
    """Open an isolated browser and return once Blackboard confirms the session."""
    try:
        async with async_playwright() as playwright:
            browser = None
            for channel in ("chrome", "msedge", None):
                try:
                    options = {"channel": channel} if channel else {}
                    browser = await playwright.chromium.launch(
                        headless=False, **options
                    )
                    break
                except BrowserError:
                    continue
            if browser is None:
                raise AuthenticationError(
                    "No supported browser found. Install Chrome/Edge or run "
                    "'python -m playwright install chromium'."
                )
            try:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(client.base_url, wait_until="domcontentloaded")
                client.http.headers["User-Agent"] = await page.evaluate(
                    "navigator.userAgent"
                )
                deadline = asyncio.get_running_loop().time() + timeout
                while asyncio.get_running_loop().time() < deadline:
                    if not browser.is_connected() or not context.pages:
                        raise AuthenticationError("The login browser was closed.")
                    cookies = await context.cookies()
                    if cookies:
                        import_cookies(client, cookies)
                        try:
                            await client.verify_session()
                            return
                        except AuthenticationError:
                            pass
                        except ApiError as exc:
                            if exc.status not in (403, 404):
                                raise
                    await asyncio.sleep(1)
                raise AuthenticationError("Login timed out after five minutes.")
            finally:
                await browser.close()
    except BrowserError:
        raise BlackboardError(
            "The login browser could not complete authentication. Launch again to retry."
        ) from None
