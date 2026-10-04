"""Verify hierarchy, concurrent exports, resumability, and partial failures offline."""

import asyncio
import json
from collections import Counter

import httpx
import pytest

from blackboard_downloader.errors import AuthenticationError
from blackboard_downloader.exporter import Exporter
from blackboard_downloader.models import Course


def content(identity, title, handler="folder", *, children=False, body=""):
    return {
        "id": identity,
        "title": title,
        "contentHandler": {"id": "resource/x-bb-" + handler},
        "hasChildren": children,
        "body": body,
    }


def course_handler(request):
    path = request.url.path
    if path.endswith("/contents"):
        if "/blocked/" in path:
            return httpx.Response(403)
        return httpx.Response(
            200, json={"results": [content("root", "Lectures", children=True)]}
        )
    if path.endswith("/root/children"):
        return httpx.Response(
            200,
            json={
                "results": [
                    content("pdf", "Lecture", "file"),
                    content("empty", "Empty folder", children=True),
                    content("doc", "Exercises", "document"),
                    content("root", "Lectures", children=True),
                ]
            },
        )
    if path.endswith("/empty/children"):
        return httpx.Response(200, json={"results": []})
    if path.endswith("/pdf/attachments"):
        return httpx.Response(
            200, json={"results": [{"id": "a", "fileName": "one.pdf"}]}
        )
    if path.endswith("/doc/attachments"):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "b", "fileName": "questions.pdf"},
                    {"id": "c", "fileName": "answers.pdf"},
                ]
            },
        )
    if path.endswith("/download"):
        return httpx.Response(200, content=b"%PDF-example")
    raise AssertionError("Unexpected request: " + path)


async def test_hierarchy_empty_folders_cycles_and_blocked_course(
    client_factory, tmp_path, course
):
    events = []
    async with client_factory(course_handler) as client:
        exporter = Exporter(client, tmp_path, on_event=events.append)
        report = await exporter.run([Course("blocked", "Closed course"), course])
    root = tmp_path / "courses" / course.name / "Lectures"
    assert (root / "Empty folder").is_dir()
    assert (root / "one.pdf").read_bytes() == b"%PDF-example"
    assert (root / "Exercises" / "questions.pdf").is_file()
    assert (root / "Exercises" / "answers.pdf").is_file()
    assert report["downloaded"] == 3
    assert report["status"] == "partial"
    assert [item["status"] for item in report["courses"]] == ["partial", "complete"]
    assert "403" in report["errors"][0]["message"]
    assert json.loads((tmp_path / "report.json").read_text())["downloaded"] == 3
    assert len([event for event in events if event.kind == "finished"]) == 3


async def test_resume_skips_file_requests_and_overwrite_is_explicit(
    client_factory, tmp_path, course
):
    calls = Counter()

    def handler(request):
        calls[request.url.path] += 1
        return course_handler(request)

    async with client_factory(handler) as client:
        await Exporter(client, tmp_path).run([course])
        before = sum(
            count for path, count in calls.items() if path.endswith("/download")
        )
        report = await Exporter(client, tmp_path).run([course])
        assert report["downloaded"] == 0
        assert report["skipped"] == 3
        assert before == sum(
            count for path, count in calls.items() if path.endswith("/download")
        )
        report = await Exporter(client, tmp_path, overwrite=True).run([course])
    assert report["downloaded"] == 3


async def test_ultra_bbml_resources_names_and_deduplication(client_factory, tmp_path):
    requests = []
    body = (
        '<a href="bbresource://_42_1" '
        'data-bbfile=\'{"linkName":"Worksheet","extension":"pdf"}\'>Download</a>'
        '<a href="/bbcswebdav/xid-42_1?signature=changed">Duplicate</a>'
        '<img src="@X@EmbeddedFile.requestUrlStub@X@bbcswebdav/xid-43_1" '
        'data-bbfile=\'{"linkName":"Figure.png"}\'>'
        '<a href="https://video.example/watch">External video</a>'
    )

    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/contents"):
            return httpx.Response(
                200,
                json={"results": [content("doc", "Worksheet", "document", body=body)]},
            )
        return httpx.Response(200, content=b"resource")

    async with client_factory(handler) as client:
        report = await Exporter(client, tmp_path).run(
            [Course("ultra", "Mechanics", True)]
        )
    root = tmp_path / "courses" / "Mechanics" / "Worksheet"
    assert (root / "Worksheet.pdf").read_bytes() == b"resource"
    assert (root / "Figure.png").is_file()
    assert report["downloaded"] == 2
    assert not any(path.endswith("/attachments") for path in requests)


class BrokenStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"partial" * 50000
        raise httpx.ReadError("secret-signed-url must not appear")


async def test_failed_overwrite_preserves_existing_file_and_removes_temporary_data(
    client_factory, tmp_path, course
):
    async with client_factory(course_handler) as client:
        await Exporter(client, tmp_path).run([course])

    def handler(request):
        if request.url.path.endswith("/pdf/attachments/a/download"):
            return httpx.Response(200, stream=BrokenStream())
        return course_handler(request)

    async with client_factory(handler) as client:
        report = await Exporter(client, tmp_path, overwrite=True).run([course])
    assert (
        tmp_path / "courses" / course.name / "Lectures" / "one.pdf"
    ).read_bytes() == (b"%PDF-example")
    assert report["status"] == "partial"
    assert report["downloaded"] == 2
    assert "secret-signed-url" not in json.dumps(report)
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("kind", ["redirect", "html", "401"])
async def test_expiration_aborts_export_and_persists_interrupted_report(
    client_factory, tmp_path, course, kind
):
    def handler(request):
        if request.url.path.endswith("/download"):
            if kind == "redirect":
                return httpx.Response(302, headers={"Location": "/webapps/login/"})
            if kind == "html":
                return httpx.Response(
                    200,
                    text='<form><input name="user_id"><input name="password"></form>',
                )
            return httpx.Response(401)
        return course_handler(request)

    async with client_factory(handler) as client:
        with pytest.raises(AuthenticationError):
            await Exporter(client, tmp_path).run([course])
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == "interrupted"
    assert report["downloaded"] == 0
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.pdf"))


async def test_transfer_size_mismatch_is_not_published(
    client_factory, tmp_path, course
):
    def handler(request):
        if request.url.path.endswith("/download"):
            return httpx.Response(
                200, content=b"short", headers={"Content-Length": "100"}
            )
        return course_handler(request)

    async with client_factory(handler) as client:
        report = await Exporter(client, tmp_path).run([course])
    assert len(report["errors"]) == 3
    assert not list(tmp_path.rglob("*.pdf"))
    assert not list(tmp_path.rglob("*.part"))


async def test_downloads_and_attachment_discovery_run_concurrently(
    client_factory, tmp_path, course
):
    active = Counter()
    maximum = Counter()

    async def handler(request):
        path = request.url.path
        if path.endswith("/contents"):
            return httpx.Response(
                200,
                json={
                    "results": [content(str(i), f"File {i}", "file") for i in range(16)]
                },
            )
        kind = "attachments" if path.endswith("/attachments") else "files"
        active[kind] += 1
        maximum[kind] = max(maximum[kind], active[kind])
        await asyncio.sleep(0.01)
        active[kind] -= 1
        if kind == "attachments":
            number = path.split("/")[-2]
            return httpx.Response(
                200, json={"results": [{"id": number, "fileName": f"{number}.pdf"}]}
            )
        return httpx.Response(200, content=b"file")

    async with client_factory(handler, concurrency=4) as client:
        report = await Exporter(client, tmp_path).run([course])
    assert report["downloaded"] == 16
    assert maximum == {"attachments": 4, "files": 4}


class WaitingStream(httpx.AsyncByteStream):
    def __init__(self, started):
        self.started = started

    async def __aiter__(self):
        yield b"partial" * 50000
        self.started.set()
        await asyncio.Event().wait()


async def test_cancellation_keeps_report_and_cleans_partial_files(
    client_factory, tmp_path, course
):
    started = asyncio.Event()

    def handler(request):
        if request.url.path.endswith("/download"):
            return httpx.Response(200, stream=WaitingStream(started))
        return course_handler(request)

    async with client_factory(handler) as client:
        task = asyncio.create_task(Exporter(client, tmp_path).run([course]))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not list(tmp_path.rglob("*.part"))
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "interrupted"


async def test_empty_course_is_successful(client_factory, tmp_path, course):
    async with client_factory(
        lambda _: httpx.Response(200, json={"results": []})
    ) as client:
        report = await Exporter(client, tmp_path).run([course])
    assert report["status"] == "complete"
    assert report["downloaded"] == 0
    assert (tmp_path / "courses" / course.name).is_dir()
