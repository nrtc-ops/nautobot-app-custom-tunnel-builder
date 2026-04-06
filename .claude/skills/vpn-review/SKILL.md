---
name: vpn-review
version: 1.0.0
description: |
  VPN-specific code review for the Nautobot Custom Tunnel Builder. Checks
  crypto map/ACL naming collision, sequence number safety, IKEv1 vs IKEv2
  config path completeness, Nautobot VPN model hierarchy correctness, PSK
  handling, and endpoint field naming. Use in addition to (or instead of)
  generic /review when the diff touches VPN provisioning code.
  Invoke when asked to "vpn-review", "review the VPN code", "check my tunnel
  changes", or when changes touch jobs.py, api/views.py, mapping.py, or
  onepassword_utils.py.
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - AskUserQuestion
---

# VPN Review Skill

**Announce at start:** "I'm using the vpn-review skill to check VPN-specific concerns."

## Purpose

Domain-specific code review for this app's IPsec provisioning code. The
generic `/review` catches SQL injection and race conditions. This skill knows
the specific ways VPN provisioning can go wrong: naming collisions on the
router, IKE version mismatches, Nautobot model misuse, PSK leakage paths.

## Context

Architecture at a glance:
- **Policy-based IPsec** (crypto map + crypto ACL). NOT VTI/tunnel interfaces.
- **IKEv1 path:** `crypto isakmp policy` → `crypto isakmp key` → `crypto ipsec transform-set` → `crypto map`
- **IKEv2 path:** `crypto ikev2 proposal` → `crypto ikev2 policy` → `crypto ikev2 keyring` → `crypto ikev2 profile` → `crypto ipsec transform-set` → `crypto map`
- Crypto map sequence starts at 2000, increments by 10 per portal tunnel.
- PSK stored in 1Password → Nautobot `Secret` (provider `"one-password"`) → `SecretsGroup` → `VPNProfile`.
- `_custom_field_data` on `VPNProfile` holds: `custom_tunnel_builder_crypto_map_sequence`, `custom_tunnel_builder_psk_retrieval_token`, `custom_tunnel_builder_psk_retrieved`.
- `_custom_field_data` on `VPNTunnelEndpoint` holds: `custom_tunnel_builder_crypto_map_name`.

Key files:
- `nautobot_custom_tunnel_builder/api/views.py` — portal API + hierarchy creation
- `nautobot_custom_tunnel_builder/jobs.py` — `BuildIpsecTunnel` + `PortalBuildIpsecTunnel`
- `nautobot_custom_tunnel_builder/mapping.py` — `profile_to_config_params()`
- `nautobot_custom_tunnel_builder/api/serializers.py` — `PortalTunnelRequestSerializer`
- `nautobot_custom_tunnel_builder/onepassword_utils.py` — PSK storage

## Checklist

Work through each category. Flag every issue with severity and exact location.

---

### 1. Crypto Map / ACL Naming Collision Risk

The device has a SINGLE global crypto map (name in `custom_tunnel_builder_crypto_map_name`
CF on the hub endpoint). Each tunnel gets a sequence number. ACL and transform-set
names are derived from the sequence.

Check:
- [ ] Are `crypto_acl_name` and `ipsec_transform_set_name` unique per sequence? Pattern: `PORTAL-ACL-{seq}` and `PORTAL-TS-{seq}`.
- [ ] Is the crypto map name read correctly from the hub endpoint CF (`custom_tunnel_builder_crypto_map_name`), defaulting to `"VPN"`?
- [ ] If the code constructs names manually, does it use the sequence number as the disambiguator?
- [ ] IKEv2 names (`PORTAL-PROP-{seq}`, `PORTAL-POL-{seq}`, `PORTAL-KR-{seq}`, `PORTAL-PROF-{seq}`) — are they all sequence-scoped?
- [ ] IKEv1 names — `isakmp_policy_priority` should equal `sequence` (priority IS the sequence in this app).

Failure mode: two tunnels sharing a name silently overwrite each other on the router. No error returned from device.

---

### 2. Sequence Number Safety

Sequence starts at 2000, steps by 10. Calculated in `_create_tunnel_hierarchy`.

Check:
- [ ] Is sequence calculated from COMMITTED DB state (existing `VPNTunnel.vpn_profile._custom_field_data`)?
- [ ] Is there a `select_for_update()` or other lock to prevent concurrent requests getting the same sequence?
- [ ] Is the fallback for "no existing tunnels" returning 2000 (not 0, not None)?
- [ ] Is `max_seq + 10` the step used (not +1 or +100)?
- [ ] Could `None` sequence propagate into the IOS-XE command string? Check `build_iosxe_policy_config` input dict.

---

### 3. IKE Version Path Completeness

IKEv1 and IKEv2 have distinct config blocks. A missing command on the router often
silently fails to establish the SA — you won't see an error from `send_config_set`.

IKEv1 required commands:
- `crypto isakmp policy {priority}` with encr, hash, authentication, group, lifetime
- `crypto isakmp key {psk} address {peer}`
- `crypto ipsec transform-set {name} {enc} {integrity}` (or GCM without integrity)
- `crypto map {name} {seq} ipsec-isakmp` with set peer, set transform-set, match address

