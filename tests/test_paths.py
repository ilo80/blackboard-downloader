"""Test portable filenames, stable collisions, and local path containment."""

import json

import pytest

from blackboard_downloader.errors import BlackboardError
from blackboard_downloader.paths import PathRegistry, safe_name


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("..", "untitled"),
        ("CON.txt", "_CON.txt"),
        ("a/b\\c", "a_b_c"),
        ("A &amp; B", "A & B"),
    ],
)
def test_portable_names(value, expected):
    assert safe_name(value) == expected
    assert len(safe_name("é" * 300).encode()) <= 180


def test_collisions_and_subset_reruns_keep_their_paths(tmp_path):
    registry = PathRegistry(tmp_path)
    first = registry.allocate(tmp_path, "Lecture.pdf", "first")
    second = registry.allocate(tmp_path, "LECTURE.pdf", "second")
    assert first.name.casefold() != second.name.casefold()
    registry.save()
    fresh = PathRegistry(tmp_path)
    assert fresh.allocate(tmp_path, "Renamed.pdf", "second") == second
    assert fresh.allocate(tmp_path, "Lecture.pdf", "first") == first


def test_unmanaged_files_are_not_overwritten(tmp_path):
    existing = tmp_path / "notes.pdf"
    existing.write_bytes(b"local file")
    registry = PathRegistry(tmp_path)
    assert registry.allocate(tmp_path, "notes.pdf", "remote") != existing
    assert existing.read_bytes() == b"local file"


@pytest.mark.parametrize("data", [[], {"../outside": {}}, {".": {"../file": "owner"}}])
def test_invalid_or_traversing_registry_is_rejected(tmp_path, data):
    (tmp_path / ".blackboard-paths.json").write_text(json.dumps(data))
    with pytest.raises(BlackboardError):
        PathRegistry(tmp_path)


def test_symlinks_cannot_escape_export(tmp_path):
    registry = PathRegistry(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("The platform does not permit unprivileged symlink creation.")
    with pytest.raises(BlackboardError, match="symbolic link"):
        registry.allocate(link, "file.pdf", "remote")


def test_long_colliding_names_still_load(tmp_path):
    registry = PathRegistry(tmp_path)
    title = "x" * 130 + "." + "y" * 49
    registry.allocate(tmp_path, title, "first")
    second = registry.allocate(tmp_path, title, "second")
    assert len(second.name.encode()) <= 180
    registry.save()
    assert PathRegistry(tmp_path).known(tmp_path, "second") == second
