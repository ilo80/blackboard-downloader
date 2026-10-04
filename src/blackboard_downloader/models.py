"""Small shared values for course selection and export progress."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    ultra: bool = False


@dataclass(frozen=True)
class Download:
    course: Course
    url: str
    parent: Path
    name: str | None
    identity: str


@dataclass(frozen=True)
class Event:
    kind: str
    label: str = ""
    key: str = ""
    amount: int = 0
    total: int | None = None
