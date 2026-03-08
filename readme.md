# nautobot-app-custom-tunnel-builder

[![Build and Upload to PyPi](https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/actions/workflows/pypi-workflow.yml/badge.svg)](https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/actions/workflows/pypi-workflow.yml)

A **Nautobot 3.x app** that provides a custom web form for building **policy-based IPsec tunnels** (IKEv1 or IKEv2) on Cisco IOS-XE devices (CSR 1000v, ASR 1000, ISR 4000).

Operators fill out the form, click **Build Tunnel**, and a Nautobot Job SSHes into the target device, generates and pushes the full crypto map–based IPsec configuration, then saves the running config — all without leaving the browser.

---

## Features

- Custom Nautobot form at `/plugins/tunnel-builder/`
- **Policy-based** IPsec using crypto maps and crypto ACLs
- **IKEv2** support: proposal → policy → keyring → profile → transform-set → crypto map
- **IKEv1** support: ISAKMP policy + pre-shared key → transform-set → crypto map
- Algorithm choices: AES-128/192/256, AES-GCM-128/256 (IKEv2), SHA-1/256/384/512, MD5, DH groups 2/5/14/19/20/21
- IKE version toggle with live show/hide of version-specific form sections
- Form-level validation including CIDR network parsing and GCM ↔ HMAC cross-field enforcement
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
PLUGINS = ["nautobot_app_custom_tunnel_builder"]
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

1. **`forms.py`** — Collects IKE version, peer info, interesting-traffic networks, crypto map settings, and IKE/IPsec parameters. Validates CIDRs, enforces IKEv2-only DH group restrictions, and rejects invalid GCM ↔ HMAC combinations.
2. **`views.py`** — Renders the form on GET; enqueues the `BuildIpsecTunnel` Job on valid POST, then redirects to the Job Result page.
3. **`jobs.py`** — `build_iosxe_policy_config()` generates ordered CLI commands; the Job connects with Netmiko, pushes config, and saves it.

### IOS-XE configuration blocks pushed (IKEv2)

```
crypto ikev2 proposal    →  Phase 1 algorithms
crypto ikev2 policy      →  links proposal
crypto ikev2 keyring     →  per-peer PSK
crypto ikev2 profile     →  match + auth + keyring + lifetime
ip access-list extended  →  interesting traffic (crypto ACL)
crypto ipsec transform-set  →  Phase 2 ciphers
crypto map               →  links transform-set + ikev2 profile + ACL
interface <WAN>          →  crypto map applied
copy running-config startup-config
```

### IOS-XE configuration blocks pushed (IKEv1)

```
crypto isakmp policy     →  Phase 1 algorithms + DH group
crypto isakmp key        →  pre-shared key per peer
ip access-list extended  →  interesting traffic (crypto ACL)
crypto ipsec transform-set  →  Phase 2 ciphers
crypto map               →  links transform-set + ACL + peer
interface <WAN>          →  crypto map applied
copy running-config startup-config
```

---

## Project Layout

```
nautobot-app-custom-tunnel-builder/
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
└── nautobot_app_custom_tunnel_builder/
    ├── __init__.py           # NautobotAppConfig
    ├── forms.py              # IpsecTunnelForm
    ├── jobs.py               # BuildIpsecTunnel Job + config builder
    ├── navigation.py         # Nav menu
    ├── urls.py               # URL routing
    ├── views.py              # IpsecTunnelBuilderView
    └── templates/
        └── nautobot_app_custom_tunnel_builder/
            └── ipsec_tunnel_form.html
```

---

## Device Requirements

Devices must be registered in Nautobot with:

- **Platform** → `network_driver` set to `cisco_ios` or `cisco_xe`
- **Primary IPv4 address** set (used as the SSH target)

IOS-XE version **12.4(20)T+** supports IKEv1 crypto maps. Version **15.2(1)S+** is required for `crypto ikev2` support.

---

## Permissions

Users must have the `extras.run_job` permission. The nav menu item and the form view both enforce this.

---

## Documentation

Full documentation is in the [`docs/`](docs/) folder:

| Doc | Contents |
|-----|----------|
| [Overview](docs/overview.md) | Architecture diagram, component table, policy-based vs VTI |
| [Installation](docs/installation.md) | Install steps, device prep, service restart |
| [Configuration](docs/configuration.md) | App settings, env vars, SecretsGroup integration, permissions |
| [Usage](docs/usage.md) | Every form field explained, job result walkthrough, failure scenarios |
| [IOS-XE Config Reference](docs/iosxe-config.md) | Full config template, worked example, verify commands, remove commands |
| [Development](docs/development.md) | Code map, extending the app, testing |

---

## License

Apache 2.0
