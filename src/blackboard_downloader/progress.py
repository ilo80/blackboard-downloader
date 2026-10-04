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
from rich.table import Column
from rich.text import Text

from .models import Event


class ExportProgress:
    def __init__(self, console: Console):
        self.console = console
        description_width = min(32, max(12, console.width // 3))
        self.overall = Progress(
            SpinnerColumn(table_column=Column(width=1, no_wrap=True)),
            TextColumn(
                "{task.description}",
                markup=False,
                table_column=Column(width=description_width, no_wrap=True),
            ),
            BarColumn(bar_width=None, table_column=Column(ratio=1)),
            MofNCompleteColumn(table_column=Column(width=13, no_wrap=True)),
            TimeRemainingColumn(table_column=Column(width=8, no_wrap=True)),
            console=console,
            expand=True,
        )
        self.files = Progress(
            TextColumn(
                "{task.description}",
                markup=False,
                table_column=Column(width=description_width, no_wrap=True),
            ),
            BarColumn(bar_width=None, table_column=Column(ratio=1)),
            TaskProgressColumn(table_column=Column(width=4, no_wrap=True)),
            DownloadColumn(table_column=Column(width=17, no_wrap=True)),
            TransferSpeedColumn(table_column=Column(width=12, no_wrap=True)),
            TimeRemainingColumn(table_column=Column(width=8, no_wrap=True)),
            console=console,
            expand=True,
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
