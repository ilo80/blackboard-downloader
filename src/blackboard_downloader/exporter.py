"""Concurrent content discovery and streaming file export."""

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path

from .client import BlackboardClient
from .content import (
    ATTACHMENT_HANDLERS,
    body_files,
    file_key,
    resource_url,
    response_filename,
)
from .errors import AuthenticationError, BlackboardError
from .models import Course, Download, Event
from .paths import PathRegistry


async def drain_queue(queue: asyncio.Queue, handle: Callable, concurrency: int) -> None:
    """Use a fixed worker count even when a collection contains thousands of items."""

    async def worker():
        while True:
            item = await queue.get()
            try:
                await handle(item)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    joined = asyncio.create_task(queue.join())
    try:
        done, _ = await asyncio.wait(
            [joined, *workers], return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
    finally:
        for task in [joined, *workers]:
            task.cancel()
        await asyncio.gather(joined, *workers, return_exceptions=True)


class Exporter:
    def __init__(
        self,
        client: BlackboardClient,
        output: Path,
        *,
        overwrite: bool = False,
        on_event: Callable[[Event], None] | None = None,
    ):
        self.client = client
        self.registry = PathRegistry(output)
        self.output = self.registry.output
        self.overwrite = overwrite
        self.emit = on_event or (lambda event: None)
        self.report = {
            "status": "running",
            "courses": [],
            "downloaded": 0,
            "skipped": 0,
            "errors": [],
        }
        self.downloads: list[Download] = []
        self._visited: set[tuple[str, str]] = set()
        self._sources: set[tuple[Path, str]] = set()
        self._final_sources: dict[tuple[Path, str], Path] = {}
        self._file_locks: dict[tuple[Path, str], asyncio.Lock] = {}
        self._entries: dict[str, dict] = {}

    def error(self, course: Course, label: str, exc: Exception) -> None:
        self.report["errors"].append(
            {"course": course.name, "context": label, "message": str(exc)}
        )
        self._entries[course.id]["errors"] += 1
        self.emit(Event("error", f"{course.name} / {label}: {exc}"))

    def add_download(
        self, course: Course, parent: Path, url: str, name: str | None, identity: str
    ) -> None:
        key = (parent, file_key(url))
        if key in self._sources:
            return
        self._sources.add(key)
        self.downloads.append(Download(course, url, parent, name, identity))
        self.emit(Event("discovered", course.name, amount=len(self.downloads)))

    async def discover(self, courses: list[Course]) -> None:
        queue = asyncio.Queue()
        for course in courses:
            parent = self.registry.allocate(
                self.output / "courses", course.name, "course:" + course.id
            )
            parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "name": course.name,
                "path": parent.relative_to(self.output).as_posix(),
                "status": "running",
                "errors": 0,
            }
            self._entries[course.id] = entry
            self.report["courses"].append(entry)
            queue.put_nowait((course, parent, None))

        async def handle(job):
            course, parent, content = job
            label = (
                content.get("title") or "Untitled content" if content else course.name
            )
            self.emit(Event("scanning", f"{course.name} / {label}"))
            try:
                if content is None:
                    for item in await self.client.contents(course.id):
                        queue.put_nowait((course, parent, item))
                    return
                content_id = content.get("id")
                if not content_id:
                    raise BlackboardError("A content item has no identifier.")
                if (course.id, content_id) in self._visited:
                    return
                self._visited.add((course.id, content_id))
                handler = content.get("contentHandler", {}).get("id")
                standalone = handler == "resource/x-bb-file" and not content.get(
                    "hasChildren"
                )
                directory = (
                    parent
                    if standalone
                    else self.registry.allocate(parent, label, "content:" + content_id)
                )
                directory.mkdir(parents=True, exist_ok=True)
                found = False
                if handler == "resource/x-bb-file" or (
                    not course.ultra and handler in ATTACHMENT_HANDLERS
                ):
                    try:
                        attachments = await self.client.attachments(
                            course.id, content_id
                        )
                        for attachment in attachments:
                            if not attachment.get("id"):
                                raise BlackboardError(
                                    "An attachment has no identifier."
                                )
                            found = True
                            self.add_download(
                                course,
                                directory,
                                self.client.attachment_url(
                                    course.id, content_id, attachment["id"]
                                ),
                                attachment.get("fileName"),
                                "attachment:" + content_id + ":" + attachment["id"],
                            )
                    except AuthenticationError:
                        raise
                    except BlackboardError as exc:
                        self.error(course, label, exc)
                try:
                    embedded = body_files(
                        content.get("body") or "", self.client.base_url
                    )
                except BlackboardError as exc:
                    self.error(course, label, exc)
                    embedded = []
                for url, name in embedded:
                    found = True
                    self.add_download(
                        course,
                        directory,
                        url,
                        name,
                        "body:" + content_id + ":" + file_key(url),
                    )
                if standalone and not found:
                    raise BlackboardError("Blackboard returned no downloadable file.")
                if content.get("hasChildren"):
                    for child in await self.client.contents(course.id, content_id):
                        queue.put_nowait((course, directory, child))
            except AuthenticationError:
                raise
            except (BlackboardError, OSError) as exc:
                self.error(course, label, exc)

        await drain_queue(queue, handle, self.client.concurrency)

    async def save_file(self, response, destination: Path, key: str) -> None:
        """Only publish complete files; remove temporary data on failure or Ctrl+C."""
        self.registry.check(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        received = 0
        probe = bytearray()
        length = response.headers.get("Content-Length")
        expected = int(length) if length and length.isdecimal() else None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".bb-", suffix=".part", delete=False
            ) as target:
                temporary = Path(target.name)
                async for chunk in response.aiter_bytes(chunk_size=256 * 1024):
                    if len(probe) < 16384:
                        probe.extend(chunk[: 16384 - len(probe)])
                        lowered = probe.lower()
                        if b"user_id" in lowered and (
                            b"password" in lowered or b"nonceutil" in lowered
                        ):
                            raise AuthenticationError(
                                "Blackboard returned a login form instead of a file."
                            )
                    # Await writes so slow disks do not stall every network transfer.
                    write = asyncio.create_task(asyncio.to_thread(target.write, chunk))
                    try:
                        await asyncio.shield(write)
                    except asyncio.CancelledError:
                        # Finish this write before closing and removing its file.
                        await write
                        raise
                    received += len(chunk)
                    self.emit(Event("bytes", key=key, amount=len(chunk)))
            if (
                expected is not None
                and not response.headers.get("Content-Encoding")
                and received != expected
            ):
                raise BlackboardError(
                    "The file transfer ended before its declared size."
                )
            self.registry.check(destination)
            temporary.replace(destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def download(self, item: Download) -> None:
        label = f"{item.course.name} / {item.name or 'File'}"
        key = str(id(item))
        destination = self.registry.known(item.parent, item.identity)
        if destination is not None and destination.is_file() and not self.overwrite:
            self.report["skipped"] += 1
            self.emit(Event("finished", label, key))
            return
        self.emit(Event("starting", label, key))
        try:
            async with self.client.open_file(resource_url(item.url)) as response:
                source = (item.parent, file_key(str(response.url)))
                lock = self._file_locks.setdefault(source, asyncio.Lock())
                async with lock:
                    if source in self._final_sources:
                        self.report["skipped"] += 1
                        return
                    name = item.name or response_filename(
                        response.headers.get("Content-Disposition", ""),
                        str(response.url),
                    )
                    destination = self.registry.allocate(
                        item.parent, name, item.identity
                    )
                    if destination.is_file() and not self.overwrite:
                        self.report["skipped"] += 1
                    else:
                        length = response.headers.get("Content-Length", "")
                        self.emit(
                            Event(
                                "transferring",
                                f"{item.course.name} / {destination.name}",
                                key,
                                total=int(length) if length.isdecimal() else None,
                            )
                        )
                        await self.save_file(response, destination, key)
                        self.report["downloaded"] += 1
                    self._final_sources[source] = destination
        except AuthenticationError:
            raise
        except (BlackboardError, OSError) as exc:
            self.error(item.course, label, exc)
        finally:
            self.emit(Event("finished", label, key))

    async def run(self, courses: list[Course]) -> dict:
        try:
            await self.discover(courses)
            self.registry.save()
            self.emit(Event("planned", total=len(self.downloads)))
            queue = asyncio.Queue()
            for item in self.downloads:
                queue.put_nowait(item)
            await drain_queue(queue, self.download, self.client.concurrency)
            self.report["status"] = "partial" if self.report["errors"] else "complete"
            for entry in self.report["courses"]:
                entry["status"] = "partial" if entry["errors"] else "complete"
            return self.report
        except BaseException:
            self.report["status"] = "interrupted"
            for entry in self.report["courses"]:
                entry["status"] = "interrupted"
            raise
        finally:
            self.registry.save()
            self.registry.write_json(self.output / "report.json", self.report)
