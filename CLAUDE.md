# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

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

Code style: ruff (format + lint), pylint, 120-character line limit.

## Architecture

This is a Nautobot 3.x plugin that pushes **policy-based IPsec configurations** (crypto map + crypto ACL) to Cisco IOS-XE devices via SSH. It does NOT use VTI/route-based tunnels.

**Request flow:**
```
Browser form → IpsecTunnelBuilderView (views.py)
  → looks up Job model by module_name + job_class_name
  → JobResult.enqueue_job()
  → BuildIpsecTunnel.run() (jobs.py)
  → build_iosxe_policy_config() generates CLI commands
  → Netmiko SSH → send_config_set() → write mem
```

**Key modules:**
- `__init__.py` — `NautobotCustomTunnelBuilderConfig`; imports `jobs` in `ready()` to register the Nautobot job
- `jobs.py` — `BuildIpsecTunnel` job + `build_iosxe_policy_config(data)` config builder
- `forms.py` — `IpsecTunnelForm`; device filtered to `cisco_ios`/`cisco_xe` platform drivers
- `views.py` — `IpsecTunnelBuilderView` (LoginRequired + `extras.run_job` permission)
- `navigation.py` — Network Tools → VPN → Build IPsec Tunnel

**IKEv1 vs IKEv2 config paths** (both in `build_iosxe_policy_config`):
- IKEv1: `crypto isakmp policy` → `crypto isakmp key` → `crypto ipsec transform-set` → `crypto map`
- IKEv2: `crypto ikev2 proposal` → `crypto ikev2 policy` → `crypto ikev2 keyring` → `crypto ikev2 profile` → `crypto ipsec transform-set` → `crypto map`

**Credential handling:**
- SSH credentials from env vars: `NAUTOBOT_DEVICE_USERNAME`, `NAUTOBOT_DEVICE_PASSWORD`, `NAUTOBOT_DEVICE_ENABLE_SECRET`, `NAUTOBOT_DEVICE_SSH_PORT`
- Pre-shared key (PSK) is a `SensitiveVariable`; redacted from all job logs and never stored in Nautobot

**Device requirements:**
- `platform.network_driver` must be `cisco_ios` or `cisco_xe`
- Device must have a primary IPv4 address for SSH

**Cross-field validation rules (forms.py + enforced in job):**
- IKEv2 rejects DH groups 2 and 5
- GCM Phase 2 encryption requires `None` integrity (HMAC not used with GCM)
- Non-GCM encryption requires an explicit HMAC integrity algorithm

**Job registration:** The job is discovered via `register_jobs(BuildIpsecTunnel)` in `jobs.py` and triggered by the `from . import jobs` in `ready()`. After install, `nautobot-server migrate` is required to register the job in the database.
