# Cookiecutter Nautobot App Integration Design

**Date:** 2026-03-10
**Status:** Approved

## Goal

Adopt the nautobot-app cookiecutter project conventions for build system, development infrastructure, CI/CD, and documentation structure. Keep all existing app Python code unchanged.

## Decisions

- **Build backend:** Poetry (poetry-core) with PEP 621 `[project]` table as single source of truth
- **Python management:** uv (`.python-version` kept)
- **Linting:** ruff replaces black + flake8; 120-char line length
- **Docs:** Restructure to cookiecutter layout (admin/user/dev subdirs) with mkdocs Material theme
- **CI/CD:** All four cookiecutter workflows (ci, coverage, release, upstream_testing)
- **Dev infra:** Docker Compose multi-file setup + invoke tasks
- **Changelog:** Towncrier with `changes/` directory

## Section 1: Build System (pyproject.toml)

### Structure

```toml
[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"

[project]
name = "nautobot-custom-tunnel-builder"
version = "0.2.3a1"
# ... all metadata in [project] table (source of truth)

[tool.poetry.group.dev.dependencies]
# ruff, pytest, invoke, coverage, yamllint, towncrier, pylint, etc.

[tool.poetry.group.docs.dependencies]
# mkdocs, mkdocs-material, mkdocstrings

[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP"]

[tool.towncrier]
# changelog fragment config
```

### Files Removed

- `requirements.txt`
- `uv.lock`
- `[tool.setuptools.*]` sections from pyproject.toml

### Files Generated

- `poetry.lock`

### Files Kept

- `.python-version` (uv python management)

## Section 2: Development Infrastructure

### `development/` directory (new)

```text
development/
├── docker-compose.base.yml      # Nautobot service definition
├── docker-compose.postgres.yml  # PostgreSQL service
├── docker-compose.redis.yml     # Redis service
├── docker-compose.dev.yml       # Nautobot + worker + beat
└── nautobot_config.py           # Dev Nautobot config (env-var driven)
```

### `tasks.py` (new, root-level invoke file)

Invoke tasks adapted from cookiecutter template:

- Docker: build, start, stop, restart, destroy, logs, cli
- Linting: ruff, yamllint, pylint
- Testing: unittest, coverage
- Migrations: makemigrations, check-migrations
- Docs: mkdocs serve

### `changes/` directory (new)

Towncrier changelog fragments directory with `.gitignore` placeholder.
Categories: added, changed, fixed, dependencies, documentation, housekeeping, breaking, security, deprecated, removed.

## Section 3: CI/CD Workflows

Replace existing single `release.yml` with all four cookiecutter workflows:

### `ci.yml`

- ruff format + lint
- yamllint, markdownlint
- Poetry lock check
- pylint (in Docker)
- unittest matrix (Python 3.11 + 3.13, PostgreSQL)
- Changelog validation (towncrier)

### `coverage.yml`

- Post-CI workflow for PR coverage comments

### `release.yml`

- Poetry build with tag/version validation
- Publish to GitHub release + PyPI (trusted publishing)

### `upstream_testing.yml`

- Scheduled bi-daily Nautobot compatibility testing
- Tests against nautobot develop/next/ltm branches

## Section 4: Documentation Restructure

### New layout (cookiecutter convention)

```text
docs/
├── index.md                         # includes README
├── admin/
│   ├── install.md                   # from: installation.md
│   ├── upgrade.md                   # new
│   ├── uninstall.md                 # new
│   ├── compatibility_matrix.md      # new
│   └── release_notes/
│       └── index.md                 # new
├── user/
│   ├── app_overview.md              # from: overview.md
│   ├── app_getting_started.md       # from: usage.md
│   ├── app_use_cases.md             # from: iosxe-config.md
│   └── faq.md                       # new stub
├── dev/
│   ├── contributing.md              # new (from template)
│   ├── dev_environment.md           # from: development.md
│   ├── release_checklist.md         # new (from template)
│   └── code_reference/
│       └── package.md               # new (mkdocstrings auto-gen)
└── assets/
    ├── extra.css                    # new
    └── nautobot_logo.svg            # new
```

### Content migration

| Old file | New location | Action |
|---|---|---|
| `docs/overview.md` | `docs/user/app_overview.md` | Move + adapt |
| `docs/installation.md` | `docs/admin/install.md` | Move + adapt |
| `docs/configuration.md` | merged into `docs/admin/install.md` | Merge |
| `docs/usage.md` | `docs/user/app_getting_started.md` | Move + adapt |
| `docs/iosxe-config.md` | `docs/user/app_use_cases.md` | Move + adapt |
| `docs/development.md` | `docs/dev/dev_environment.md` | Move + adapt |

### New files

- `mkdocs.yml` — Material theme, mkdocstrings, navigation structure
- `.readthedocs.yaml` (optional, add later if needed)

### Old files removed after migration

- `docs/overview.md`
- `docs/installation.md`
- `docs/configuration.md`
- `docs/usage.md`
- `docs/iosxe-config.md`
- `docs/development.md`

## Section 5: Other Updates

### `CLAUDE.md`

- Update commands section (ruff instead of black/flake8, poetry instead of pip, invoke tasks)

### `.yamllint.yml` (new)

- YAML linting config matching cookiecutter

### What Does NOT Change

- All app Python code (`__init__.py`, `jobs.py`, `forms.py`, `views.py`, `urls.py`, `navigation.py`)
- Templates (`ipsec_tunnel_form.html`)
- `.trunk/` (local linting config)
- `.python-version`
- `.claude/` settings

## Execution Order

1. Create feature branch
2. Rewrite `pyproject.toml` (Poetry + `[project]` table)
3. Delete `requirements.txt`, `uv.lock`
4. Generate `poetry.lock`
5. Create `development/` directory with compose files + nautobot_config.py
6. Create `tasks.py` (invoke)
7. Create `changes/` directory
8. Create `.yamllint.yml`
9. Replace `.github/workflows/` (all four workflow files)
10. Create `mkdocs.yml`
11. Restructure `docs/` to cookiecutter layout
12. Update `CLAUDE.md`
13. Update `readme.md` (project layout section)
14. Run ruff format on Python files
15. Verify poetry install works
