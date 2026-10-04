"""Display discovery, overall completion, and active transfer progress."""

from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.text import Text

from .models import Event


class ExportProgress:
    def __init__(self, console: Console):
        self.console = console
        self.overall = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}", markup=False),
            BarColumn(),
            MofNCompleteColumn(),
            TimeRemainingColumn(),
            console=console,
        )
        self.files = Progress(
            TextColumn("{task.description}", markup=False),
            BarColumn(),
            TaskProgressColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=console,
        )
        self.task = self.overall.add_task("Discovering course files", total=None)
        self.active: dict[str, int] = {}
        self.live = Live(
            Group(self.overall, self.files), console=console, refresh_per_second=8
        )

    def __enter__(self):
        self.live.start()
        return self

    def __exit__(self, *_):
        self.live.stop()

    def emit(self, event: Event) -> None:
        if event.kind == "scanning":
            self.overall.update(
                self.task,
                description=Text("Scanning: " + event.label, overflow="ellipsis"),
            )
        elif event.kind == "discovered":
            self.overall.update(
                self.task, description=f"Discovering files: {event.amount} found"
            )
        elif event.kind == "planned":
            self.overall.reset(
                self.task,
                description="Files processed",
                total=event.total,
            )
        elif event.kind == "starting":
            self.active[event.key] = self.files.add_task(
                Text(event.label, overflow="ellipsis"), total=None
            )
        elif event.kind == "transferring":
            self.files.update(
                self.active[event.key],
                description=Text(event.label, overflow="ellipsis"),
                total=event.total,
            )
        elif event.kind == "bytes":
            self.files.advance(self.active[event.key], event.amount)
        elif event.kind == "finished":
            if event.key in self.active:
                self.files.remove_task(self.active.pop(event.key))
            self.overall.advance(self.task)
        elif event.kind == "error":
            self.console.print(Text(event.label, style="yellow"))
