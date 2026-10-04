# Blackboard Downloader

Download files from selected Blackboard courses through a guided terminal workflow.
Course names and folder hierarchies are preserved. Original attachments and Ultra
BbML files are supported, including embedded Blackboard images and media.

## Installation

Requires Python 3.11+ and Chrome or Edge. From the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

On Linux/macOS, use `python3 -m venv .venv` and `source .venv/bin/activate`.
If PowerShell blocks activation, run `.\.venv\Scripts\python.exe` directly.
If Chrome/Edge is unavailable, install the browser used for authentication:

```sh
python -m playwright install chromium
```

## Usage

```sh
blackboard-downloader
# Equivalent:
python -m blackboard_downloader
```

The application guides you through:

1. Blackboard server: defaults to `https://blackboard.esiee.fr`, as in the prototype.
2. Sign-in: defaults to a browser window; sign in normally, including SSO/MFA.
   The application detects the authenticated session and continues automatically.
3. Courses: a numbered list of **real course names**. Enter `1,3`, `2-5`, or `all`.
   Press Enter to download **all courses**.
4. Output folder: defaults to `downloads/`.
5. On subsequent runs, whether to download existing files again: defaults to **no**.

Every question has a visible default. There are no course IDs or download flags
to supply. Discovery displays the current course/item and the file count; downloads
show overall completion and active transfers with bytes, speed, and estimated time.

An optional `.env` in the current directory can set the defaults in
[.env.example](.env.example). If both `BLACKBOARD_USERNAME` and
`BLACKBOARD_PASSWORD` are configured, classic form login becomes the default;
browser login remains available. File values override shell values, and passwords
are read literally without `${...}` interpolation. Cookies are kept in memory.

## Downloads and recovery

Files are stored in `downloads/courses/Course name/`, preserving nested and empty
folders. Standalone files retain their filenames; documents with attachments use
their titles as directories. Eight concurrent workers reuse HTTP connections and
stream files to disk. Temporary HTTP failures are retried with backoff; rate-limit
responses respect `Retry-After`.

Keep `.blackboard-paths.json` with your export: it stabilizes colliding names and
lets reruns skip completed files before requesting them. Transfers publish files
atomically, so failures and Ctrl+C preserve existing files. Partial file transfers
restart on the next run. Unrelated local files are not overwritten.

`report.json` records downloaded/skipped counts and errors. An inaccessible course
or file does not prevent the others from downloading. An expired session stops the
run. Exit codes: `0` for success, `1` for an incomplete export or expected failure,
`2` for unsupported arguments, and `130` for Ctrl+C.

Only files exposed to your account are downloaded. LTI tools and third-party video
services are excluded. Public content APIs follow the
[Blackboard reference](https://developer.blackboard.com/portal/displayApi) and
[attachment guide](https://docs.blackboard.com/docs/blackboard/rest-apis/demo-code/curl-attach-demo).
Browser/form authentication uses the prototype's web-session endpoint
`/learn/api/v1/users/me`; availability of cookie-authenticated APIs depends on your
institution. This project does not require an administrator OAuth application.

## Tests

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest
python -m build
```

The automated suite runs offline using simulated HTTP responses and browser
sessions. It covers interactive defaults, authentication, pagination, concurrency,
hierarchy, name collisions, resuming, cancellation, and failed transfers.

## Directory structure

```text
src/blackboard_downloader/
  cli.py, progress.py         # Interactive workflow and terminal progress
  auth.py, client.py          # Browser/form authentication and bounded HTTP access
  content.py, exporter.py     # File discovery and concurrent streaming downloads
  paths.py                   # Safe stable paths and atomic persistence
  config.py, models.py        # Configuration defaults and shared data
tests/                       # Offline automated tests
.env.example                 # Optional local settings
pyproject.toml               # Package, command, dependencies, and development tools
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.
Licensed under [GPL-3.0-only](LICENSE).
