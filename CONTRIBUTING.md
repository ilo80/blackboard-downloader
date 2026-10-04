# Contributing

## Environment

Follow the installation instructions in the [README](README.md), then work
inside the `.venv` environment. Development dependencies are declared in
`pyproject.toml`; no application dependencies have been selected yet.

## Code, documentation, and tests

- Write all project content in English, including documentation, identifiers,
  comments, docstrings, and tests.
- Place the package in `src/blackboard_downloader/` and tests in `tests/`.
- Keep modules readable and reuse existing libraries and utilities where
  appropriate.
- Add or update tests for each behavior change.
- Run `python -m ruff check .`, `python -m ruff format --check .`, and
  `python -m pytest` before committing. During initialization, the absence of
  code and tests is expected; pytest exits with code 5.
- Keep documentation consistent with the available functionality.
- Do not track Blackboard credentials, cookies, tokens, or downloaded files.
  Use `downloads/` for local downloads.

## Git

- Create a dedicated branch for each change.
- Use [Conventional Commits](https://www.conventionalcommits.org/), such as
  `chore: initialize project` or `feat: download course files`.
- Keep commits focused and easy to review.
- Give pull requests clear titles and brief descriptions of the purpose,
  changes, and verification performed.
- Agents must commit their completed work locally and must never push.

See [AGENTS.md](AGENTS.md) for the complete repository guidelines.
