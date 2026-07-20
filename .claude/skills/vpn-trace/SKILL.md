---
name: vpn-trace
version: 1.0.0
description: |
  Nautobot VPN tunnel trace — follow a portal request through the complete
  object hierarchy (VPN → VPNTunnel → endpoints → VPNProfile → SecretsGroup →
  JobResult). Use when debugging a member's provisioning, checking tunnel status,
  or investigating why something is missing or broken. Invoke when asked to
  "trace a tunnel", "check VPN status", "debug this member's VPN", or
  "what happened to the acme-corp tunnel".
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - AskUserQuestion
---

# VPN Trace Skill

**Announce at start:** "I'm using the vpn-trace skill to trace the VPN object hierarchy."

## Purpose

Systematically inspect the state of a portal-created IPsec VPN tunnel in this
Nautobot Custom Tunnel Builder app. Given a member name, `vpn_id`, `tunnel_id`,
or IP address, produce a complete picture of every Nautobot object involved and
where it stands.

## Context

This app creates the following hierarchy for each portal tunnel:

```
VPN (vpn_id = "vpn-nrtc-ms-{member}-{city}-{state}-001")
 └─ VPNTunnel (name includes member + location + sequence)
     ├─ vpn_profile → VPNProfile (cloned from template)
     │    ├─ _custom_field_data.custom_tunnel_builder_crypto_map_sequence: int
     │    ├─ _custom_field_data.custom_tunnel_builder_psk_retrieval_token: str
     │    ├─ _custom_field_data.custom_tunnel_builder_psk_retrieved: bool
     │    ├─ vpn_profile_phase1_policy_assignments → VPNPhase1Policy
     │    ├─ vpn_profile_phase2_policy_assignments → VPNPhase2Policy
     │    └─ secrets_group → SecretsGroup → Secret (provider="one-password")
     ├─ endpoint_a (hub / concentrator)
     │    ├─ source_ipaddress → device primary IP
     │    ├─ protected_prefixes → hub network CIDR
     │    └─ _custom_field_data.custom_tunnel_builder_crypto_map_name: str
     └─ endpoint_z (spoke / member)
          ├─ source_ipaddress → member remote peer IP
          └─ protected_prefixes → member network CIDR
```

The `PortalBuildIpsecTunnel` Nautobot Job is enqueued after hierarchy creation.
Key config files:
- `nautobot_custom_tunnel_builder/api/views.py` — `_create_tunnel_hierarchy()`
- `nautobot_custom_tunnel_builder/jobs.py` — `PortalBuildIpsecTunnel.run()`
- `nautobot_custom_tunnel_builder/mapping.py` — `profile_to_config_params()`
- `nautobot_custom_tunnel_builder/onepassword_utils.py` — PSK storage

## Step 1: Identify the subject

Parse the user's request for:
- A `tunnel_id` (UUID)
- A `vpn_id` (e.g., `vpn-nrtc-ms-acme-corp-jackson-ms-001`)
- A member name slug (e.g., `acme-corp`)
- A city/state (e.g., `Jackson, MS`)
- A remote peer IP

If ambiguous, ask the user to clarify.

## Step 2: Search the codebase for naming patterns

Understand the naming conventions so you can reconstruct the expected object names:

```
member slug:       {member_name}            e.g. "acme-corp"
location slug:     {city.lower()}-{state.lower()}  e.g. "jackson-ms"
vpn_id:            vpn-nrtc-ms-{member}-{loc_slug}-001
tunnel_id_str:     vpn-tunnel-nrtc-ms-{member}-{loc_slug}-{sequence}
profile_name:      vpnprofile-nrtc-ms-{member}-{loc_slug}-{sequence}
secret_name:       vpn-psk-nrtc-ms-{member}-{loc_slug}-{sequence}
sg_name:           vpn-sg-nrtc-ms-{member}-{loc_slug}-{sequence}
member_device:     member-{member}-{loc_slug}
1password_title:   vpn-psk-nrtc-ms-{member}-{loc_slug}-{sequence}
```

## Step 3: Trace the object hierarchy

For each object in the hierarchy, report:
- Whether it EXISTS
- Its key fields and custom field values
- Any anomalies (missing FKs, wrong status, empty CF values, etc.)

Check in order:

**VPN object:**
- `vpn_id` field
- `name` field (human display name)
- Count of `vpn_tunnels`

**VPNTunnel:**
- `tunnel_id` string
- `name`
- `status.name` (should be "Active" after success, "Decommissioning" on failure)
- `vpn` FK set?
- `endpoint_a` set?
- `endpoint_z` set?
- `vpn_profile` set?

**VPNProfile:**
- `name`
- `secrets_group` set?
- Phase1 assignments count (should be ≥ 1)
- Phase2 assignments count (should be ≥ 1)
- CF `custom_tunnel_builder_crypto_map_sequence`: value
- CF `custom_tunnel_builder_psk_retrieval_token`: present/blank
- CF `custom_tunnel_builder_psk_retrieved`: True/False

**SecretsGroup + Secret:**
- SecretsGroup name
- Secret name
- Secret `provider` (should be `"one-password"`)
- Secret `parameters` (should have `item_id` and `field`)

**Hub endpoint (endpoint_a):**
- `source_ipaddress` → IP string
- `protected_prefixes` count and values
- CF `custom_tunnel_builder_crypto_map_name`: value

**Spoke endpoint (endpoint_z):**
- `source_ipaddress` → IP string (should match `remote_peer_ip`)
- `protected_prefixes` count and values

**Member Device:**
- `name` = `member-{member}-{loc_slug}`
- Has `dummy0` interface?
- `dummy0` has IP assigned matching spoke endpoint's source IP?

## Step 4: Check Job status

Look for recent `PortalBuildIpsecTunnel` JobResult correlated to this tunnel:
- Job status (`COMPLETED`, `FAILED`, `RUNNING`, `PENDING`)
- Duration
- Any error output in the log
- Tunnel status after job completion

## Step 5: Produce a status report

Format:

```
VPN TRACE REPORT
================
Subject: {member} / {location}
VPN ID: {vpn_id}

HIERARCHY
  VPN:           [OK | MISSING]  {vpn_id}
  VPNTunnel:     [OK | MISSING | DEGRADED]  {tunnel_name}  status={status}
  VPNProfile:    [OK | MISSING]  seq={sequence}  psk_retrieved={bool}
  SecretsGroup:  [OK | MISSING]
  Hub endpoint:  [OK | MISSING]  IP={ip}  crypto_map={name}
  Spoke endpoint:[OK | MISSING]  IP={ip}
  Member device: [OK | MISSING]  {device_name}

JOB
  Status:  [COMPLETED | FAILED | NOT_FOUND]
  Error:   {if failed}

ISSUES
  - {list any anomalies found}

NEXT STEPS
  - {what to investigate or fix}
```

If everything looks clean, say so plainly. If there are gaps, name the specific
object that's missing and what code path creates it (include file:line).
