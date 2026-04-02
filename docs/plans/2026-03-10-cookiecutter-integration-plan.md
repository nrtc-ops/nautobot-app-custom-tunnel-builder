# Cookiecutter Nautobot App Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adopt nautobot-app cookiecutter conventions for build system, dev infra, CI/CD, and docs.

**Architecture:** Rewrite pyproject.toml for Poetry + PEP 621, add Docker Compose dev environment with invoke tasks, replace CI workflows, restructure docs to cookiecutter layout with mkdocs. No app Python code changes.

**Tech Stack:** Poetry (build), uv (Python mgmt), ruff (lint/format), invoke (tasks), Docker Compose (dev env), mkdocs-material (docs), towncrier (changelog), GitHub Actions (CI/CD)

**Reference project:** `/Users/mdean/Desktop/devsecops/github/cookiecutter-nautobot-app/nautobot-app/{{ cookiecutter.project_slug }}/`

**Variable mapping (cookiecutter → our values):**

| Variable | Value |
|---|---|
| `app_name` | `nautobot_custom_tunnel_builder` |
| `app_slug` | `nautobot-custom-tunnel-builder` |
| `project_slug` | `nautobot-app-custom-tunnel-builder` (repo) |
| `verbose_name` | `Custom Tunnel Builder` |
| `camel_name` | `CustomTunnelBuilder` |
| `full_name` | `NRTC Ops` |
| `github_org` | `nrtc-ops` |
| `base_url` | `tunnel-builder` |
| `repo_url` | `https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder` |
| `min_nautobot_version` | `3.0.0` |
| `upper_bound_nautobot_version` | `4.0.0` |
| PyPI name | `nautobot-custom-tunnel-builder` |

---

## Task 1: Create Feature Branch

### Step 1: Create and checkout branch

```bash
git checkout -b feature/cookiecutter-integration
```

### Step 2: Commit design docs

```bash
git add docs/plans/
git commit -m "docs: add cookiecutter integration design and plan"
```

---

## Task 2: Rewrite pyproject.toml

**Files:**

- Modify: `pyproject.toml`

### Step 1: Rewrite pyproject.toml

Replace the entire file. Key decisions:

- `[build-system]` uses `poetry-core`
- `[project]` table is source of truth (PEP 621)
- Dev/docs deps go in `[tool.poetry.group.*]`
- `[tool.ruff]` replaces black + flake8
- `[tool.towncrier]` for changelog
- `[tool.pylint]` for pylint config
- `[tool.coverage]` for test coverage
- Remove all `[tool.setuptools.*]` sections

Reference: cookiecutter `pyproject.toml` — resolve all `{{ cookiecutter.* }}` and `{{ min_nautobot_version }}` templates with our variable mapping above.

Key adaptations from the cookiecutter template:

