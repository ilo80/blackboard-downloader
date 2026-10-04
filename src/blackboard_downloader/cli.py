"""Launch one interactive workflow, with a default for every question."""

import asyncio
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from .auth import browser_login
from .client import BlackboardClient, validate_url
from .config import read_settings
from .errors import BlackboardError
from .exporter import Exporter
from .models import Course
from .progress import ExportProgress


def parse_selection(value: str, count: int) -> list[int]:
    """Parse visible course numbers, ranges, or all; return zero-based positions."""
    value = value.strip().casefold()
    if value in ("", "all", "*"):
        return list(range(count))
    if not re.fullmatch(r"\d+(?:\s*-\s*\d+)?(?:[\s,]+\d+(?:\s*-\s*\d+)?)*", value):
        raise ValueError("Use 'all', course numbers (1,3), or ranges (2-5).")
    result = set()
    for group in re.split(r"[\s,]+", re.sub(r"\s*-\s*", "-", value)):
        numbers = [int(number) for number in group.split("-")]
        start, end = numbers[0], numbers[-1]
        if start < 1 or end > count or start > end:
            raise ValueError(f"Choose course numbers between 1 and {count}.")
        result.update(range(start - 1, end))
    return sorted(result)


def select_courses(courses: list[Course], console: Console) -> list[Course]:
    table = Table(title="Your Blackboard courses", show_lines=False)
    table.add_column("#", justify="right", style="cyan", no_wrap=True)
    table.add_column("Course name")
    for number, course in enumerate(courses, start=1):
        table.add_row(str(number), Text(course.name))
    console.print(table)
    while True:
        answer = Prompt.ask(
            "Courses to download (numbers, ranges, or all)",
            default="all",
            console=console,
        )
        try:
            return [courses[index] for index in parse_selection(answer, len(courses))]
        except ValueError as exc:
            console.print(Text(str(exc), style="yellow"))


def select_output(default: Path, console: Console) -> Path:
    while True:
        answer = Prompt.ask("Output folder", default=str(default), console=console)
        path = Path(answer).expanduser()
        if path.exists() and not path.is_dir():
            console.print("[yellow]Choose a directory, not an existing file.[/yellow]")
            continue
        return path


async def run(console: Console) -> int:
    settings = read_settings()
    console.print("[bold cyan]Blackboard Downloader[/bold cyan]")
    while True:
        url = Prompt.ask("Blackboard server", default=settings.url, console=console)
        try:
            validate_url(url)
            break
        except ValueError as exc:
            console.print(Text(str(exc), style="yellow"))
    async with BlackboardClient(url) as client:
        choices = ["browser", "configured"] if settings.has_credentials else ["browser"]
        method = Prompt.ask(
            "Sign-in method",
            choices=choices,
            default="configured" if settings.has_credentials else "browser",
            console=console,
        )
        if method == "configured":
            with console.status("Signing in with configured credentials..."):
                await client.login(settings.username, settings.password)
        else:
            console.print(
                "Sign in in the browser window (SSO/MFA supported). "
                "This continues automatically when you are connected."
            )
            with console.status("Waiting for browser sign-in..."):
                await browser_login(client)
        with console.status("Loading your course names..."):
            courses = await client.courses()
        if not courses:
            console.print("No enrolled courses were found.")
            return 0
        selected = select_courses(courses, console)
        output = select_output(settings.output, console)
        overwrite = False
        if (output / ".blackboard-paths.json").exists():
            overwrite = Confirm.ask(
                "Download existing files again?", default=False, console=console
            )
        console.print(
            Text(f"Downloading {len(selected)} course(s) to {output.resolve()}.")
        )
        with ExportProgress(console) as progress:
            exporter = Exporter(
                client, output, overwrite=overwrite, on_event=progress.emit
            )
            report = await exporter.run(selected)
        console.print(
            f"Downloaded: {report['downloaded']} | Already present: {report['skipped']} "
            f"| Errors: {len(report['errors'])}"
        )
        console.print(Text(f"Report: {exporter.output / 'report.json'}"))
        return 1 if report["errors"] else 0


def main() -> int:
    """Provide the console script and module entry point without download flags."""
    console = Console()
    if len(sys.argv) > 1:
        console.print(
            "Run 'blackboard-downloader' without arguments for the guided flow."
        )
        return 0 if sys.argv[1:] in (["--help"], ["-h"]) else 2
    try:
        return asyncio.run(run(console))
    except KeyboardInterrupt:
        console.print("\nCancelled. Completed files are kept; launch again to resume.")
        return 130
    except (BlackboardError, ValueError, OSError, EOFError) as exc:
        console.print(Text(str(exc) or "Interactive input was closed.", style="red"))
        return 1
