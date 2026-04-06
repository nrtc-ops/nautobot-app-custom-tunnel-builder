---
name: vpn-debug
version: 1.0.0
description: |
  Structured debug for Nautobot Custom Tunnel Builder portal provisioning failures.
  Follows the chain: portal API response → transaction state → 1Password call →
  Nautobot object hierarchy → JobResult log → device push output. Use when a
  portal request returned an error, a tunnel is stuck in the wrong status, or
  a member can't establish connectivity.
  Invoke when asked to "debug this tunnel", "why did provisioning fail",
  "the job failed for acme-corp", or "the tunnel is stuck".
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - AskUserQuestion
---

# VPN Debug Skill

**Announce at start:** "I'm using the vpn-debug skill to investigate the provisioning failure."

## Purpose

Systematic failure investigation for portal-requested IPsec tunnels. This skill
follows the full call chain — API → DB transaction → 1Password → Celery job →
Netmiko SSH push — and identifies exactly where it broke and why.

## Iron Law

Do not suggest a fix until the root cause is confirmed. Premature fixes mask the
real problem. Follow the chain until you find the break.

---

## Phase 1: Establish What Happened

Ask the user for (or infer from context):

1. **What was the symptom?**
   - Portal API returned HTTP 4xx or 5xx?
   - API returned 202 but job failed?
   - Job appeared to succeed but device has no config?
   - Tunnel is stuck in "Active" but no connectivity?

2. **What do you have?**
   - `tunnel_id` (UUID from API response)?
   - `vpn_id` or member name?
   - JobResult ID or URL?
   - The original API request payload?

3. **When did it happen?** (approximate timestamp)

---

## Phase 2: Classify the Failure Point

There are five places this can break. Identify which:

```
[A] Input validation (serializer) — returned 400
[B] Transaction / object creation (views.py _create_tunnel_hierarchy) — returned 500
[C] 1Password call (onepassword_utils.py) — part of B, but distinct
[D] Job enqueue or job execution (jobs.py PortalBuildIpsecTunnel) — returned 202 but job failed
[E] Device push (Netmiko send_config_set) — job failed with IOS-XE error
```

---

## Phase 3: Investigate Each Possible Failure Point

### A. Input Validation Failure (HTTP 400)

If the API returned 400, the serializer rejected the request before touching the DB.

Check `api/serializers.py`:
- `member_name`: did it contain uppercase, spaces, or invalid chars?
- `location_state`: was it more than 2 chars or non-alphabetic?
- `device`: does the device exist? Does it have a `primary_ip`?
- `template_vpn_profile`: does the VPNProfile UUID exist?
- `hub_protected_prefix` / `member_protected_prefix`: valid CIDR?
- `remote_peer_ip`: valid IPv4?

No DB changes occur for 400s. No cleanup needed.

---

### B. Transaction Failure (HTTP 500 — hierarchy creation)

If the API returned 500 with `"Failed to create tunnel. Contact an administrator."`,
the `_create_tunnel_hierarchy()` call raised an exception.

The `except Exception` catch in `views.py:post()` absorbs the exception.
**The DB transaction was rolled back** (due to `transaction.atomic()`).
**BUT: if step 6 (1Password) succeeded before the DB failure, the 1Password item is orphaned.**

Investigate in order:

