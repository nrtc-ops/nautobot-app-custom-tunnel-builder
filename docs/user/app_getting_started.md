# Getting Started

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Add to `nautobot_config.py`

```python
PLUGINS = ["nautobot_custom_tunnel_builder"]
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
└── nautobot_custom_tunnel_builder/
    ├── __init__.py           # NautobotAppConfig
    ├── forms.py              # IpsecTunnelForm
    ├── jobs.py               # BuildIpsecTunnel Job + config builder
    ├── navigation.py         # Nav menu
    ├── urls.py               # URL routing
    ├── views.py              # IpsecTunnelBuilderView
    └── templates/
        └── nautobot_custom_tunnel_builder/
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

## Accessing the Form

After installation, navigate to **Network Tools > VPN > Build IPsec Tunnel** in the Nautobot navigation bar. The form is available at:

```
https://<your-nautobot>/plugins/tunnel-builder/
```

You must be logged in and have the `extras.run_job` permission.

---

## Form Sections

### Target Device

| Field             | Description                                                                                                                           |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Target Device** | Dropdown of Nautobot devices whose platform `network_driver` is `cisco_ios` or `cisco_xe`. The device's primary IPv4 is used for SSH. |

---

### IKE Version & Remote Peer

| Field              | Description                                                                               | Default |
| ------------------ | ----------------------------------------------------------------------------------------- | ------- |
| **IKE Version**    | `IKEv2` (recommended) or `IKEv1` (legacy). Switches the visible Phase 1 settings section. | `IKEv2` |
| **Remote Peer IP** | Public IPv4 of the far-end IPsec peer.                                                    | —       |

---

### Interesting Traffic (Crypto ACL)

Defines which traffic is encrypted by the tunnel via an extended ACL.

| Field                     | Description                                   | Example          |
| ------------------------- | --------------------------------------------- | ---------------- |
| **Local Network (CIDR)**  | Local subnet to protect.                      | `192.168.1.0/24` |
| **Remote Network (CIDR)** | Remote subnet to protect.                     | `10.0.0.0/24`    |
| **Crypto ACL Name**       | Name of the `ip access-list extended` object. | `VPN-ACL`        |

---

### Crypto Map

| Field                   | Description                                               | Example            |
| ----------------------- | --------------------------------------------------------- | ------------------ |
| **WAN Interface**       | Physical interface where the crypto map is applied.       | `GigabitEthernet1` |
| **Crypto Map Name**     | Name of the `crypto map` object.                          | `CRYPTO-MAP`       |
| **Crypto Map Sequence** | Sequence number within the map (lower = evaluated first). | `10`               |

---

### Shared IKE Parameters

| Field                   | Description                                                                  | Default        |
| ----------------------- | ---------------------------------------------------------------------------- | -------------- |
| **IKE DH Group**        | Diffie-Hellman group for key exchange. Groups 2 and 5 are IKEv1 legacy only. | `Group 19`     |
| **IKE SA Lifetime (s)** | How long the IKE SA lives before renegotiation. Range: 300-86400.            | `86400` (24 h) |

---

### IKEv1 Settings _(shown when IKEv1 is selected)_

| Field                       | Description                                                       | Default   |
| --------------------------- | ----------------------------------------------------------------- | --------- |
| **ISAKMP Policy Priority**  | Priority of the `crypto isakmp policy` (lower = higher priority). | `10`      |
| **ISAKMP Encryption**       | Phase 1 cipher (`aes`, `aes 256`, `3des`).                        | `AES-256` |
| **ISAKMP Hash / Integrity** | Phase 1 hash (`sha256`, `sha`, `md5`, etc.).                      | `SHA-256` |

---

### IKEv2 Settings _(shown when IKEv2 is selected)_

| Field                   | Description                                                 | Default          |
| ----------------------- | ----------------------------------------------------------- | ---------------- |
| **IKEv2 Proposal Name** | Name of the `crypto ikev2 proposal` object.                 | `IKEv2-PROPOSAL` |
| **IKEv2 Policy Name**   | Name of the `crypto ikev2 policy` object.                   | `IKEv2-POLICY`   |
| **IKEv2 Keyring Name**  | Name of the `crypto ikev2 keyring` object.                  | `IKEv2-KEYRING`  |
| **IKEv2 Profile Name**  | Name of the `crypto ikev2 profile` object.                  | `IKEv2-PROFILE`  |
| **IKEv2 Encryption**    | Phase 1 encryption cipher. GCM options available for IKEv2. | `AES-CBC-256`    |
| **IKEv2 Integrity**     | Phase 1 integrity algorithm.                                | `SHA-256`        |

---

### IPsec Phase 2 Settings

| Field                     | Description                                                       | Default           |
| ------------------------- | ----------------------------------------------------------------- | ----------------- |
| **Transform-Set Name**    | Name of the `crypto ipsec transform-set` object.                  | `IPSEC-TS`        |
| **IPsec Encryption**      | Phase 2 encryption cipher.                                        | `ESP-AES-256`     |
| **IPsec Integrity**       | Phase 2 integrity algorithm. Set to **None** with GCM encryption. | `ESP-SHA256-HMAC` |
| **IPsec SA Lifetime (s)** | How long each IPsec SA lives before rekeying. Range: 120-86400.   | `3600` (1 h)      |

> **GCM note:** If you select `ESP-GCM-128` or `ESP-GCM-256`, you **must** set IPsec Integrity to **None**. The form enforces this with a cross-field validation error.

---

### Authentication

| Field              | Description                                                                            |
| ------------------ | -------------------------------------------------------------------------------------- |
| **Pre-Shared Key** | The IKE PSK shared with the remote peer. Transmitted over SSH. Not stored in Nautobot. |

---

## Submitting the Form

1. Select the IKE version — the appropriate Phase 1 section appears automatically.
2. Complete all required fields (marked with `*`).
3. Click **Build Tunnel**.
4. On success, the Job is enqueued and you are redirected to the **Job Result** page.

---

## Job Result Page

The redirect after submission lands on Nautobot's standard **Job Result** detail page:

- **Status** — Pending > Running > Completed / Failed
- **Log output** — Each step logged (PSK redacted):
    - Configuration commands generated
    - SSH connection established
    - `send_config_set()` output from the device
    - Confirmation that startup-config was saved

---

## Running the Job Directly (Jobs UI)

The `BuildIpsecTunnel` job is available under **Jobs > Build Policy-Based IPsec Tunnel (IOS-XE)**. All form fields are also exposed as Job variables for scripted or API-driven execution.

---

## Failure Scenarios

| Scenario                              | Behavior                                                          |
| ------------------------------------- | ----------------------------------------------------------------- |
| Device has no primary IP              | Job fails immediately with a clear error message                  |
| SSH connection refused / timeout      | Netmiko exception caught; traceback logged; job marked **Failed** |
| Authentication failure                | Netmiko auth exception caught and logged                          |
| Invalid CIDR for local/remote network | Form validation rejects input before job is queued                |
| IKEv2 selected with DH group 2 or 5   | Form cross-field validation rejects before queuing                |
| GCM selected with HMAC integrity      | Form cross-field validation rejects before queuing                |
| Job not registered                    | View displays error (run `nautobot-server migrate`)               |
