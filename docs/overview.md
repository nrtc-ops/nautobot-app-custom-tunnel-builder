# Overview

## What is `nautobot-custom-tunnel-builder`?

`nautobot-custom-tunnel-builder` is a Nautobot 3.x app (plugin) that provides a custom web form inside Nautobot for building **policy-based IPsec tunnels** — using either **IKEv1 (ISAKMP)** or **IKEv2** — on Cisco IOS-XE devices (e.g., Cisco CSR 1000v).

Operators fill in the form, click **Build Tunnel**, and a Nautobot Job connects to the device over SSH, pushes the generated crypto map configuration, and saves it to startup-config — all without leaving the browser.

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

| Module          | Purpose                                                                                            |
| --------------- | -------------------------------------------------------------------------------------------------- |
| `__init__.py`   | `NautobotAppConfig` — registers the app with Nautobot                                              |
| `forms.py`      | Django form — collects and validates all IPsec parameters for IKEv1 and IKEv2                      |
| `jobs.py`       | Nautobot Job — generates IOS-XE commands via `build_iosxe_policy_config()` and pushes them via SSH |
| `views.py`      | Custom Django CBV — serves the form and dispatches the job                                         |
| `urls.py`       | Routes `/tunnel-builder/` to the view                                                              |
| `navigation.py` | Adds **Network Tools → VPN → Build IPsec Tunnel** to Nautobot's nav bar                            |
| `templates/`    | Bootstrap 5 HTML template with IKE version show/hide                                               |

---

## Policy-Based vs. Route-Based (VTI)

This app uses **policy-based IPsec with crypto maps**, which is the traditional and most broadly compatible method for site-to-site IPsec on IOS-XE.

| Feature           | Policy-Based (this app)       | Route-Based (VTI)    |
| ----------------- | ----------------------------- | -------------------- |
| Traffic selection | ACL / crypto ACL              | Route / tunnel iface |
| IKEv1 support     | Yes                           | Limited              |
| IKEv2 support     | Yes                           | Yes                  |
| Dynamic routing   | Complex (GRE over IPsec)      | Native               |
| Compatibility     | Broadest (legacy + 3rd-party) | Modern IOS-XE only   |
| Config complexity | Moderate                      | Lower (modern)       |

Policy-based is the right choice when connecting to **legacy IKEv1 peers**, **third-party firewalls**, or any environment that does not support route-based VTI.

---

## IKEv1 vs. IKEv2

| Feature               | IKEv1 (ISAKMP)       | IKEv2 (RFC 7296)  |
| --------------------- | -------------------- | ----------------- |
| Standards age         | Legacy (RFC 2409)    | Modern (RFC 7296) |
| Message exchanges     | More (6 or 3)        | Fewer (4)         |
| DoS resistance        | Lower                | Built-in cookies  |
| EAP / asymmetric auth | No                   | Yes               |
| Dead Peer Detection   | Extension (RFC 3706) | Built-in          |
| Recommendation        | Legacy peers only    | Preferred         |

---

## Supported Platforms

- Cisco CSR 1000v (IOS-XE)
- Cisco ASR 1000 series (IOS-XE)
- Cisco ISR 4000 series (IOS-XE)
- Any IOS-XE device with `crypto isakmp` / `crypto ikev2` support

Devices must be registered in Nautobot with:

- A **primary IPv4 address** (used for SSH)
- A **platform** whose `network_driver` is `cisco_ios` or `cisco_xe`
