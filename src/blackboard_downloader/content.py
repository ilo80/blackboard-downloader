"""Extract downloadable Blackboard files from Original attachments and Ultra BbML."""

import json
import re
from email.message import Message
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .errors import BlackboardError

ATTACHMENT_HANDLERS = {
    "resource/x-bb-file",
    "resource/x-bb-document",
    "resource/x-bb-assignment",
}


def resource_url(value: str) -> str:
    if value.startswith("@X@EmbeddedFile.requestUrlStub@X@"):
        value = "/" + value.removeprefix("@X@EmbeddedFile.requestUrlStub@X@").lstrip(
            "/"
        )
    if value.startswith("bbresource://"):
        resource = value.removeprefix("bbresource://")
        if re.fullmatch(r"_\d+_\d+", resource):
            resource = "xid-" + resource[1:]
        if not re.fullmatch(r"xid-\d+_\d+", resource):
            raise BlackboardError("Unresolved Blackboard resource reference.")
        return "/bbcswebdav/" + resource
    if value.startswith("bbupload://"):
        raise BlackboardError("An unpublished Blackboard upload cannot be downloaded.")
    return value


def file_key(url: str) -> str:
    """Ignore changing WebDAV signatures when identifying the same file."""
    parsed = urlsplit(url)
    match = re.search(r"/(xid-\d+_\d+)(/.*)?$", parsed.path)
    if "/bbcswebdav/" in parsed.path and match:
        return parsed.netloc + ":" + match.group(1) + (match.group(2) or "")
    return url


def body_files(body: str, base_url: str) -> list[tuple[str, str | None]]:
    result = []
    seen = set()
    soup = BeautifulSoup(body, "html.parser")
    for element in soup.select(
        "a[href], img[src], source[src], video[src], audio[src]"
    ):
        href = element.get("href") or element.get("src")
        path = urlsplit(href).path
        if not (
            "/bbcswebdav/" in path
            or href.startswith(("bbresource://", "bbupload://"))
            or "data-bbfile" in element.attrs
            or element.get("data-bbtype") in ("attachment", "image")
        ):
            continue
        try:
            metadata = json.loads(element.get("data-bbfile", "{}"))
        except ValueError:
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        name = metadata.get("linkName") or metadata.get("alternativeText")
        extension = metadata.get("extension")
        if name and extension and not name.lower().endswith("." + extension.lower()):
            name += "." + extension
        try:
            resolved = resource_url(href)
        except BlackboardError:
            # Retain unresolved entries for the export report without losing siblings.
            resolved = href
        url = urljoin(base_url + "/", resolved)
        key = file_key(url)
        if key not in seen:
            seen.add(key)
            result.append((url, name))
    return result


def response_filename(header: str, url: str) -> str:
    message = Message()
    message["Content-Disposition"] = header
    return (
        message.get_filename()
        or unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        or "file"
    )
