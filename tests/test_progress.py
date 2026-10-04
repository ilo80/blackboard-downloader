"""Verify stable rendered progress bars as descriptions and transfer units change."""

from io import StringIO

import pytest
from rich.console import Console

from blackboard_downloader.models import Event
from blackboard_downloader.progress import ExportProgress


def bar_positions(console, progress):
    lines = console.render_lines(progress, pad=False)
    positions = []
    for line in lines:
        offset = 0
        cells = []
        for segment in line:
            if segment.text and all(char in "━╸╺" for char in segment.text):
                cells.extend(range(offset, offset + segment.cell_length))
            offset += segment.cell_length
        positions.append(cells)
    return positions


@pytest.mark.parametrize("width", [80, 100, 140])
def test_file_bars_keep_their_width_and_position(width):
    console = Console(
        file=StringIO(),
        width=width,
        color_system="truecolor",
        no_color=False,
        legacy_windows=False,
    )
    progress = ExportProgress(console)
    now = 0.0
    progress.files.get_time = lambda: now
    layouts = []
    for number, (name, total, chunk) in enumerate(
        [
            ("a.pdf", None, 50),
            ("notes.pdf", 900, 200),
            ("Course / " + "Long document title " * 10, 950_000, 200_000),
            ("講義 / résumé.pdf", 5_000_000_000, 2_000_000_000),
        ]
    ):
        key = str(number)
        progress.emit(Event("starting", name, key))
        progress.emit(Event("transferring", name, key, total=total))
        now += 1
        progress.emit(Event("bytes", key=key, amount=chunk))
        now += 1
        progress.emit(Event("bytes", key=key, amount=chunk))
        positions = bar_positions(console, progress.files)
        assert len(positions) == 1
        assert positions[0], "The progress bar must remain visible."
        layouts.append(positions[0])
        progress.emit(Event("finished", key=key))
    assert all(layout == layouts[0] for layout in layouts)


def test_starting_and_finishing_other_files_does_not_resize_bars():
    console = Console(
        file=StringIO(),
        width=100,
        color_system="truecolor",
        no_color=False,
        legacy_windows=False,
    )
    progress = ExportProgress(console)
    progress.emit(Event("starting", "notes.pdf", "first"))
    progress.emit(Event("transferring", "notes.pdf", "first", total=1000))
    original = bar_positions(console, progress.files)[0]
    progress.emit(Event("starting", "Long course and file names " * 10, "second"))
    assert bar_positions(console, progress.files) == [original, original]
    progress.emit(Event("finished", key="second"))
    assert bar_positions(console, progress.files) == [original]


def test_overall_bar_is_stable_during_discovery_and_downloads():
    console = Console(
        file=StringIO(),
        width=100,
        color_system="truecolor",
        no_color=False,
        legacy_windows=False,
    )
    progress = ExportProgress(console)
    layouts = []
    for event in [
        Event("scanning", "Course / " + "Very long folder name " * 10),
        Event("discovered", amount=2),
        Event("discovered", amount=12000),
        Event("planned", total=12000),
        Event("finished", key="first"),
    ]:
        progress.emit(event)
        layouts.append(bar_positions(console, progress.overall)[0])
    assert layouts[0]
    assert all(layout == layouts[0] for layout in layouts)
