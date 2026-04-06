# Package Rename Design

**Date:** 2026-03-10
**Status:** Approved

## Goal

Adopt Nautobot app naming conventions by removing `_app` / `-app` from the Python package name and PyPI distribution name. The GitHub repo name does not change.

## Naming Convention

| Context | Current | New |
|---|---|---|
| GitHub repo | `nautobot-app-custom-tunnel-builder` | **no change** |
| PyPI distribution | `nautobot-app-custom-tunnel-builder` | `nautobot-custom-tunnel-builder` |
| Python package dir | `nautobot_app_custom_tunnel_builder/` | `nautobot_custom_tunnel_builder/` |
| Python import path | `nautobot_app_custom_tunnel_builder` | `nautobot_custom_tunnel_builder` |
| AppConfig class | `NautobotAppCustomTunnelBuilderConfig` | `NautobotCustomTunnelBuilderConfig` |
| AppConfig.name | `"nautobot_app_custom_tunnel_builder"` | `"nautobot_custom_tunnel_builder"` |
| Django app label | `nautobot_app_custom_tunnel_builder` | `nautobot_custom_tunnel_builder` |

## Migration Strategy

**Breaking change.** Users uninstall the old package and install the new one. No Django data migration is provided. After reinstalling, users run `nautobot-server migrate` to re-register the job.

## Changes By Category

### 1. Directory Renames

| Current Path | New Path |
|---|---|
| `nautobot_app_custom_tunnel_builder/` | `nautobot_custom_tunnel_builder/` |
| `.../templates/nautobot_app_custom_tunnel_builder/` | `.../templates/nautobot_custom_tunnel_builder/` |
| `nautobot_app_custom_tunnel_builder.egg-info/` | Delete (auto-regenerated) |

### 2. Python Source Files

**`__init__.py`** (4 changes):

- `get_version("nautobot_app_custom_tunnel_builder")` → `get_version("nautobot-custom-tunnel-builder")` (use PyPI distribution name)
- `class NautobotAppCustomTunnelBuilderConfig` → `NautobotCustomTunnelBuilderConfig`
- `name = "nautobot_app_custom_tunnel_builder"` → `"nautobot_custom_tunnel_builder"`
- `config = NautobotAppCustomTunnelBuilderConfig` → `NautobotCustomTunnelBuilderConfig`

**`views.py`** (3 changes):

- `JOB_CLASS_PATH` string → `"nautobot_custom_tunnel_builder.jobs.BuildIpsecTunnel"`
- `template_name` → `"nautobot_custom_tunnel_builder/ipsec_tunnel_form.html"`
- `module_name=` → `"nautobot_custom_tunnel_builder.jobs"`

**`urls.py`** (1 change):

- `app_name` → `"nautobot_custom_tunnel_builder"`

**`navigation.py`** (2 changes):

- Both `link=` strings → `"plugins:nautobot_custom_tunnel_builder:ipsec_tunnel_builder"`

### 3. Build Configuration

**`pyproject.toml`** (3 changes):

- `name = "nautobot-app-custom-tunnel-builder"` → `"nautobot-custom-tunnel-builder"`
- `include = ["nautobot_app_custom_tunnel_builder*"]` → `["nautobot_custom_tunnel_builder*"]`
- `"nautobot_app_custom_tunnel_builder" = [` → `"nautobot_custom_tunnel_builder" = [`

**`uv.lock`** — regenerate after pyproject.toml changes.

### 4. Documentation

**`readme.md`**:

- `PLUGINS = ["nautobot_app_custom_tunnel_builder"]` → `["nautobot_custom_tunnel_builder"]`
- Directory tree references (underscore form)
- pip install / PyPI references (dash form)
- Note: GitHub URLs with the repo name (`nautobot-app-custom-tunnel-builder`) do NOT change

**`docs/installation.md`**:

- PLUGINS config examples (underscore form)
- pip install / wheel filename references (dash form)
- git clone URL does NOT change (repo name unchanged)

**`docs/configuration.md`**:

- `"nautobot_app_custom_tunnel_builder": {` → `"nautobot_custom_tunnel_builder": {`

**`docs/development.md`**:

- Directory tree listings
- Import paths
- PLUGINS config
- Lint/format commands (`black`, `flake8`)
- Template path references

**`docs/overview.md`**:

- Dash-form name references in description text

### 5. Project Guidance

**`CLAUDE.md`**:

- Lint command: `flake8 nautobot_app_custom_tunnel_builder/` → `nautobot_custom_tunnel_builder/`
- Format command: `black nautobot_app_custom_tunnel_builder/` → `nautobot_custom_tunnel_builder/`
- Class name reference: `NautobotAppCustomTunnelBuilderConfig` → `NautobotCustomTunnelBuilderConfig`

### 6. Things That Do NOT Change

- **GitHub repo name**: `nautobot-app-custom-tunnel-builder` (all GitHub URLs stay)
- **Git clone URLs**: point to repo name, unchanged
- **Base URL path**: `tunnel-builder` / `/plugins/tunnel-builder/` (defined in urls.py path, not the package name)
- **Job class name**: `BuildIpsecTunnel`
- **Form class name**: `IpsecTunnelForm`
- **View class name**: `IpsecTunnelBuilderView`
- **Template filename**: `ipsec_tunnel_form.html` (only the directory changes)

## Execution Order

1. Rename `nautobot_app_custom_tunnel_builder/` directory → `nautobot_custom_tunnel_builder/`
2. Rename inner templates directory
3. Update all Python source files
4. Update `pyproject.toml`
5. Delete `.egg-info/` directory
6. Regenerate `uv.lock`
7. Update all documentation
8. Update `CLAUDE.md`
9. Reinstall package (`pip install -e ".[dev]"`)
10. Run tests to verify
