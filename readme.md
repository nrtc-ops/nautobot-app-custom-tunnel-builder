# nautobot-ipsec-builder

A **Nautobot 3.x app** that provides a custom web form for building **IKEv2 Virtual Tunnel Interface (VTI) IPsec tunnels** on Cisco IOS-XE devices (CSR 1000v, ASR 1000, ISR 4000).

Operators fill out the form, click **Build Tunnel**, and a Nautobot Job SSHes into the target device, generates and pushes the full IKEv2 + IPsec VTI configuration, then saves the running config — all without leaving the browser.

---

## Features

- Custom Nautobot form at `/plugins/ipsec-builder/`
- Full **IKEv2 VTI** configuration (proposal → policy → keyring → profile → transform-set → ipsec-profile → tunnel interface)
- Algorithm choices: AES-CBC-128/256, AES-GCM-128/256, SHA-256/384/512, DH groups 14/19/20/21
- Form-level validation including CIDR parsing and GCM ↔ HMAC cross-field enforcement
- Nautobot Job (`BuildIpsecTunnel`) runnable from both the custom form and the Jobs UI
- SSH via [Netmiko](https://github.com/ktbyers/netmiko) — no RESTCONF or NETCONF required
- PSK redacted from all job logs
- Runs `copy running-config startup-config` automatically
- Navigation menu entry under **Network Tools → VPN**

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
pip install -e .
```

### 2. Add to `nautobot_config.py`

```python
PLUGINS = ["nautobot_ipsec_builder"]
```

### 3. Migrate and collect static

```bash
nautobot-server migrate
nautobot-server collectstatic --no-input
```

### 4. Set device credentials

```bash
export NAUTOBOT_DEVICE_USERNAME=admin
export NAUTOBOT_DEVICE_PASSWORD=your-password
export NAUTOBOT_DEVICE_ENABLE_SECRET=your-enable-secret   # optional
```

### 5. Restart services

```bash
sudo systemctl restart nautobot nautobot-worker
```

Navigate to **Network Tools → VPN → Build IPsec Tunnel**.

---

## How It Works

```
Browser → Custom Form (views.py)
               │
               │  JobResult.enqueue_job()
               ▼
         Nautobot Job (jobs.py)
               │
               │  Netmiko SSH
               ▼
         Cisco IOS-XE Device
```

1. **`forms.py`** — A Django form collects all IKEv2 and IPsec parameters and validates them (CIDR, algorithm compatibility).
2. **`views.py`** — A class-based view renders the form on GET and enqueues the `BuildIpsecTunnel` Job on a valid POST, then redirects to the Job Result page.
3. **`jobs.py`** — The Job generates ordered IOS-XE CLI commands via `build_iosxe_ipsec_config()`, then connects to the device with Netmiko, pushes the config, and saves it.

### IOS-XE configuration blocks pushed (in order)

```
crypto ikev2 proposal    →  IKEv2 algorithms
crypto ikev2 policy      →  links proposal
crypto ikev2 keyring     →  per-peer PSK
crypto ikev2 profile     →  match + auth + keyring + lifetime
crypto ipsec transform-set  →  Phase 2 ciphers
crypto ipsec profile     →  links transform-set + ikev2 profile
interface Tunnel<N>      →  VTI with tunnel protection
copy running-config startup-config
```

---

## Project Layout

```
nautobot-custom-views/
├── pyproject.toml
├── requirements.txt
├── README.md
├── docs/
│   ├── overview.md          # Architecture and design rationale
│   ├── installation.md      # Step-by-step install guide
│   ├── configuration.md     # App settings, env vars, SecretsGroup
│   ├── usage.md             # Form fields, job result, failure scenarios
│   ├── iosxe-config.md      # Full IOS-XE config template + worked example
│   └── development.md       # Code map, adding features, testing
└── nautobot_ipsec_builder/
    ├── __init__.py           # NautobotAppConfig
    ├── forms.py              # IpsecTunnelForm
    ├── jobs.py               # BuildIpsecTunnel Job
    ├── navigation.py         # Nav menu
    ├── urls.py               # URL routing
    ├── views.py              # IpsecTunnelBuilderView
    └── templates/
        └── nautobot_ipsec_builder/
            └── ipsec_tunnel_form.html
```

---

## Device Requirements

Devices must be registered in Nautobot with:

- **Platform** → `network_driver` set to `cisco_ios` or `cisco_xe`
- **Primary IPv4 address** set (used as the SSH target)

IOS-XE version **15.4+** is required for `crypto ikev2` support.

---

## Permissions

Users must have the `extras.run_job` permission. The nav menu item and the form view both enforce this.

---

## Documentation

Full documentation is in the [`docs/`](docs/) folder:

| Doc | Contents |
|-----|----------|
| [Overview](docs/overview.md) | Architecture diagram, component table, why IKEv2 VTI |
| [Installation](docs/installation.md) | Install steps, device prep, service restart |
| [Configuration](docs/configuration.md) | App settings, env vars, SecretsGroup integration, permissions |
| [Usage](docs/usage.md) | Every form field explained, job result walkthrough, failure scenarios |
| [IOS-XE Config Reference](docs/iosxe-config.md) | Full config template, worked example, verify commands, remove commands |
| [Development](docs/development.md) | Code map, extending the app, testing |

---

## License

Apache 2.0