1. **Check if any Nautobot objects were created:**
   - `VPN.objects.filter(vpn_id=...)` — exists?
   - `VPNTunnel.objects.filter(tunnel_id=...)` — exists?
   - `VPNProfile.objects.filter(name__startswith="vpnprofile-nrtc-ms-...")` — exists?

   If none exist → transaction rolled back cleanly.
   If some exist but not others → partial creation leaked out of atomic block (shouldn't happen, investigate migrations).

2. **Check the Nautobot logs** for the traceback:
   - `logger.exception("Failed to create tunnel for member '%s'.", ...)` in views.py
   - Look for the actual exception class and message

3. **Common B-type failure causes:**
   - `DeviceType.DoesNotExist`: "Member VPN Endpoint" DeviceType not created by migration 0001. Run `nautobot-server post_upgrade`.
   - `LocationType.DoesNotExist`: No LocationType named "Site". Must be pre-created or added to migration.
   - `Status.DoesNotExist`: Status "Active" doesn't exist for the relevant model (unusual, but possible on fresh install).
   - `IntegrityError`: Duplicate `tunnel_id` string (sequence collision from race condition).
   - `RuntimeError: 1Password credentials not configured`: `OP_SERVICE_ACCOUNT_TOKEN` or `OP_VAULT_UUID` env vars not set.

---

### C. 1Password Failure (part of B)

If the error message mentions "1Password" or "credentials not configured":

Check `onepassword_utils.py`:
- Are `OP_SERVICE_ACCOUNT_TOKEN` and `OP_VAULT_UUID` set in the environment?
- Is `onepassword-sdk` installed? (`poetry run python -c "import onepassword"`)
- Is the service account token valid? (Check 1Password audit logs if accessible)
- Did the vault UUID change?

The `asyncio.run()` call creates a new event loop each time. This is safe in WSGI
but will fail with `RuntimeError: This event loop is already running` in async
contexts. If running under ASGI or gevent Celery, this is the cause.

---

### D. Job Failure (job returned FAILED status)

If the API returned 202 (tunnel objects created) but the job failed:

1. **Locate the JobResult:**
   - Look for `PortalBuildIpsecTunnel` job results filtered by creation time
   - Check `job_result.status` and `job_result.result`

2. **Read the job log output** for the traceback

3. **Common D-type failure causes:**

   **Tunnel object not found:**
   - `VPNTunnel.DoesNotExist` for `tunnel_id`
   - The tunnel was deleted between API response and job execution (race or manual deletion)

   **Endpoint missing:**
   - `"No hub endpoint with source IP found"` — `tunnel.endpoint_a` is None
   - `"No spoke endpoint with source IP found"` — `tunnel.endpoint_z` is None
   - This means the hierarchy creation succeeded but the endpoint FK assignment failed silently. Check `views.py:391` (`tunnel.endpoint_a = hub_endpoint; tunnel.save()`) — was `save()` called?

   **VPN Profile missing:**
   - `"Tunnel has no VPN profile assigned"` — `tunnel.vpn_profile` is None
   - Check `views.py:373` — was `vpn_profile=profile` included in `VPNTunnel.objects.create()`?

   **Mapping failure:**
   - `ValueError: VPNProfile has no Phase 1 policy assignment` — the cloned profile has no Phase1 assignments
   - Check `_clone_vpn_profile()` in views.py — were Phase1/Phase2 assignments copied from the template?
   - `KeyError` in `mapping.py` — an algorithm value in the VPNPhase1Policy or VPNPhase2Policy has no entry in the translation maps in `constants.py`

   **SSH connection failure:**
   - `NetMikoTimeoutException` or `NetMikoAuthenticationException`
   - Check: device primary IP reachable? SSH credentials correct (`NAUTOBOT_DEVICE_USERNAME`, `NAUTOBOT_DEVICE_PASSWORD`)?
   - Check: `NAUTOBOT_DEVICE_SSH_PORT` set correctly if non-22?

---

### E. Device Push Failure (IOS-XE error output)

If the job failed with `IosXeConfigError: Device returned errors: %...`:

1. **Read the error line(s)** from the job log (look for `% ` prefix lines)
2. **Common IOS-XE error causes:**
   - `% Invalid input detected` — command syntax error, likely wrong IOS-XE version
   - `% Ambiguous command` — abbreviated command not supported on this IOS-XE version
   - `% Cannot use GCM without AES-128 or AES-256` — algorithm combination invalid
   - `% Overlapping transform-set` — sequence number collision (same seq on same crypto map)
   - `% Crypto map sequence already exists` — same issue

3. **Check the generated commands:**
   - Read `mapping.py:profile_to_config_params()` with the actual profile's algorithm values
   - Run `build_iosxe_policy_config()` mentally or via test with those values
   - Look for the command that matches the error line number

4. **Tunnel status after E-type failure:**
   - `PortalBuildIpsecTunnel.run()` sets tunnel status to `"Decommissioning"` on exception
   - Check `tunnel.status.name` to confirm

---

## Phase 4: Produce a Debug Report

```
VPN DEBUG REPORT
================
Symptom: {what the user reported}
Failure point: [A/B/C/D/E] — {category name}

ROOT CAUSE
  {specific exception class and message, or exact error output}
  Location: {file:line where the failure occurred}

EVIDENCE
  - {key observations from Phase 3}
  - {Nautobot objects present/absent}
  - {Job status and relevant log lines}

CURRENT STATE
  DB objects: [CLEAN / PARTIAL / PRESENT]
  1Password: [ITEM CREATED / NOT CREATED / UNKNOWN]
  Device config: [PUSHED / NOT PUSHED / PARTIAL]
  Tunnel status: {status.name}

FIX
  1. {first corrective step}
  2. {second corrective step}
  Note any manual cleanup needed (orphaned 1Password items, stuck tunnel status, etc.)
```

---

## Cleanup Guidance by Failure Type

- **Type A:** Nothing to clean up. Just fix the request payload.
- **Type B (no 1Password call completed):** DB is clean. Fix the root cause, retry.
- **Type B (1Password call completed before DB failure):** Orphaned 1Password item. Name: `vpn-psk-nrtc-ms-{member}-{loc_slug}-{sequence}`. Delete manually from 1Password vault.
- **Type C:** No DB objects created, no 1Password item. Fix credentials, retry.
- **Type D:** Tunnel object exists in "Active" status but no device config. Options: manually trigger `PortalBuildIpsecTunnel` with the tunnel_id and PSK, or delete the tunnel objects and re-request.
- **Type E:** Tunnel is "Decommissioning". Device may have partial config. SSH to device, manually remove the partial crypto map sequence. Then delete tunnel objects and re-request.
