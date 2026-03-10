# Development Guide

## Project Structure

```
nautobot-app-custom-tunnel-builder/
├── pyproject.toml                              # Package metadata and build config
├── requirements.txt                            # Runtime dependencies
├── docs/                                       # This documentation
│   ├── overview.md
│   ├── installation.md
│   ├── configuration.md
│   ├── usage.md
│   ├── iosxe-config.md
│   └── development.md
└── nautobot_custom_tunnel_builder/             # Python package
    ├── __init__.py                             # NautobotAppConfig
    ├── forms.py                                # Django form
    ├── jobs.py                                 # Nautobot Job + config builder
    ├── navigation.py                           # Nav menu items
    ├── urls.py                                 # URL routing
    ├── views.py                                # Custom CBV
    └── templates/
        └── nautobot_custom_tunnel_builder/
            └── ipsec_tunnel_form.html          # Bootstrap 5 form template
```

---

## Setting Up a Development Environment

### 1. Clone the repo

```bash
git clone https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder.git
cd nautobot-app-custom-tunnel-builder
```

### 2. Create a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 3. Install in editable mode with dev dependencies

```bash
pip install -e ".[dev]"
```

### 4. Point at an existing Nautobot instance

Set `NAUTOBOT_CONFIG` to your config file, then run the Nautobot development server:

```bash
export NAUTOBOT_CONFIG=/opt/nautobot/nautobot_config.py
nautobot-server runserver
```

Make sure the app is listed in `PLUGINS` in that config file.

---

## Code Map

### `__init__.py` — App Registration

Defines `NautobotCustomTunnelBuilderConfig(NautobotAppConfig)`. This is the Django AppConfig subclass Nautobot discovers when `nautobot_custom_tunnel_builder` is in `PLUGINS`.

Key attributes:

| Attribute          | Value                                               |
| ------------------ | --------------------------------------------------- |
| `base_url`         | `tunnel-builder` — the URL prefix under `/plugins/` |
| `default_settings` | Defines `device_ssh_port` and `connection_timeout`  |

---

### `forms.py` — `IpsecTunnelForm`

A plain `django.forms.Form` (not a ModelForm — no database model needed).

Key validation logic:

- `clean_tunnel_ip_address()` — uses `ipaddress.IPv4Interface` to validate CIDR input.
- `clean()` — cross-field validation: rejects GCM + HMAC and non-GCM + no HMAC combinations.

The device queryset filters by `platform__network_driver` so only IOS-XE devices appear:

```python
Device.objects.filter(platform__network_driver="cisco_ios").order_by("name")
```

To support additional drivers, add them to the `filter()` call:

```python
Device.objects.filter(
    platform__network_driver__in=["cisco_ios", "cisco_xe"]
).order_by("name")
```

---

### `jobs.py` — `BuildIpsecTunnel`

Two distinct responsibilities:

#### 1. Config builder — `build_iosxe_ipsec_config(data: dict) -> list[str]`

A pure function that takes a dict of parameters and returns an ordered list of IOS-XE CLI commands. It is deliberately decoupled from Nautobot and Netmiko so it can be unit-tested independently.

```python
from nautobot_custom_tunnel_builder.jobs import build_iosxe_ipsec_config

cmds = build_iosxe_ipsec_config({
    "tunnel_number": 100,
    "tunnel_source_interface": "GigabitEthernet1",
    ...
})
assert "interface Tunnel100" in cmds
```

#### 2. Nautobot Job — `BuildIpsecTunnel(Job)`

Handles Nautobot integration:

- Declares `Job` variables (for the Jobs UI) that mirror `IpsecTunnelForm`.
- `run()` method calls `build_iosxe_ipsec_config()`, then connects via Netmiko.
- PSK is redacted from all log lines.
- Credentials come from environment variables (see [Configuration](configuration.md)).

**`Meta` flags of note:**

```python
has_sensitive_variables = True   # Prevents Nautobot from storing job input in the DB
commit_default = True            # Runs with commit=True by default
```

---

### `views.py` — `IpsecTunnelBuilderView`

A `LoginRequiredMixin` + `PermissionRequiredMixin` + `View` class.

- **GET**: instantiates a blank `IpsecTunnelForm` and renders the template.
- **POST**: validates `IpsecTunnelForm`, looks up the Job by `job_class_name`, calls `JobResult.enqueue_job()`, then redirects to the job result URL.

The job is looked up by class name:

```python
job_model = JobModel.objects.get(job_class_name="BuildIpsecTunnel")
```

If the job isn't registered (e.g., migration hasn't been run), the view shows a user-friendly error instead of a 500.

---

### `navigation.py`

Adds the form to Nautobot's navigation under **Network Tools → VPN**. Items are only visible to users with `extras.run_job`.

To move the link to a different nav tab, change the `NavMenuTab(name=...)` value.

---

### `urls.py`

Single route:

```
/plugins/tunnel-builder/  →  IpsecTunnelBuilderView
```

The `base_url = "tunnel-builder"` in `__init__.py` controls the `/plugins/<base_url>/` prefix.

---

### `templates/nautobot_custom_tunnel_builder/ipsec_tunnel_form.html`

Extends Nautobot's `base.html`. Uses Bootstrap 5 (already included in Nautobot 3.x).

The form is split into visual **cards** by concern:

1. Target Device
2. IKE Version & Remote Peer
3. Interesting Traffic (Crypto ACL)
4. Crypto Map
5. Shared IKE Parameters
6. IKEv1 Settings (shown when IKEv1 selected)
7. IKEv2 Settings (shown when IKEv2 selected)
8. IPsec Phase 2 Settings
9. Authentication

A sticky sidebar on medium+ screens explains what config will be pushed.

---

## Adding New Features

### Support a new encryption algorithm

1. Add the new option to `IKE_ENCRYPTION_CHOICES` (or `IPSEC_ENCRYPTION_CHOICES`) in both `forms.py` and `jobs.py`.
2. Verify the IOS-XE keyword is correct for the target platform.
3. Update the algorithm reference table in `docs/iosxe-config.md`.

### Add tunnel removal support

1. Create a new form `RemoveIpsecTunnelForm` in `forms.py` with a device + tunnel number selector.
2. Create a `RemoveIpsecTunnel(Job)` in `jobs.py` that generates `no interface Tunnel<N>` commands.
3. Add a new view in `views.py` and register a new URL in `urls.py`.

### Add SecretsGroup credential lookup

See [Configuration — SecretsGroup Integration](configuration.md#nautobot-secretsgroup-integration-recommended-for-production).

---

## Running Tests

```bash
pytest
```

Tests are located in `tests/` (not yet scaffolded). Key things to test:

- `build_iosxe_ipsec_config()` — verify correct command output for each algorithm combination.
- `IpsecTunnelForm.clean()` — verify GCM/HMAC cross-validation rejects bad combos.
- `IpsecTunnelBuilderView` — use Django test client to test GET/POST flows.

---

## Code Style

```bash
# Format
black nautobot_custom_tunnel_builder/

# Lint
flake8 nautobot_custom_tunnel_builder/
```

Max line length is 120 characters (configure in `setup.cfg` or `pyproject.toml` as needed).
