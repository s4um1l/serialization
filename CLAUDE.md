# Serialization

## Python & Package Management

- Use **uv** for all Python package management (never pip/requirements.txt)
- Use `pyproject.toml` for project config — no setup.py or requirements.txt
- `uv init` to bootstrap new projects
- `uv add <pkg>` to add dependencies
- `uv add --group dev <pkg>` for dev dependencies
- `uv run` to execute scripts and commands
- `uv sync` to install from lockfile

## Git Commits

- Commit at every meaningful progress point — don't batch everything at the end
- Write short, imperative commit messages
- Do NOT include `Co-Authored-By` lines referencing Claude or Anthropic
