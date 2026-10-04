"""Optional local configuration and useful interactive defaults."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_URL = "https://blackboard.esiee.fr"


@dataclass(frozen=True)
class Settings:
    url: str = DEFAULT_URL
    output: Path = Path("downloads")
    username: str = ""
    password: str = field(default="", repr=False)

    @property
    def has_credentials(self) -> bool:
        return bool(self.username and self.password)


def read_settings(path: Path = Path(".env")) -> Settings:
    """Let the local file override the shell, without interpolating passwords."""
    values = {**os.environ, **dotenv_values(path, interpolate=False)}
    return Settings(
        url=values.get("BLACKBOARD_URL") or DEFAULT_URL,
        output=Path(values.get("BLACKBOARD_OUTPUT") or "downloads").expanduser(),
        username=values.get("BLACKBOARD_USERNAME") or "",
        password=values.get("BLACKBOARD_PASSWORD") or "",
    )