IKEv2 required commands:
- `crypto ikev2 proposal {name}` with encryption, integrity, group
- `crypto ikev2 policy {name}` with proposal reference
- `crypto ikev2 keyring {name}` with peer address + pre-shared-key local/remote
- `crypto ikev2 profile {name}` with match identity, authentication, keyring, lifetime
- `crypto ipsec transform-set {name} {enc}` + `mode tunnel`
- `crypto map {name} {seq} ipsec-isakmp` with set peer, set transform-set, set ikev2-profile, match address

Check:
- [ ] Does `_build_ikev1_commands()` produce all required IKEv1 commands?
- [ ] Does `_build_ikev2_commands()` produce all required IKEv2 commands including `set ikev2-profile`?
- [ ] Does `build_iosxe_policy_config()` add the crypto ACL and crypto map for BOTH IKE versions?
- [ ] Is `mode tunnel` included in the transform-set? (Required for policy-based.)
- [ ] GCM Phase 2: is integrity algorithm intentionally omitted (correct) or accidentally omitted (bug)?
- [ ] Are there any commands that reference IKEv2 constructs in the IKEv1 path or vice versa?

---

### 4. Nautobot VPN Model Hierarchy

Check:
- [ ] `VPNTunnel.endpoint_a` = hub (concentrator). `VPNTunnel.endpoint_z` = spoke (member). Are these assigned in the right order?
- [ ] `VPNTunnelEndpoint.source_ipaddress` is an `IPAddress` object. Is it being assigned an `IPAddress` instance (not a string, not an Interface)?
- [ ] `VPNTunnelEndpoint.protected_prefixes` uses `.add()` (M2M). Is it called after the endpoint is saved?
- [ ] `VPNProfile` Phase1/Phase2 assignments: related manager name is `vpn_profile_phase1_policy_assignments` and `vpn_profile_phase2_policy_assignments`. Confirm no code uses the old `vpnprofilephase1policyassignment_set` name.
- [ ] When cloning a VPNProfile, are ALL Phase1 AND Phase2 assignments copied (not just the first)?
- [ ] Is `VPNTunnel.vpn` FK set? (Associates the tunnel to the VPN object.)
- [ ] Is `VPNTunnel.vpn_profile` FK set?

---

### 5. PSK Handling

PSK is the most sensitive value. Check every path it touches.

Check:
- [ ] Is PSK generated with `secrets.token_urlsafe(32)` or equivalent? Not `random`, not `uuid4`.
- [ ] Is PSK stored ONLY in 1Password? Not in any DB field, not in any log line?
- [ ] In `jobs.py`, is PSK redacted from `self.logger` calls before logging? Pattern: `line.replace(psk, "***REDACTED***")`.
- [ ] Is PSK passed to `JobResult.enqueue_job()` as a kwarg? If so, note it — Nautobot may store it in `job_kwargs` JSON. Flag if not redacted.
- [ ] In `PSKRetrievalView`, is the token cleared after retrieval (`psk_retrieval_token = ""`)?
- [ ] Is `psk_retrieved = True` set atomically with the token clear (same `.save()`)?
- [ ] Is `get_value()` called on the correct `Secret` object (the one in the tunnel's `SecretsGroup`)?
- [ ] Is `secret` checked for `None` before calling `get_value()`?

---

### 6. Serializer / Input Validation

Check:
- [ ] `member_name`: slug pattern enforced (`^[a-z0-9]+(?:-[a-z0-9]+)*$`)? Case normalization?
- [ ] `location_state`: forced to uppercase? Max 2 chars?
- [ ] `hub_protected_prefix` and `member_protected_prefix`: valid IPv4 CIDR? `strict=False` so host bits are tolerated?
- [ ] `device`: validated that `primary_ip` exists (otherwise SSH fails)?
- [ ] `template_vpn_profile`: queryset scoped (not open to any VPNProfile)?
- [ ] `remote_peer_ip`: IPv4 only enforced?

---

### 7. Error Handling and Rollback

Check:
- [ ] Is `_create_tunnel_hierarchy` wrapped in `transaction.atomic()`?
- [ ] Is the 1Password call INSIDE the atomic block? If so, flag: 1Password is not rollbackable. If a DB step after the 1Password call fails, the 1Password item is orphaned.
- [ ] Does a 1Password failure (RuntimeError) result in a 500 response with no partial DB state?
- [ ] Does a DB failure after 1Password creation result in an orphaned secret? (Known issue — note severity.)
- [ ] Are all 500 responses using `logger.exception()` so the traceback is captured?
- [ ] Is the broad `except Exception` catch in `post()` logging enough to diagnose production failures?

---

### 8. Device Resolution

Check:
- [ ] Is device resolved from `hub_endpoint.source_ipaddress.assigned_object.parent`?
- [ ] Is `assigned_object` checked for type before accessing `.parent`? (Could be VMInterface, not Interface.)
- [ ] Is `device.primary_ip` rechecked after lookup, or trusted from serializer validation?

---

## Output Format

For each issue found:

```
[SEVERITY] Category — short description
  Location: file.py:line
  Detail: what's wrong and what the consequence is
  Fix: what to change
```

Severity levels:
- `[BLOCKER]` — will cause incorrect IOS-XE config, PSK leakage, or data loss
- `[HIGH]` — will cause runtime failures in production
- `[MEDIUM]` — operational risk, correctness issue in edge cases
- `[INFO]` — style, missing guard, improvement

End with a summary line: "N blockers, N high, N medium, N info."

If nothing is wrong in a category, say "PASS" for that category — don't skip it silently.
