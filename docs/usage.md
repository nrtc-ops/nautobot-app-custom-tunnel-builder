# Usage

## Accessing the Form

After installation, navigate to **Network Tools → VPN → Build IPsec Tunnel** in the Nautobot navigation bar. The form is available at:

```
https://<your-nautobot>/plugins/ipsec-builder/
```

You must be logged in and have the `extras.run_job` permission.

---

## Form Fields

### Target Device

| Field | Description |
|-------|-------------|
| **Target Device** | Dropdown of all Nautobot devices whose platform `network_driver` is `cisco_ios` or `cisco_xe`. The device's primary IPv4 is used for SSH. |

---

### Tunnel Interface

| Field | Description | Example |
|-------|-------------|---------|
| **Tunnel Interface Number** | Numeric ID for the `interface Tunnel<N>`. Must be unique on the device. | `100` |
| **Tunnel Source Interface** | The local WAN/uplink interface the tunnel originates from. | `GigabitEthernet1` |
| **Tunnel IP Address (CIDR)** | IP address of the virtual tunnel interface in CIDR notation. | `10.255.0.1/30` |
| **Remote Peer IP** | Public IPv4 of the far-end IPsec peer. | `203.0.113.1` |

---

### IKEv2 Settings

| Field | Description | Default |
|-------|-------------|---------|
| **IKEv2 Proposal Name** | Name of the `crypto ikev2 proposal` object. | `IKEv2-PROPOSAL` |
| **IKEv2 Policy Name** | Name of the `crypto ikev2 policy` object. | `IKEv2-POLICY` |
| **IKEv2 Keyring Name** | Name of the `crypto ikev2 keyring` object. | `IKEv2-KEYRING` |
| **IKEv2 Profile Name** | Name of the `crypto ikev2 profile` object. | `IKEv2-PROFILE` |
| **IKE Encryption** | Phase 1 encryption cipher. | `AES-CBC-256` |
| **IKE Integrity** | Phase 1 integrity/hash algorithm. | `SHA-256` |
| **IKE DH Group** | Diffie-Hellman group for key exchange. | `Group 19` (256-bit ECP) |
| **IKE SA Lifetime (s)** | How long the IKE Security Association lives before renegotiation. Range: 300–86400. | `86400` (24 h) |

---

### IPsec Settings

| Field | Description | Default |
|-------|-------------|---------|
| **Transform-Set Name** | Name of the `crypto ipsec transform-set` object. | `IPSEC-TS` |
| **IPsec Profile Name** | Name of the `crypto ipsec profile` object. | `IPSEC-PROFILE` |
| **IPsec Encryption** | Phase 2 encryption cipher. | `ESP-AES-256` |
| **IPsec Integrity** | Phase 2 integrity algorithm. Set to **None** when using GCM encryption (GCM is authenticated by design). | `ESP-SHA256-HMAC` |
| **IPsec SA Lifetime (s)** | How long each IPsec SA lives before rekeying. Range: 120–86400. | `3600` (1 h) |

> **GCM note:** If you select `ESP-GCM-128` or `ESP-GCM-256`, you **must** set IPsec Integrity to **None**. The form enforces this with a cross-field validation error.

---

### Authentication

| Field | Description |
|-------|-------------|
| **Pre-Shared Key** | The IKEv2 PSK shared with the remote peer. Transmitted to the device over SSH. Not stored in Nautobot. |

---

## Submitting the Form

1. Complete all required fields (marked with `*`).
2. Click **Build Tunnel**.
3. The form validates locally (client-side `novalidate` is off; Django validates on the server).
4. On success, the Job is enqueued and you are redirected to the **Job Result** page.
5. The Job Result page shows real-time log output as the job runs.

---

## Job Result Page

The redirect after submission lands on Nautobot's standard **Job Result** detail page. Here you can see:

- **Status** — Pending → Running → Completed / Failed
- **Log output** — Each step is logged:
  - Configuration commands generated (PSK redacted)
  - SSH connection established
  - `send_config_set()` output from the device
  - Confirmation that startup-config was saved
- **Return value** — A summary string, e.g.:
  ```
  IPsec tunnel Tunnel100 ↔ 203.0.113.1 configured on csr1-lab (10.0.0.1).
  ```

---

## Running the Job Directly (Jobs UI)

The `BuildIpsecTunnel` job is also available directly under **Jobs → Build IKEv2 IPsec Tunnel (IOS-XE)** in the Nautobot Jobs UI. This is useful for:

- Scripted/API-driven execution
- Testing individual parameters
- Re-running a configuration without the custom form

All fields exposed in the custom form are also available as Job variables in the Jobs UI.

---

## Failure Scenarios

| Scenario | Behavior |
|----------|----------|
| Device has no primary IP | Job fails immediately with a clear error message |
| SSH connection refused / timeout | Netmiko exception is caught; full traceback logged; job marked **Failed** |
| Authentication failure | Netmiko `NetmikoAuthenticationException` caught and logged |
| Invalid CIDR for tunnel IP | Form validation rejects the input before the job is queued |
| GCM selected with HMAC integrity | Form cross-field validation rejects before queuing |
| Job not registered | View displays an error message (run `nautobot-server migrate`) |
