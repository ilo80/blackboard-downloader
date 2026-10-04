"""Exercise the interactive workflow and defaults without a live Blackboard account."""

from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from rich.console import Console

from blackboard_downloader import cli
from blackboard_downloader.config import Settings, read_settings
from blackboard_downloader.models import Course, Event
from blackboard_downloader.progress import ExportProgress


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", [0, 1, 2, 3, 4]),
        ("all", [0, 1, 2, 3, 4]),
        ("*", [0, 1, 2, 3, 4]),
        ("1, 3-5", [0, 2, 3, 4]),
        ("2 4 2", [1, 3]),
        ("2 - 4", [1, 2, 3]),
    ],
)
def test_course_selection(value, expected):
    assert cli.parse_selection(value, 5) == expected


@pytest.mark.parametrize("value", ["0", "6", "5-3", "_1_1", "1,", "none", "1-1000000"])
def test_invalid_selections_are_rejected(value):
    with pytest.raises(ValueError):
        cli.parse_selection(value, 5)


def test_selection_uses_names_and_defaults_to_all(monkeypatch):
    console = Console(file=StringIO())
    ask = Mock(side_effect=["invalid", "all"])
    monkeypatch.setattr(cli.Prompt, "ask", ask)
    courses = [Course("_secret_1", "Algebra [A]"), Course("_secret_2", "Physics")]
    assert cli.select_courses(courses, console) == courses
    text = console.file.getvalue()
    assert "Algebra [A]" in text and "Physics" in text
    assert "_secret_1" not in text
    assert all(call.kwargs["default"] == "all" for call in ask.call_args_list)


def test_settings_override_shell_without_password_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("BLACKBOARD_USERNAME", "old")
    path = tmp_path / ".env"
    path.write_text(
        "BLACKBOARD_USERNAME=alice\n"
        "BLACKBOARD_PASSWORD='p${literal}#value'\n"
        "BLACKBOARD_OUTPUT=archive\n",
        encoding="utf-8",
    )
    settings = read_settings(path)
    assert settings.username == "alice"
    assert settings.password == "p${literal}#value"
    assert settings.output == Path("archive")
    assert settings.has_credentials
    assert settings.password not in repr(settings)


@pytest.mark.parametrize("configured", [False, True])
async def test_full_workflow_has_defaults_for_every_question(
    client_factory, tmp_path, monkeypatch, configured
):
    import httpx

    settings = Settings(
        url="https://blackboard.example",
        output=tmp_path,
        username="alice" if configured else "",
        password="secret" if configured else "",
    )
    (tmp_path / ".blackboard-paths.json").write_text("{}")
    client = client_factory(lambda _: httpx.Response(200, json={"results": []}))
    client.login = AsyncMock()
    client.courses = AsyncMock(
        return_value=[Course("a", "Algebra"), Course("b", "Physics")]
    )
    browser = AsyncMock()
    monkeypatch.setattr(cli, "read_settings", lambda: settings)
    monkeypatch.setattr(cli, "BlackboardClient", lambda _: client)
    monkeypatch.setattr(cli, "browser_login", browser)
    defaults = []

    def answer(prompt, **kwargs):
        assert "default" in kwargs, prompt
        assert kwargs["default"] is not None
        defaults.append(kwargs["default"])
        return kwargs["default"]

    monkeypatch.setattr(cli.Prompt, "ask", answer)
    monkeypatch.setattr(cli.Confirm, "ask", answer)
    console = Console(file=StringIO(), width=100)
    assert await cli.run(console) == 0
    assert defaults == [
        settings.url,
        "configured" if configured else "browser",
        "all",
        str(tmp_path),
        False,
    ]
    assert browser.await_count == (0 if configured else 1)
    assert client.login.await_count == (1 if configured else 0)
    assert "Algebra" in console.file.getvalue()


def test_progress_renders_names_counts_and_transfers():
    console = Console(file=StringIO(), force_terminal=True, width=100)
    with ExportProgress(console) as progress:
        for event in [
            Event("scanning", "Algebra / Lectures"),
            Event("discovered", amount=1),
            Event("planned", total=1),
            Event("starting", "Algebra / lecture.pdf", "file"),
            Event("transferring", "Algebra / lecture.pdf", "file", total=100),
            Event("bytes", key="file", amount=50),
        ]:
            progress.emit(event)
        progress.live.refresh()
        console.print(progress.files)
        assert "lecture.pdf" in console.file.getvalue()
        progress.emit(Event("finished", key="file"))
        assert progress.overall.tasks[0].completed == 1
        assert not progress.active


def test_main_maps_cancellation_to_exit_130(monkeypatch):
    monkeypatch.setattr(cli.sys, "argv", ["blackboard-downloader"])
    monkeypatch.setattr(cli, "run", AsyncMock(side_effect=KeyboardInterrupt))
    assert cli.main() == 130
