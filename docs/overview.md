# Overview

## What is `nautobot-ipsec-builder`?

`nautobot-ipsec-builder` is a Nautobot 3.x app (plugin) that provides a custom web form inside Nautobot for building **IKEv2 Virtual Tunnel Interface (VTI) IPsec tunnels** on Cisco IOS-XE devices (e.g., Cisco CSR 1000v).

Operators fill in the form, click **Build Tunnel**, and a Nautobot Job connects to the device over SSH, pushes the generated configuration, and saves it to startup-config — all without leaving the browser.

---

## Architecture

```
Browser
  │
  ▼
┌─────────────────────────────────────────────┐
│  Nautobot 3.x                               │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │  Custom View  (views.py)            │   │
│  │  GET  → render IpsecTunnelForm      │   │
│  │  POST → validate → enqueue Job      │   │
│  └────────────────┬────────────────────┘   │
│                   │ JobResult.enqueue_job() │
│  ┌────────────────▼────────────────────┐   │
│  │  Nautobot Job  (jobs.py)            │   │
│  │  BuildIpsecTunnel.run()             │   │
│  │  1. Build IOS-XE config commands    │   │
│  │  2. Netmiko SSH → Device            │   │
│  │  3. send_config_set()               │   │
│  │  4. save_config()                   │   │
│  └────────────────┬────────────────────┘   │
└───────────────────┼─────────────────────────┘
                    │ SSH / Netmiko
                    ▼
              Cisco IOS-XE
              (CSR 1000v / ASR / ISR)
```

---

## Key Components

| Module | Purpose |
|--------|---------|
| `__init__.py` | `NautobotAppConfig` — registers the app with Nautobot |
| `forms.py` | Django form — collects and validates all IPsec parameters |
| `jobs.py` | Nautobot Job — generates IOS-XE commands and pushes them via SSH |
| `views.py` | Custom Django CBV — serves the form and dispatches the job |
| `urls.py` | Routes `/ipsec-builder/` to the view |
| `navigation.py` | Adds **Network Tools → VPN → Build IPsec Tunnel** to Nautobot's nav bar |
| `templates/` | Bootstrap 5 HTML template for the form |

---

## IKEv2 VTI — Why This Approach?

This app uses **IKEv2 with a Virtual Tunnel Interface (VTI)**, which is the modern, recommended method for site-to-site IPsec on IOS-XE. Compared to the older crypto-map approach:

| Feature | Crypto Map (IKEv1) | IKEv2 VTI (this app) |
|---------|-------------------|----------------------|
| Standards | IKEv1 | IKEv2 (RFC 7296) |
| Routing | Policy-based (ACL) | Route-based (interface) |
| Dynamic routing (OSPF/BGP) | Complex | Native |
| QoS on tunnel | Not supported | Supported |
| Dead Peer Detection | Limited | Built-in |
| Configuration complexity | High | Lower |

---

## Supported Platforms

- Cisco CSR 1000v (IOS-XE)
- Cisco ASR 1000 series (IOS-XE)
- Cisco ISR 4000 series (IOS-XE)
- Any IOS-XE device with `crypto ikev2` support (15.4+)

Devices must be registered in Nautobot with:
- A **primary IPv4 address** (used for SSH)
- A **platform** whose `network_driver` is `cisco_ios` or `cisco_xe`