- Keep `nautobot>=3.0.0,<4.0.0` and `netmiko>=4.0.0` as runtime deps
- Drop `build`, `pip`, `twine` from runtime deps (those are build/publish tools, not runtime)
- Python `>=3.11,<3.14` (match current project's 3.11 minimum)
- Add `[tool.poetry]` section with `packages` config pointing to `nautobot_custom_tunnel_builder`

*We want to make sure that we keep uv related info in the pyproject.toml, and use as much we can in the project table for poetry.

### Step 2: Verify syntax

```bash
python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb')); print('OK')"
```

---

## Task 3: Delete Old Files, Generate poetry.lock

**Files:**

- Delete: `requirements.txt`
- Delete: `uv.lock`
- Generate: `poetry.lock`

### Step 1: Delete old files

```bash
rm requirements.txt uv.lock
```

### Step 2: Install Poetry if needed

```bash
which poetry || pip install poetry
```

### Step 3: Generate lock file

```bash
poetry lock
```

### Step 4: Install and verify

```bash
poetry install
```

### Step 5: Commit

```bash
git add pyproject.toml poetry.lock
git rm requirements.txt uv.lock
git commit -m "build: switch from setuptools to Poetry with PEP 621 project table"
```

---

## Task 4: Create development/ Directory

**Files:**

- Create: `development/docker-compose.base.yml`
- Create: `development/docker-compose.postgres.yml`
- Create: `development/docker-compose.redis.yml`
- Create: `development/docker-compose.dev.yml`
- Create: `development/nautobot_config.py`
- Create: `development/creds.env`
- Create: `development/development.env`

Reference: cookiecutter `development/` files — resolve all templates with our variable mapping.

### Step 1: Create development directory

```bash
mkdir -p development
```

### Step 2: Create docker-compose.base.yml

Adapt from cookiecutter template. Key customizations:

- Image name: `nautobot-custom-tunnel-builder-nautobot`
- Build args: `NAUTOBOT_VER`, `PYTHON_VER`
- Environment files: `development/development.env`, `development/creds.env`

### Step 3: Create docker-compose.postgres.yml

PostgreSQL 17-alpine service with health check, creds.env, persistent volume.

### Step 4: Create docker-compose.redis.yml

Redis 6-alpine with appendonly and password auth.

### Step 5: Create docker-compose.dev.yml

Development overrides: port 8080 for Nautobot, port 8001 for docs, volume mounts for source code and nautobot_config.py, watchmedo for worker/beat auto-restart.

### Step 6: Create nautobot_config.py

Adapt from cookiecutter template. Key customizations:

- `PLUGINS = ["nautobot_custom_tunnel_builder"]`
- Database config from env vars (PostgreSQL default)
- Debug toolbar integration
- Redis cache/celery config
- Logging configuration

### Step 7: Create creds.env

```text
NAUTOBOT_DB_USER=nautobot
NAUTOBOT_DB_PASSWORD=decinablesprewl
NAUTOBOT_NAPALM_PASSWORD=
NAUTOBOT_SECRET_KEY=r8OwDznj!!dci#P9ghmRfdu1Ysxm0AiPeDCQhKE+N_rClfWNj
NAUTOBOT_REDIS_PASSWORD=decinablesprewl
NAUTOBOT_DEVICE_USERNAME=admin
NAUTOBOT_DEVICE_PASSWORD=admin
POSTGRES_USER=nautobot
POSTGRES_PASSWORD=decinablesprewl
POSTGRES_DB=nautobot
```

### Step 8: Create development.env

```text
NAUTOBOT_DB_ENGINE=django.db.backends.postgresql
NAUTOBOT_DB_HOST=db
NAUTOBOT_DB_NAME=nautobot
NAUTOBOT_DB_PORT=5432
NAUTOBOT_REDIS_HOST=redis
NAUTOBOT_REDIS_PORT=6379
NAUTOBOT_CONFIG=/opt/nautobot/nautobot_config.py
NAUTOBOT_DEBUG=True
NAUTOBOT_ALLOWED_HOSTS=*
NAUTOBOT_CHANGELOG_RETENTION=0
NAUTOBOT_LOG_LEVEL=DEBUG
```

### Step 9: Commit

```bash
git add development/
git commit -m "feat: add Docker Compose development environment"
```

---

## Task 5: Create tasks.py (Invoke)

**Files:**

- Create: `tasks.py`

### Step 1: Create tasks.py

Adapt from cookiecutter template. Key customizations:

- `namespace.configure` with `project_name = "custom-tunnel-builder"`
- Compose files list matching our `development/` directory
- Resolve all `{{ cookiecutter.* }}` references
- `INVOKE_NAUTOBOT_CUSTOM_TUNNEL_BUILDER_*` env var prefix

Key tasks to include:

- Docker: `build`, `start`, `stop`, `restart`, `destroy`, `debug`, `logs`, `cli`
- Linting: `ruff`, `pylint`, `yamllint`, `markdownlint`
- Testing: `unittest`, `tests` (runs all linters + tests)
- Migrations: `makemigrations`, `check-migrations`
- Docs: `docs`, `build-and-check-docs`
- Utility: `create-user`, `nbshell`, `shell-plus`

### Step 2: Verify tasks load

```bash
invoke --list
```

### Step 3: Commit

```bash
git add tasks.py
git commit -m "feat: add invoke tasks for development workflow"
```

---

## Task 6: Create changes/ Directory and Config Files

**Files:**

- Create: `changes/.gitignore`
- Create: `.yamllint.yml`
- Create: `.markdownlint.yml` (if not already in `.trunk/configs/`)

### Step 1: Create changes directory with .gitignore

```bash
mkdir -p changes
```

The `.gitignore` should contain a single line to keep the directory tracked:

```text
!.gitignore
```

### Step 2: Create .yamllint.yml

Adapt from cookiecutter. Disable empty-values and line-length. Ignore .venv/.

### Step 3: Commit

```bash
git add changes/ .yamllint.yml
git commit -m "feat: add towncrier changes directory and yamllint config"
```

---

## Task 7: Replace .github/workflows/

**Files:**

- Delete: `.github/workflows/release.yml` (old)
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/coverage.yml`
- Create: `.github/workflows/release.yml` (new)
- Create: `.github/workflows/upstream_testing.yml`

### Step 1: Create ci.yml

Adapt from cookiecutter template. Key customizations:

- Resolve all `{{ cookiecutter.* }}` with our values
- Python versions: `"3.11"` and `"3.13"` (instead of 3.10/3.13)
- `invoke_context_name: "NAUTOBOT_CUSTOM_TUNNEL_BUILDER"` (app_name uppercased)
- GitHub org/repo references: `nrtc-ops/nautobot-app-custom-tunnel-builder`
- PostgreSQL only (no MySQL in matrix)

Jobs to include:

- `generate-lockfile` — Poetry lock regeneration
- `ruff-format` and `ruff-lint` — Code style
- `check-docs-build` — MkDocs validation
- `poetry` — Lock file integrity
- `yamllint` — YAML linting
- `check-in-docker` — Docker build, pylint
- `unittest` — Matrix testing
- `unittest_report` — Coverage reporting
- `changelog` — Towncrier validation on PRs

### Step 2: Create coverage.yml

Post-CI workflow for PR coverage comments. Adapt from cookiecutter template.

### Step 3: Create release.yml (new version)

Poetry-based release pipeline. Key customizations:

- Tag validation against `[project] version` in pyproject.toml
- Poetry build (not setuptools)
- GitHub release upload + PyPI trusted publishing

### Step 4: Create upstream_testing.yml

Scheduled Nautobot compatibility testing. Adapt from cookiecutter template with:

- `invoke_context_name: "NAUTOBOT_CUSTOM_TUNNEL_BUILDER"`
- `app_name: "custom-tunnel-builder"`

### Step 5: Commit

```bash
git add .github/workflows/
git commit -m "ci: replace workflows with cookiecutter convention (ci, coverage, release, upstream)"
```

---

## Task 8: Create mkdocs.yml

**Files:**

- Create: `mkdocs.yml`

### Step 1: Create mkdocs.yml

Adapt from cookiecutter template. Key customizations:

- `site_dir: "nautobot_custom_tunnel_builder/static/nautobot_custom_tunnel_builder/docs"`
- `site_name: "Custom Tunnel Builder Documentation"`
- `repo_url: "https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder"`
- Navigation structure adapted to our actual doc files (no models section since we have no models)
- Remove conditional model_class_name sections

### Step 2: Commit

```bash
git add mkdocs.yml
git commit -m "docs: add mkdocs configuration with Material theme"
```

---

## Task 9: Restructure docs/

**Files:**

- Create: `docs/index.md`
- Move: `docs/overview.md` → `docs/user/app_overview.md`
- Move: `docs/installation.md` + `docs/configuration.md` → `docs/admin/install.md`
- Move: `docs/usage.md` → `docs/user/app_getting_started.md`
- Move: `docs/iosxe-config.md` → `docs/user/app_use_cases.md`
- Move: `docs/development.md` → `docs/dev/dev_environment.md`
- Create: `docs/admin/upgrade.md`
- Create: `docs/admin/uninstall.md`
- Create: `docs/admin/compatibility_matrix.md`
- Create: `docs/admin/release_notes/index.md`
- Create: `docs/user/faq.md`
- Create: `docs/dev/contributing.md`
- Create: `docs/dev/release_checklist.md`
- Create: `docs/dev/code_reference/package.md`
- Copy: `docs/assets/` (from cookiecutter template for favicon, logos, css)
- Delete: old flat docs files

### Step 1: Create directory structure

```bash
mkdir -p docs/admin/release_notes docs/user docs/dev/code_reference docs/assets
```

### Step 2: Create docs/index.md

```markdown
---
hide:
  - navigation
---

--8<-- "readme.md"
```

### Step 3: Move and adapt existing docs

For each moved file, the content stays largely the same but headers/links may need updating to reflect new relative paths. The key content migrations:

- `overview.md` → `user/app_overview.md` (keep as-is, it's already good)
- `installation.md` + `configuration.md` → `admin/install.md` (merge into single install guide)
- `usage.md` → `user/app_getting_started.md` (keep as-is)
- `iosxe-config.md` → `user/app_use_cases.md` (keep as-is)
- `development.md` → `dev/dev_environment.md` (keep as-is, update code style section for ruff)

### Step 4: Create new stub docs

Create from cookiecutter templates with our values substituted:

- `admin/upgrade.md` — post_upgrade instructions
- `admin/uninstall.md` — migration rollback + pip uninstall
- `admin/compatibility_matrix.md` — version matrix table
- `admin/release_notes/index.md` — release notes index
- `user/faq.md` — empty placeholder
- `dev/contributing.md` — changelog fragments, branching, code standards (ruff)
- `dev/release_checklist.md` — Poetry version bumping, towncrier, release process
- `dev/code_reference/package.md` — mkdocstrings reference

### Step 5: Copy assets from cookiecutter

```bash
cp /Users/mdean/Desktop/devsecops/github/cookiecutter-nautobot-app/nautobot-app/\{\{\ cookiecutter.project_slug\ \}\}/docs/assets/extra.css docs/assets/
cp /Users/mdean/Desktop/devsecops/github/cookiecutter-nautobot-app/nautobot-app/\{\{\ cookiecutter.project_slug\ \}\}/docs/assets/favicon.ico docs/assets/
cp /Users/mdean/Desktop/devsecops/github/cookiecutter-nautobot-app/nautobot-app/\{\{\ cookiecutter.project_slug\ \}\}/docs/assets/nautobot_logo.svg docs/assets/
```

### Step 6: Delete old flat files

```bash
git rm docs/overview.md docs/installation.md docs/configuration.md docs/usage.md docs/iosxe-config.md docs/development.md
```

### Step 7: Commit

```bash
git add docs/
git commit -m "docs: restructure to cookiecutter layout (admin/user/dev)"
```

---

## Task 10: Update CLAUDE.md and readme.md

**Files:**

- Modify: `CLAUDE.md`
- Modify: `readme.md`

### Step 1: Update CLAUDE.md commands section

Replace the commands section with Poetry/ruff/invoke equivalents:

```bash
# Install with Poetry
poetry install

# Run tests
invoke unittest
# or directly:
poetry run pytest

# Lint
invoke ruff

# Format
poetry run ruff format nautobot_custom_tunnel_builder/

# Build distribution
poetry build

# Docker dev environment
invoke build
invoke start
invoke stop

# After any model/migration changes
invoke makemigrations
```

### Step 2: Update readme.md

Update the Project Layout section to reflect new directory structure. Update Quick Start section to reference Poetry.

### Step 3: Commit

```bash
git add CLAUDE.md readme.md
git commit -m "docs: update CLAUDE.md and readme for Poetry and invoke workflow"
```

---

## Task 11: Run ruff Format and Final Verification

### Step 1: Run ruff format on all Python files

```bash
poetry run ruff format nautobot_custom_tunnel_builder/ tasks.py development/nautobot_config.py
```

### Step 2: Run ruff lint

```bash
poetry run ruff check nautobot_custom_tunnel_builder/ tasks.py --fix
```

### Step 3: Verify Python files parse

```bash
python -c "
import ast, pathlib
for f in pathlib.Path('nautobot_custom_tunnel_builder').rglob('*.py'):
    ast.parse(f.read_text())
    print(f'{f}: OK')
"
```

### Step 4: Verify poetry install works

```bash
poetry install
```

### Step 5: Verify invoke loads

```bash
invoke --list
```

### Step 6: Commit any formatting changes

```bash
git add -A
git commit -m "style: run ruff format across codebase"
```

---

## Task 12: Update Auto-Memory

**Files:**

- Modify: `/Users/mdean/.claude/projects/-Users-mdean-Desktop-devsecops-github-nrtc-ops-nautobot-app-custom-tunnel-builder/memory/MEMORY.md`

Update the memory file to reflect the new build system, tooling, and file locations.

---

## Verification Checklist

After all tasks complete, verify:

- [ ] `poetry install` succeeds
- [ ] `poetry run ruff check nautobot_custom_tunnel_builder/` passes
- [ ] `poetry run ruff format --check nautobot_custom_tunnel_builder/` passes
- [ ] `invoke --list` shows all tasks
- [ ] `pyproject.toml` has `[project]` table with version as source of truth
- [ ] `docs/` follows cookiecutter layout (admin/user/dev)
- [ ] `.github/workflows/` has ci.yml, coverage.yml, release.yml, upstream_testing.yml
- [ ] `development/` has compose files + nautobot_config.py
- [ ] `changes/` directory exists
- [ ] No references to `black`, `flake8`, `setuptools`, or `requirements.txt` remain
- [ ] All Python files parse without syntax errors
