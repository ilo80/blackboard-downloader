# Blackboard Downloader

A Python project for downloading files and folders from all or selected
Blackboard courses while preserving their existing hierarchy.

**Current status:** project initialization only. No downloading functionality,
Python modules, or entry points have been implemented yet.

## Installation

Requirements: Python 3.11 or later and Git.
From the repository root, on Windows (PowerShell):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Linux or macOS:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

The `.venv/` directory stays local and is not tracked by Git.
If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` instead of
`python` directly, without changing the system execution policy.

## Usage

The application will allow users to select courses and content to download,
then save them while preserving their organization. The launch command and
Blackboard configuration will be documented when implemented.

## Development and tests

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest
python -m build
```

Ruff provides linting and formatting; pytest will run tests in `tests/`.
Until tests are added, pytest reports "no tests ran" and exits with code 5.
No placeholder tests are included in this initialization.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## Directory structure

```text
blackboard-downloader/
|-- src/blackboard_downloader/  # Future Python package
|-- tests/                    # Future automated tests
|-- AGENTS.md                 # Repository guidelines
|-- CONTRIBUTING.md           # Contribution guide
|-- LICENSE                   # Full GPLv3 license text
|-- README.md
`-- pyproject.toml            # Metadata, dependencies, and tools
```

## License

Licensed under the GNU General Public License version 3 only (`GPL-3.0-only`).
See [LICENSE](LICENSE) for the full text.
