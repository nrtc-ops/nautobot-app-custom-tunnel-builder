# nautobot-app-custom-tunnel-builder

[![CI](https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/actions/workflows/ci.yml)
[![Release](https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/actions/workflows/release.yml/badge.svg)](https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/actions/workflows/release.yml)


A **Nautobot 3.x app** that provides a custom web form for building **policy-based IPsec tunnels** (IKEv1 or IKEv2) on Cisco IOS-XE devices (CSR 1000v, ASR 1000, ISR 4000).

Operators fill out the form, click **Build Tunnel**, and a Nautobot Job SSHes into the target device, generates and pushes the full crypto map-based IPsec configuration, then saves the running config — all without leaving the browser.

---

## Features

- Custom Nautobot form at `/plugins/tunnel-builder/`
- **Policy-based** IPsec using crypto maps and crypto ACLs
- **IKEv2** support: proposal > policy > keyring > profile > transform-set > crypto map
- **IKEv1** support: ISAKMP policy + pre-shared key > transform-set > crypto map
- Algorithm choices: AES-128/192/256, AES-GCM-128/256 (IKEv2), SHA-1/256/384/512, MD5, DH groups 2/5/14/19/20/21
- IKE version toggle with live show/hide of version-specific form sections
- Form-level validation including CIDR network parsing and GCM / HMAC cross-field enforcement
- Nautobot Job (`BuildIpsecTunnel`) runnable from both the custom form and the Jobs UI
- SSH via [Netmiko](https://github.com/ktbyers/netmiko) — no RESTCONF or NETCONF required
- PSK redacted from all job logs
- Runs `copy running-config startup-config` automatically
- Navigation menu entry under **Network Tools > VPN**

---

## Requirements

| Dependency | Version |
|------------|---------|
| Python | 3.11+ |
| Nautobot | 3.0.0+ |
| Netmiko | 4.0.0+ |

---

## Quick Start

### 1. Install

```bash
pip install nautobot-custom-tunnel-builder
```

### 2. Add to `nautobot_config.py`

```python
PLUGINS = ["nautobot_custom_tunnel_builder"]
```

### 3. Run post-upgrade

```bash
nautobot-server post_upgrade
```

### 4. Set device credentials

```bash
export NAUTOBOT_DEVICE_USERNAME=admin
export NAUTOBOT_DEVICE_PASSWORD=your-password
export NAUTOBOT_DEVICE_ENABLE_SECRET=your-enable-secret   # optional
```

### 5. Restart services

```bash
sudo systemctl restart nautobot nautobot-worker nautobot-scheduler
```

Navigate to **Network Tools > VPN > Build IPsec Tunnel**.

---

## How It Works

```
Browser -> Custom Form (views.py)
               |
               |  JobResult.enqueue_job()
               v
         Nautobot Job (jobs.py)
               |
               |  Netmiko SSH
               v
         Cisco IOS-XE Device
```

1. **`forms.py`** — Collects IKE version, peer info, interesting-traffic networks, crypto map settings, and IKE/IPsec parameters. Validates CIDRs, enforces IKEv2-only DH group restrictions, and rejects invalid GCM / HMAC combinations.
2. **`views.py`** — Renders the form on GET; enqueues the `BuildIpsecTunnel` Job on valid POST, then redirects to the Job Result page.
3. **`jobs.py`** — `build_iosxe_policy_config()` generates ordered CLI commands; the Job connects with Netmiko, pushes config, and saves it.

---

## Project Layout

```
nautobot-app-custom-tunnel-builder/
├── pyproject.toml                    # Package metadata (Poetry + PEP 621)
├── poetry.lock                       # Locked dependencies
├── tasks.py                          # Invoke tasks for dev workflow
├── mkdocs.yml                        # Documentation config
├── development/                      # Docker Compose dev environment
│   ├── Dockerfile
│   ├── docker-compose.*.yml
│   ├── nautobot_config.py
│   └── *.env
├── docs/
│   ├── admin/                        # Install, upgrade, uninstall, release notes
│   ├── user/                         # Overview, getting started, use cases, FAQ
│   └── dev/                          # Contributing, dev environment, release checklist
├── changes/                          # Towncrier changelog fragments
└── nautobot_custom_tunnel_builder/
    ├── __init__.py                   # NautobotAppConfig
    ├── forms.py                      # IpsecTunnelForm
    ├── jobs.py                       # BuildIpsecTunnel Job + config builder
    ├── navigation.py                 # Nav menu
    ├── urls.py                       # URL routing
    ├── views.py                      # IpsecTunnelBuilderView
    └── templates/
        └── nautobot_custom_tunnel_builder/
            └── ipsec_tunnel_form.html
```

---

## Development

```bash
# Install dependencies
poetry install

# Docker dev environment
poetry run invoke build
poetry run invoke start

# Run all tests
poetry run invoke tests

# Lint & format
poetry run invoke ruff
poetry run invoke autoformat
```

See the full [Development Environment](docs/dev/dev_environment.md) guide for more details.

---

## Device Requirements

Devices must be registered in Nautobot with:

- **Platform** > `network_driver` set to `cisco_ios` or `cisco_xe`
- **Primary IPv4 address** set (used as the SSH target)

---

## Permissions

Users must have the `extras.run_job` permission. The nav menu item and the form view both enforce this.

---

## Documentation

Full documentation is in the [`docs/`](docs/) folder:

| Section | Contents |
|---------|----------|
| [App Overview](docs/user/app_overview.md) | Architecture diagram, component table, policy-based vs VTI |
| [Getting Started](docs/user/app_getting_started.md) | Every form field explained, job result walkthrough |
| [Use Cases](docs/user/app_use_cases.md) | Full IOS-XE config template, worked example, verify commands |
| [Install & Configure](docs/admin/install.md) | Install steps, app config, env vars, permissions |
| [Development](docs/dev/dev_environment.md) | Docker dev env, invoke tasks, code style |
| [Contributing](docs/dev/contributing.md) | Changelog fragments, branching, release policy |

---

## License

Apache 2.0
