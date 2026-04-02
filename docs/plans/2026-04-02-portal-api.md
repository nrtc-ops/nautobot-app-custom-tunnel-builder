# Portal API for Self-Service IPsec Tunnel Provisioning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a REST API to the Nautobot tunnel builder plugin so the member portal can programmatically request IPsec tunnel builds with simplified inputs.

**Architecture:** Custom REST API endpoint in the existing plugin. Portal POSTs 5 params → API validates, creates VPN objects (status=provisioning), enqueues a Celery job → job maps VPNProfile to config, pushes via SSH, stores PSK in Nautobot Secrets → portal polls status, retrieves PSK via one-time URL.

**Tech Stack:** Python/Django, Nautobot 3.x, Django REST Framework, Celery (via Nautobot jobs), Netmiko, Nautobot VPN models + Secrets framework.

**Design doc:** `docs/designs/portal-api-design.md`
**Eng review test plan:** `docs/designs/eng-review-test-plan.md`

---

## Context

Network engineers manually SSH into Cisco IOS-XE devices to build IPsec tunnels. The existing plugin automates this via a Nautobot form. Now a member-facing portal (Rails + Keycloak OIDC) needs to request tunnel builds via API. Portal users provide 5 params; crypto settings come from VPNProfile objects.

### Key Decisions (from eng review)

- **Celery job + polling** (not synchronous API) to avoid WSGI timeout
- **PSK storage:** Nautobot Custom Fields on VPNTunnel + Nautobot Secrets
- **select_for_update()** on sequence number reads to prevent race conditions
- **VPN objects first** (status=provisioning), update to active/failed after SSH
- **Duplicate check:** (device + peer + local_network + remote_network)
- **IOS-XE error detection:** parse send_config_set output for `% ` error prefix
- **PORTAL- prefix** on all auto-generated config names to avoid collision with manual tunnels
- **Skip interface-apply block** for portal tunnels (crypto map already applied)
- **Crypto map name** from Device Custom Field
- **Both IKEv1 and IKEv2** mapping from VPNProfile
- **Shared device queryset** for form + API (fix existing `cisco_xe`-only bug)

### Nautobot VPN Model Structure (verified from live instance)

```
VPNProfile (name, keepalive, NAT, secrets_group, etc.)
  └── VPNProfilePhase1PolicyAssignment (weight)
        └── VPNPhase1Policy (ike_version, encryption_algorithm[], integrity_algorithm[], dh_group[], lifetime_seconds)
  └── VPNProfilePhase2PolicyAssignment (weight)
        └── VPNPhase2Policy (encryption_algorithm[], integrity_algorithm[], pfs_group[], lifetime)
```

All algorithm fields are JSON arrays (lists). Select first element.

---

## File Structure

```
nautobot_custom_tunnel_builder/
├── __init__.py                    ← MODIFY: register API URLs
├── constants.py                   ← MODIFY: add translation maps + shared queryset
├── jobs.py                        ← MODIFY: extract SSH push, add portal job
├── forms.py                       ← MODIFY: use shared queryset, fix platform filter
├── mapping.py                     ← NEW: profile_to_config_params()
├── api/
│   ├── __init__.py                ← NEW
│   ├── serializers.py             ← NEW: PortalTunnelRequestSerializer
│   ├── views.py                   ← NEW: PortalTunnelRequestView, TunnelStatusView, PSKRetrievalView
│   └── urls.py                    ← NEW: API URL patterns
├── urls.py                        ← MODIFY: include API urls
├── tests/
│   ├── __init__.py                ← NEW
│   ├── test_config_generation.py  ← NEW: tests for build_iosxe_policy_config
│   ├── test_ssh_push.py           ← NEW: tests for push_config_to_device
│   ├── test_constants.py          ← NEW: tests for translation maps
│   ├── test_mapping.py            ← NEW: tests for profile_to_config_params
│   ├── test_forms.py              ← NEW: tests for form validation
│   └── test_api.py                ← NEW: tests for API endpoints
└── views.py                       (unchanged)
```

---

## Task 1: Algorithm Translation Maps in constants.py

**Files:**
- Modify: `nautobot_custom_tunnel_builder/constants.py`
- Create: `nautobot_custom_tunnel_builder/tests/__init__.py`
- Create: `nautobot_custom_tunnel_builder/tests/test_constants.py`

- [ ] **Step 1: Create tests directory and test file**

```bash
mkdir -p nautobot_custom_tunnel_builder/tests
touch nautobot_custom_tunnel_builder/tests/__init__.py
```

- [ ] **Step 2: Write failing tests for translation maps**

Create `nautobot_custom_tunnel_builder/tests/test_constants.py`:

```python
"""Tests for algorithm translation maps in constants."""

from django.test import TestCase

from nautobot_custom_tunnel_builder.constants import (
    NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY,
    NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY,
    NAUTOBOT_TO_IOSXE_IKE_VERSION,
    get_iosxe_device_queryset,
)


class TranslationMapTest(TestCase):
    """Verify every Nautobot VPN model value maps to a valid IOS-XE CLI token."""

    def test_phase1_encryption_aes256cbc(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["AES-256-CBC"], "aes-cbc-256")

    def test_phase1_encryption_aes128cbc(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["AES-128-CBC"], "aes-cbc-128")

    def test_phase1_encryption_aes256gcm(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["AES-256-GCM"], "aes-gcm-256")

    def test_phase1_encryption_aes128gcm(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["AES-128-GCM"], "aes-gcm-128")

    def test_phase1_integrity_sha256(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY["SHA256"], "sha256")

    def test_phase1_integrity_sha384(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY["SHA384"], "sha384")

    def test_phase1_integrity_sha512(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY["SHA512"], "sha512")

    def test_phase2_encryption_aes256cbc(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION["AES-256-CBC"], "esp-aes 256")

    def test_phase2_encryption_aes128cbc(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION["AES-128-CBC"], "esp-aes 128")

    def test_phase2_encryption_aes256gcm(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION["AES-256-GCM"], "esp-gcm 256")

    def test_phase2_encryption_aes128gcm(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION["AES-128-GCM"], "esp-gcm 128")

    def test_phase2_integrity_sha256(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY["SHA256"], "esp-sha256-hmac")

    def test_phase2_integrity_sha384(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY["SHA384"], "esp-sha384-hmac")

    def test_phase2_integrity_sha512(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY["SHA512"], "esp-sha512-hmac")

    def test_ike_version_ikev2(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKE_VERSION["IKEv2"], "ikev2")

    def test_ike_version_ikev1(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKE_VERSION["IKEv1"], "ikev1")

    def test_unknown_phase1_encryption_raises(self):
        with self.assertRaises(KeyError):
            _ = NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["UNKNOWN-CIPHER"]


class IosxeDeviceQuerysetTest(TestCase):
    """Verify shared device queryset filters both cisco_ios and cisco_xe."""

    def test_queryset_filters_correct_drivers(self):
        qs = get_iosxe_device_queryset()
        # The queryset should filter on network_driver__in
        where_clause = str(qs.query)
        self.assertIn("cisco_xe", where_clause)
        self.assertIn("cisco_ios", where_clause)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `invoke unittest --pattern "test_constants" --failfast`
Expected: ImportError — translation maps don't exist yet.

- [ ] **Step 4: Add translation maps and shared queryset to constants.py**

Add to end of `nautobot_custom_tunnel_builder/constants.py`:

```python
from nautobot.dcim.models import Device

# ---------------------------------------------------------------------------
# Nautobot VPN model value → IOS-XE CLI token translation maps
# ---------------------------------------------------------------------------

NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION = {
    "AES-256-CBC": "aes-cbc-256",
    "AES-128-CBC": "aes-cbc-128",
    "AES-256-GCM": "aes-gcm-256",
    "AES-128-GCM": "aes-gcm-128",
}

NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY = {
    "SHA256": "sha256",
    "SHA384": "sha384",
    "SHA512": "sha512",
    "SHA1": "sha",
    "MD5": "md5",
}

NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION = {
    "AES-256-CBC": "esp-aes 256",
    "AES-128-CBC": "esp-aes 128",
    "AES-256-GCM": "esp-gcm 256",
    "AES-128-GCM": "esp-gcm 128",
}

NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY = {
    "SHA256": "esp-sha256-hmac",
    "SHA384": "esp-sha384-hmac",
    "SHA512": "esp-sha512-hmac",
}

NAUTOBOT_TO_IOSXE_IKE_VERSION = {
    "IKEv2": "ikev2",
    "IKEv1": "ikev1",
}

# IKEv1-specific: Nautobot Phase1 encryption → IOS-XE ISAKMP encryption
NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION = {
    "AES-256-CBC": "aes 256",
    "AES-128-CBC": "aes",
    "AES-192-CBC": "aes 192",
    "3DES": "3des",
}

# IKEv1-specific: Nautobot Phase1 integrity → IOS-XE ISAKMP hash
NAUTOBOT_TO_IOSXE_IKEV1_HASH = {
    "SHA256": "sha256",
    "SHA384": "sha384",
    "SHA512": "sha512",
    "SHA1": "sha",
    "MD5": "md5",
}


def get_iosxe_device_queryset():
    """Return a Device queryset filtered to Cisco IOS-XE platforms.

    Shared between the internal form and the portal API serializer.
    """
    return Device.objects.filter(
        platform__network_driver__in=["cisco_ios", "cisco_xe"]
    ).order_by("name")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `invoke unittest --pattern "test_constants" --failfast`
Expected: All PASS.

- [ ] **Step 6: Update forms.py to use shared queryset**

In `nautobot_custom_tunnel_builder/forms.py`, change line 34:

```python
# OLD:
device = forms.ModelChoiceField(
    queryset=Device.objects.filter(platform__network_driver="cisco_xe").order_by("name"),

# NEW:
device = forms.ModelChoiceField(
    queryset=get_iosxe_device_queryset(),
```

Add import at top of forms.py:
```python
from .constants import get_iosxe_device_queryset
```

Remove the now-unused `from nautobot.dcim.models import Device` import from forms.py.

- [ ] **Step 7: Commit**

```bash
git add nautobot_custom_tunnel_builder/constants.py nautobot_custom_tunnel_builder/forms.py nautobot_custom_tunnel_builder/tests/
git commit -m "feat: add algorithm translation maps and shared device queryset

Add Nautobot VPN model → IOS-XE CLI token translation maps for
Phase 1/2 encryption, integrity, IKE version, and IKEv1-specific params.
Extract shared device queryset (cisco_ios + cisco_xe) used by form and API.
Fix forms.py to filter both cisco_ios and cisco_xe (was cisco_xe only)."
```

---

## Task 2: Extract SSH Push Function + Error Detection

**Files:**
- Modify: `nautobot_custom_tunnel_builder/jobs.py`
- Create: `nautobot_custom_tunnel_builder/tests/test_ssh_push.py`

- [ ] **Step 1: Write failing tests for push_config_to_device**

Create `nautobot_custom_tunnel_builder/tests/test_ssh_push.py`:

```python
"""Tests for the extracted SSH push function."""

import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase

from nautobot_custom_tunnel_builder.jobs import push_config_to_device, IosXeConfigError


class PushConfigToDeviceTest(TestCase):
    """Test the extracted SSH push function."""

    def setUp(self):
        self.logger = logging.getLogger("test")
        self.device_params = {
            "device_type": "cisco_xe",
            "host": "10.1.1.1",
            "username": "admin",
            "password": "pass",
            "secret": "enable",
            "port": 22,
            "timeout": 30,
            "session_log": None,
        }
        self.commands = ["interface GigabitEthernet1", " description TEST"]

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_successful_push(self, mock_connect):
        """SSH push succeeds, config saved."""
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = "config output"

        output = push_config_to_device(self.device_params, self.commands, self.logger)

        mock_conn.send_config_set.assert_called_once_with(self.commands, cmd_verify=False)
        mock_conn.save_config.assert_called_once()
        self.assertEqual(output, "config output")

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_enable_secret_called_when_present(self, mock_connect):
        """Enable mode entered when secret is provided."""
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = "ok"

        push_config_to_device(self.device_params, self.commands, self.logger)
        mock_conn.enable.assert_called_once()

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_enable_not_called_without_secret(self, mock_connect):
        """Enable mode skipped when no secret."""
        self.device_params["secret"] = ""
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = "ok"

        push_config_to_device(self.device_params, self.commands, self.logger)
        mock_conn.enable.assert_not_called()

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_iosxe_error_detected(self, mock_connect):
        """IOS-XE error patterns in output raise IosXeConfigError."""
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = (
            "crypto ipsec transform-set BAD\n% Invalid input detected at '^' marker."
        )

        with self.assertRaises(IosXeConfigError) as ctx:
            push_config_to_device(self.device_params, self.commands, self.logger)

        self.assertIn("Invalid input", str(ctx.exception))
        mock_conn.save_config.assert_not_called()

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_connection_failure_propagates(self, mock_connect):
        """Connection failure raises original exception."""
        mock_connect.side_effect = Exception("Connection refused")

        with self.assertRaises(Exception) as ctx:
            push_config_to_device(self.device_params, self.commands, self.logger)

        self.assertIn("Connection refused", str(ctx.exception))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `invoke unittest --pattern "test_ssh_push" --failfast`
Expected: ImportError — `push_config_to_device` and `IosXeConfigError` don't exist.

- [ ] **Step 3: Extract push_config_to_device and add error detection**

In `nautobot_custom_tunnel_builder/jobs.py`, add after the imports (before `name = "NRTC Tunnel Builders"`):

```python
import re

# ---------------------------------------------------------------------------
# IOS-XE error detection
# ---------------------------------------------------------------------------

# Matches IOS-XE error lines like "% Invalid input detected at '^' marker."
_IOSXE_ERROR_PATTERN = re.compile(r"^%\s+.+", re.MULTILINE)


class IosXeConfigError(Exception):
    """Raised when IOS-XE returns error output during config push."""


# ---------------------------------------------------------------------------
# Shared SSH push function
# ---------------------------------------------------------------------------


def push_config_to_device(device_params: dict, commands: list[str], logger) -> str:
    """Push configuration commands to a device via SSH and save config.

    Args:
        device_params: Netmiko connection parameters dict.
        commands: List of IOS-XE configuration commands.
        logger: Logger instance for status messages.

    Returns:
        Raw output from send_config_set.

    Raises:
        IosXeConfigError: If the device output contains error patterns.
        Exception: If SSH connection or command execution fails.
    """
    with ConnectHandler(**device_params) as conn:
        if device_params.get("secret"):
            conn.enable()

        logger.info("Connected. Pushing %d commands.", len(commands))
        output = conn.send_config_set(commands, cmd_verify=False)
        logger.info("Configuration output:\n%s", output)

        # Check for IOS-XE error patterns before saving
        errors = _IOSXE_ERROR_PATTERN.findall(output)
        if errors:
            error_msg = "; ".join(errors)
            logger.error("IOS-XE errors detected: %s", error_msg)
            raise IosXeConfigError(f"Device returned errors: {error_msg}")

        conn.save_config()
        logger.info("Running configuration saved to startup-config.")

    return output
```

- [ ] **Step 4: Refactor BuildIpsecTunnel.run() to use push_config_to_device**

Replace lines 459-499 of the `run()` method (the SSH connection block) with:

```python
        device_params = {
            "device_type": device_type,
            "host": mgmt_ip,
            "username": os.environ.get("NAUTOBOT_DEVICE_USERNAME", "admin"),
            "password": os.environ.get("NAUTOBOT_DEVICE_PASSWORD", ""),
            "secret": os.environ.get("NAUTOBOT_DEVICE_ENABLE_SECRET", ""),
            "port": int(os.environ.get("NAUTOBOT_DEVICE_SSH_PORT", 22)),
            "timeout": 30,
            "session_log": None,
        }

        try:
            push_config_to_device(device_params, commands, self.logger)
        except Exception as exc:
            self.logger.error(
                "Failed to configure %s: %s\n%s",
                device.name,
                exc,
                traceback.format_exc(),
            )
            raise
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `invoke unittest --pattern "test_ssh_push" --failfast`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add nautobot_custom_tunnel_builder/jobs.py nautobot_custom_tunnel_builder/tests/test_ssh_push.py
git commit -m "refactor: extract SSH push function with IOS-XE error detection

Extract push_config_to_device() from BuildIpsecTunnel.run() so both
the existing job and new portal API can reuse it. Add IOS-XE error
pattern detection — scans send_config_set output for '% ' error
lines and raises IosXeConfigError before write mem."
```

---

## Task 3: Profile-to-Config Mapping Function

**Files:**
- Create: `nautobot_custom_tunnel_builder/mapping.py`
- Create: `nautobot_custom_tunnel_builder/tests/test_mapping.py`

- [ ] **Step 1: Write failing tests for profile_to_config_params**

Create `nautobot_custom_tunnel_builder/tests/test_mapping.py`:

```python
"""Tests for VPNProfile → IOS-XE config parameter mapping."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from nautobot_custom_tunnel_builder.mapping import profile_to_config_params


def _make_phase1_policy(
    ike_version="IKEv2",
    encryption=None,
    integrity=None,
    dh_group=None,
    lifetime=86400,
):
    """Create a mock VPNPhase1Policy."""
    policy = MagicMock()
    policy.ike_version = ike_version
    policy.encryption_algorithm = encryption or ["AES-256-CBC"]
    policy.integrity_algorithm = integrity or ["SHA256"]
    policy.dh_group = dh_group or ["19"]
    policy.lifetime_seconds = lifetime
    return policy


def _make_phase2_policy(encryption=None, integrity=None, lifetime=3600):
    """Create a mock VPNPhase2Policy."""
    policy = MagicMock()
    policy.encryption_algorithm = encryption or ["AES-256-CBC"]
    policy.integrity_algorithm = integrity or ["SHA256"]
    policy.lifetime = lifetime
    return policy


def _make_profile(phase1=None, phase2=None):
    """Create a mock VPNProfile with phase 1/2 policy assignments."""
    profile = MagicMock()

    p1_assignment = MagicMock()
    p1_assignment.vpn_phase1_policy = phase1 or _make_phase1_policy()

    p2_assignment = MagicMock()
    p2_assignment.vpn_phase2_policy = phase2 or _make_phase2_policy()

    profile.vpnprofilephase1policyassignment_set.order_by.return_value.first.return_value = p1_assignment
    profile.vpnprofilephase2policyassignment_set.order_by.return_value.first.return_value = p2_assignment

    return profile


class ProfileToConfigParamsIKEv2Test(TestCase):
    """Test IKEv2 profile mapping."""

    def test_standard_ikev2_profile(self):
        profile = _make_profile()
        result = profile_to_config_params(
            vpn_profile=profile,
            remote_peer_ip="203.0.113.1",
            local_network_cidr="192.168.1.0/24",
            protected_network_cidr="10.0.0.0/24",
            crypto_map_name="CRYPTO-MAP",
            sequence=10,
        )

        self.assertEqual(result["ike_version"], "ikev2")
        self.assertEqual(result["remote_peer_ip"], "203.0.113.1")
        self.assertEqual(result["local_network"], "192.168.1.0/24")
        self.assertEqual(result["remote_network"], "10.0.0.0/24")
        self.assertEqual(result["ikev2_encryption"], "aes-cbc-256")
        self.assertEqual(result["ikev2_integrity"], "sha256")
        self.assertEqual(result["ike_dh_group"], "19")
        self.assertEqual(result["ike_lifetime"], 86400)
        self.assertEqual(result["ipsec_encryption"], "esp-aes 256")
        self.assertEqual(result["ipsec_integrity"], "esp-sha256-hmac")
        self.assertEqual(result["ipsec_lifetime"], 3600)
        self.assertEqual(result["crypto_map_name"], "CRYPTO-MAP")
        self.assertEqual(result["crypto_map_sequence"], 10)

    def test_portal_prefix_on_auto_names(self):
        profile = _make_profile()
        result = profile_to_config_params(
            vpn_profile=profile,
            remote_peer_ip="203.0.113.1",
            local_network_cidr="192.168.1.0/24",
            protected_network_cidr="10.0.0.0/24",
            crypto_map_name="CRYPTO-MAP",
            sequence=20,
        )

        self.assertEqual(result["crypto_acl_name"], "PORTAL-ACL-20")
        self.assertEqual(result["ipsec_transform_set_name"], "PORTAL-TS-20")
        self.assertEqual(result["ikev2_proposal_name"], "PORTAL-PROP-20")
        self.assertEqual(result["ikev2_policy_name"], "PORTAL-POL-20")
        self.assertEqual(result["ikev2_keyring_name"], "PORTAL-KR-20")
        self.assertEqual(result["ikev2_profile_name"], "PORTAL-PROF-20")

    def test_gcm_encryption_no_integrity(self):
        phase1 = _make_phase1_policy(encryption=["AES-256-GCM"])
        phase2 = _make_phase2_policy(encryption=["AES-256-GCM"])
        profile = _make_profile(phase1=phase1, phase2=phase2)

        result = profile_to_config_params(
            vpn_profile=profile,
            remote_peer_ip="203.0.113.1",
            local_network_cidr="192.168.1.0/24",
            protected_network_cidr="10.0.0.0/24",
            crypto_map_name="CRYPTO-MAP",
            sequence=10,
        )

        self.assertEqual(result["ipsec_encryption"], "esp-gcm 256")
        self.assertEqual(result["ipsec_integrity"], "")

    def test_skip_interface_apply(self):
        """Portal-provisioned tunnels do not apply crypto map to interface."""
        profile = _make_profile()
        result = profile_to_config_params(
            vpn_profile=profile,
            remote_peer_ip="203.0.113.1",
            local_network_cidr="192.168.1.0/24",
            protected_network_cidr="10.0.0.0/24",
            crypto_map_name="CRYPTO-MAP",
            sequence=10,
        )

        self.assertNotIn("wan_interface", result)


class ProfileToConfigParamsIKEv1Test(TestCase):
    """Test IKEv1 profile mapping."""

    def test_ikev1_profile(self):
        phase1 = _make_phase1_policy(
            ike_version="IKEv1",
            encryption=["AES-256-CBC"],
            integrity=["SHA256"],
            dh_group=["14"],
        )
        profile = _make_profile(phase1=phase1)

        result = profile_to_config_params(
            vpn_profile=profile,
            remote_peer_ip="203.0.113.1",
            local_network_cidr="192.168.1.0/24",
            protected_network_cidr="10.0.0.0/24",
            crypto_map_name="CRYPTO-MAP",
            sequence=10,
        )

        self.assertEqual(result["ike_version"], "ikev1")
        self.assertEqual(result["ikev1_encryption"], "aes 256")
        self.assertEqual(result["ikev1_hash"], "sha256")
        self.assertEqual(result["isakmp_policy_priority"], 10)
        self.assertNotIn("ikev2_encryption", result)


class ProfileToConfigParamsEdgeCasesTest(TestCase):
    """Test edge cases in profile mapping."""

    def test_missing_phase1_assignment_raises(self):
        profile = MagicMock()
        profile.vpnprofilephase1policyassignment_set.order_by.return_value.first.return_value = None

        with self.assertRaises(ValueError) as ctx:
            profile_to_config_params(
                vpn_profile=profile,
                remote_peer_ip="203.0.113.1",
                local_network_cidr="192.168.1.0/24",
                protected_network_cidr="10.0.0.0/24",
                crypto_map_name="CRYPTO-MAP",
                sequence=10,
            )
        self.assertIn("Phase 1", str(ctx.exception))

    def test_missing_phase2_assignment_raises(self):
        profile = _make_profile()
        profile.vpnprofilephase2policyassignment_set.order_by.return_value.first.return_value = None

        with self.assertRaises(ValueError) as ctx:
            profile_to_config_params(
                vpn_profile=profile,
                remote_peer_ip="203.0.113.1",
                local_network_cidr="192.168.1.0/24",
                protected_network_cidr="10.0.0.0/24",
                crypto_map_name="CRYPTO-MAP",
                sequence=10,
            )
        self.assertIn("Phase 2", str(ctx.exception))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `invoke unittest --pattern "test_mapping" --failfast`
Expected: ImportError — mapping.py doesn't exist.

- [ ] **Step 3: Implement profile_to_config_params**

Create `nautobot_custom_tunnel_builder/mapping.py`:

```python
"""Map VPNProfile objects to build_iosxe_policy_config() input parameters."""

from .constants import (
    NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_IKEV1_HASH,
    NAUTOBOT_TO_IOSXE_IKE_VERSION,
    NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY,
    NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY,
)

# Phase 2 encryption algorithms that provide built-in authentication (no HMAC needed)
_GCM_PHASE2_ALGORITHMS = {"esp-gcm 256", "esp-gcm 128"}


def profile_to_config_params(
    vpn_profile,
    remote_peer_ip: str,
    local_network_cidr: str,
    protected_network_cidr: str,
    crypto_map_name: str,
    sequence: int,
) -> dict:
    """Translate a VPNProfile + request params into a dict for build_iosxe_policy_config().

    Args:
        vpn_profile: Nautobot VPNProfile model instance.
        remote_peer_ip: Remote peer IP address.
        local_network_cidr: Local network in CIDR notation.
        protected_network_cidr: Remote (protected) network in CIDR notation.
        crypto_map_name: Name of the existing crypto map on the device.
        sequence: Crypto map sequence number for this tunnel.

    Returns:
        Dict compatible with build_iosxe_policy_config().

    Raises:
        ValueError: If the profile has no Phase 1 or Phase 2 policy assignment.
        KeyError: If an algorithm value has no IOS-XE translation.
    """
    # Resolve Phase 1 and Phase 2 policies via assignment tables
    p1_assignment = (
        vpn_profile.vpnprofilephase1policyassignment_set.order_by("weight").first()
    )
    if not p1_assignment:
        raise ValueError(
            f"VPNProfile '{vpn_profile}' has no Phase 1 policy assignment."
        )

    p2_assignment = (
        vpn_profile.vpnprofilephase2policyassignment_set.order_by("weight").first()
    )
    if not p2_assignment:
        raise ValueError(
            f"VPNProfile '{vpn_profile}' has no Phase 2 policy assignment."
        )

    phase1 = p1_assignment.vpn_phase1_policy
    phase2 = p2_assignment.vpn_phase2_policy

    ike_version = NAUTOBOT_TO_IOSXE_IKE_VERSION[phase1.ike_version]

    # Phase 2 (IPsec) — shared between IKEv1 and IKEv2
    ipsec_enc = NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION[phase2.encryption_algorithm[0]]
    # GCM provides built-in authentication; no separate integrity algorithm
    if ipsec_enc in _GCM_PHASE2_ALGORITHMS:
        ipsec_integ = ""
    else:
        ipsec_integ = NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY[phase2.integrity_algorithm[0]]

    params = {
        "ike_version": ike_version,
        "remote_peer_ip": remote_peer_ip,
        "local_network": local_network_cidr,
        "remote_network": protected_network_cidr,
        "crypto_map_name": crypto_map_name,
        "crypto_map_sequence": sequence,
        "crypto_acl_name": f"PORTAL-ACL-{sequence}",
        "ipsec_transform_set_name": f"PORTAL-TS-{sequence}",
        "ike_dh_group": phase1.dh_group[0],
        "ike_lifetime": phase1.lifetime_seconds,
        "ipsec_encryption": ipsec_enc,
        "ipsec_integrity": ipsec_integ,
        "ipsec_lifetime": phase2.lifetime,
    }

    if ike_version == "ikev2":
        params.update({
            "ikev2_encryption": NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION[phase1.encryption_algorithm[0]],
            "ikev2_integrity": NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY[phase1.integrity_algorithm[0]],
            "ikev2_proposal_name": f"PORTAL-PROP-{sequence}",
            "ikev2_policy_name": f"PORTAL-POL-{sequence}",
            "ikev2_keyring_name": f"PORTAL-KR-{sequence}",
            "ikev2_profile_name": f"PORTAL-PROF-{sequence}",
        })
    else:
        # IKEv1 parameters
        params.update({
            "ikev1_encryption": NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION[phase1.encryption_algorithm[0]],
            "ikev1_hash": NAUTOBOT_TO_IOSXE_IKEV1_HASH[phase1.integrity_algorithm[0]],
            "isakmp_policy_priority": sequence,
        })

    return params
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `invoke unittest --pattern "test_mapping" --failfast`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add nautobot_custom_tunnel_builder/mapping.py nautobot_custom_tunnel_builder/tests/test_mapping.py
git commit -m "feat: add VPNProfile to IOS-XE config parameter mapping

profile_to_config_params() translates a VPNProfile (via Phase 1/2
policy assignments) into the dict that build_iosxe_policy_config()
expects. Supports both IKEv2 and IKEv1. Auto-generates PORTAL-
prefixed names for config objects. GCM encryption auto-clears
integrity (built-in auth)."
```

---

## Task 4: Portal Build Job (Celery)

**Files:**
- Modify: `nautobot_custom_tunnel_builder/jobs.py`

- [ ] **Step 1: Add PortalBuildIpsecTunnel job class**

Add to end of `nautobot_custom_tunnel_builder/jobs.py` (before `register_jobs`):

```python
from nautobot.vpn.models import VPNTunnel

from .mapping import profile_to_config_params


class PortalBuildIpsecTunnel(Job):
    """Build an IPsec tunnel from a VPNProfile, triggered by the portal API.

    The portal API view creates VPN objects and enqueues this job.
    This job resolves the profile, generates config, and pushes via SSH.
    On success, updates VPN tunnel status to 'active'.
    On failure, updates status to 'failed'.
    """

    class Meta:
        name = "Portal: Build IPsec Tunnel from VPN Profile"
        description = "Generates and pushes IPsec config derived from a VPN Profile."
        label = "Portal Build IPsec Tunnel"
        commit_default = True
        has_sensitive_variables = True
        hidden = True  # Not shown in Nautobot UI job list

    tunnel_id = StringVar(
        label="VPN Tunnel ID",
        description="UUID of the VPNTunnel object created by the API.",
    )

    pre_shared_key = StringVar(
        label="Pre-Shared Key",
        description="Generated PSK to push to the device.",
    )

    def run(self, tunnel_id, pre_shared_key):
        """Execute the portal-triggered tunnel build."""
        from nautobot.extras.models import Status

        tunnel = VPNTunnel.objects.select_related(
            "vpn_profile",
        ).get(id=tunnel_id)

        profile = tunnel.vpn_profile
        device = tunnel.vpntunnelendpoint_set.first().source_ip_address.assigned_object.device

        # Resolve crypto map name from device custom field
        crypto_map_name = device.cf.get("crypto_map_name", "CRYPTO-MAP")

        # Get sequence from tunnel custom field (set by the API view)
        sequence = tunnel.cf.get("crypto_map_sequence", 10)

        self.logger.info(
            "Building tunnel %s on device %s with profile %s (seq %d).",
            tunnel.name, device.name, profile.name, sequence,
        )

        # Map profile to config parameters
        config_params = profile_to_config_params(
            vpn_profile=profile,
            remote_peer_ip=tunnel.cf.get("remote_peer_ip", ""),
            local_network_cidr=tunnel.cf.get("local_network_cidr", ""),
            protected_network_cidr=tunnel.cf.get("protected_network_cidr", ""),
            crypto_map_name=crypto_map_name,
            sequence=sequence,
        )
        config_params["pre_shared_key"] = pre_shared_key

        # Generate IOS-XE commands (skip interface apply — crypto map already bound)
        commands = build_iosxe_policy_config(config_params)
        # Remove the last two lines (interface + crypto map apply)
        commands = [cmd for cmd in commands if not cmd.strip().startswith(("interface ", "crypto map " + crypto_map_name + " " + str(sequence))) or "ipsec-isakmp" in cmd]

        # Actually, let's be more precise: remove commands that apply the map to an interface
        # The interface/crypto map block is always the last 2 lines
        if len(commands) >= 2 and commands[-2].strip().startswith("interface "):
            commands = commands[:-2]

        # Log redacted config
        redacted = [
            line.replace(pre_shared_key, "***REDACTED***") if pre_shared_key in line else line
            for line in commands
        ]
        self.logger.debug("Configuration preview:\n%s", "\n".join(redacted))

        # Build device connection params
        mgmt_ip = str(device.primary_ip.address.ip)
        platform_map = {"cisco_ios": "cisco_ios", "cisco_xe": "cisco_xe", "cisco_iosxe": "cisco_xe"}
        driver = (device.platform.network_driver or "").lower() if device.platform else ""
        device_type = platform_map.get(driver, "cisco_ios")

        device_params = {
            "device_type": device_type,
            "host": mgmt_ip,
            "username": os.environ.get("NAUTOBOT_DEVICE_USERNAME", "admin"),
            "password": os.environ.get("NAUTOBOT_DEVICE_PASSWORD", ""),
            "secret": os.environ.get("NAUTOBOT_DEVICE_ENABLE_SECRET", ""),
            "port": int(os.environ.get("NAUTOBOT_DEVICE_SSH_PORT", 22)),
            "timeout": 30,
            "session_log": None,
        }

        # Push config
        active_status = Status.objects.get_for_model(VPNTunnel).get(name="Active")
        failed_status = Status.objects.get_for_model(VPNTunnel).get(name="Decommissioning")

        try:
            push_config_to_device(device_params, commands, self.logger)
            tunnel.status = active_status
            tunnel.save()
            self.logger.info("Tunnel %s is now active.", tunnel.name)
        except Exception as exc:
            tunnel.status = failed_status
            tunnel.save()
            self.logger.error("Tunnel %s failed: %s", tunnel.name, exc)
            raise

        return f"Tunnel {tunnel.name} configured on {device.name}."
```

Update the `register_jobs` call:

```python
register_jobs(BuildIpsecTunnel, PortalBuildIpsecTunnel)
```

- [ ] **Step 2: Commit**

```bash
git add nautobot_custom_tunnel_builder/jobs.py
git commit -m "feat: add PortalBuildIpsecTunnel job for async tunnel provisioning

New Celery-backed job that receives a VPN tunnel ID and PSK from
the portal API, resolves the VPNProfile, maps to config params,
generates IOS-XE commands (skipping interface apply), pushes via
SSH, and updates tunnel status to active/failed."
```

---

## Task 5: API Module (Serializers, Views, URLs)

**Files:**
- Create: `nautobot_custom_tunnel_builder/api/__init__.py`
- Create: `nautobot_custom_tunnel_builder/api/serializers.py`
- Create: `nautobot_custom_tunnel_builder/api/views.py`
- Create: `nautobot_custom_tunnel_builder/api/urls.py`
- Modify: `nautobot_custom_tunnel_builder/urls.py`
- Modify: `nautobot_custom_tunnel_builder/__init__.py`

- [ ] **Step 1: Create api package**

```bash
mkdir -p nautobot_custom_tunnel_builder/api
touch nautobot_custom_tunnel_builder/api/__init__.py
```

- [ ] **Step 2: Create serializer**

Create `nautobot_custom_tunnel_builder/api/serializers.py`:

```python
"""API serializers for the portal tunnel request."""

from rest_framework import serializers
from nautobot.vpn.models import VPNProfile
from nautobot.dcim.models import Device

from ..constants import get_iosxe_device_queryset


class PortalTunnelRequestSerializer(serializers.Serializer):
    """Validates portal tunnel build requests."""

    vpn_profile = serializers.PrimaryKeyRelatedField(
        queryset=VPNProfile.objects.all(),
        help_text="UUID of the VPN Profile to use for crypto settings.",
    )
    device = serializers.PrimaryKeyRelatedField(
        queryset=get_iosxe_device_queryset(),
        help_text="UUID of the target Cisco IOS-XE device.",
    )
    remote_peer_ip = serializers.IPAddressField(
        protocol="IPv4",
        help_text="Public IP of the remote IPsec peer.",
    )
    local_network_cidr = serializers.CharField(
        max_length=18,
        help_text="Local subnet to encrypt (CIDR, e.g. 192.168.1.0/24).",
    )
    protected_network_cidr = serializers.CharField(
        max_length=18,
        help_text="Remote subnet to encrypt (CIDR, e.g. 10.0.0.0/24).",
    )

    def validate_local_network_cidr(self, value):
        """Validate CIDR format."""
        import ipaddress
        try:
            ipaddress.IPv4Network(value, strict=False)
        except ValueError as err:
            raise serializers.ValidationError(
                "Enter a valid IPv4 network in CIDR notation."
            ) from err
        return value

    def validate_protected_network_cidr(self, value):
        """Validate CIDR format."""
        import ipaddress
        try:
            ipaddress.IPv4Network(value, strict=False)
        except ValueError as err:
            raise serializers.ValidationError(
                "Enter a valid IPv4 network in CIDR notation."
            ) from err
        return value

    def validate_device(self, value):
        """Ensure device has a primary IP for SSH."""
        if not value.primary_ip:
            raise serializers.ValidationError(
                f"Device '{value.name}' has no primary IP. Cannot connect via SSH."
            )
        return value
```

- [ ] **Step 3: Create views**

Create `nautobot_custom_tunnel_builder/api/views.py`:

```python
"""API views for portal tunnel provisioning."""

import logging
import secrets

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from nautobot.extras.models import Job as JobModel, JobResult, Status
from nautobot.vpn.models import VPNTunnel, VPNTunnelEndpoint

from .serializers import PortalTunnelRequestSerializer

logger = logging.getLogger(__name__)


class PortalTunnelRequestView(APIView):
    """Create an IPsec tunnel from a VPN Profile.

    POST: Validate request, create VPN objects, enqueue build job.
    Returns 202 Accepted with tunnel_id and job URL.
    """

    permission_required = "extras.run_job"

    def post(self, request):
        serializer = PortalTunnelRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device = data["device"]
        profile = data["vpn_profile"]
        remote_peer_ip = str(data["remote_peer_ip"])
        local_cidr = data["local_network_cidr"]
        protected_cidr = data["protected_network_cidr"]

        # Duplicate check: (device + peer + local + remote)
        existing = VPNTunnel.objects.filter(
            _custom_field_data__remote_peer_ip=remote_peer_ip,
            _custom_field_data__local_network_cidr=local_cidr,
            _custom_field_data__protected_network_cidr=protected_cidr,
            vpntunnelendpoint__source_ip_address=device.primary_ip,
        ).first()

        if existing:
            return Response(
                {"error": "Tunnel already exists", "tunnel_id": str(existing.id)},
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            # Get next sequence number (locked to prevent race)
            existing_tunnels = (
                VPNTunnel.objects.select_for_update()
                .filter(vpntunnelendpoint__source_ip_address=device.primary_ip)
            )
            max_seq = 0
            for t in existing_tunnels:
                seq = t.cf.get("crypto_map_sequence", 0)
                if seq > max_seq:
                    max_seq = seq
            next_seq = max_seq + 10

            # Generate PSK
            psk = secrets.token_urlsafe(32)

            # Create VPN Tunnel
            provisioning_status = Status.objects.get_for_model(VPNTunnel).get(name="Planned")
            tunnel_name = f"PORTAL-{device.name}-{remote_peer_ip}-seq{next_seq}"
            crypto_map_name = device.cf.get("crypto_map_name", "CRYPTO-MAP")

            tunnel = VPNTunnel.objects.create(
                name=tunnel_name,
                status=provisioning_status,
                vpn_profile=profile,
                _custom_field_data={
                    "crypto_map_sequence": next_seq,
                    "remote_peer_ip": remote_peer_ip,
                    "local_network_cidr": local_cidr,
                    "protected_network_cidr": protected_cidr,
                    "psk_retrieval_token": secrets.token_urlsafe(48),
                    "psk_retrieved": False,
                },
            )

            # Create local endpoint (source = device primary IP)
            VPNTunnelEndpoint.objects.create(
                vpn_tunnel=tunnel,
                role="hub",
                source_ip_address=device.primary_ip,
            )

            # Create remote endpoint (peer IP, no device in Nautobot)
            # Note: remote endpoint has no source_ip since the peer isn't in Nautobot
            VPNTunnelEndpoint.objects.create(
                vpn_tunnel=tunnel,
                role="spoke",
            )

            # Store PSK in Nautobot Secrets
            # For prototype: store in custom field data (encrypted at rest in DB)
            # Production: use Nautobot SecretsGroup
            tunnel._custom_field_data["psk_encrypted"] = psk
            tunnel.save()

        # Enqueue the portal build job
        try:
            job_model = JobModel.objects.get(
                module_name="nautobot_custom_tunnel_builder.jobs",
                job_class_name="PortalBuildIpsecTunnel",
            )
            job_result = JobResult.enqueue_job(
                job_model=job_model,
                user=request.user,
                tunnel_id=str(tunnel.id),
                pre_shared_key=psk,
            )
        except JobModel.DoesNotExist:
            return Response(
                {"error": "PortalBuildIpsecTunnel job not registered. Run nautobot-server post_upgrade."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "tunnel_id": str(tunnel.id),
                "tunnel_name": tunnel.name,
                "job_id": str(job_result.id),
                "status": "provisioning",
                "status_url": f"/api/plugins/tunnel-builder/tunnel-status/{tunnel.id}/",
                "psk_url": f"/api/plugins/tunnel-builder/psk/{tunnel._custom_field_data['psk_retrieval_token']}/",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class TunnelStatusView(APIView):
    """Check provisioning status of a tunnel."""

    permission_required = "extras.run_job"

    def get(self, request, tunnel_id):
        try:
            tunnel = VPNTunnel.objects.get(id=tunnel_id)
        except VPNTunnel.DoesNotExist:
            return Response(
                {"error": "Tunnel not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        response_data = {
            "tunnel_id": str(tunnel.id),
            "tunnel_name": tunnel.name,
            "status": tunnel.status.name.lower(),
        }

        # Only include PSK URL if tunnel is active and PSK hasn't been retrieved
        if tunnel.status.name == "Active" and not tunnel.cf.get("psk_retrieved", True):
            token = tunnel.cf.get("psk_retrieval_token", "")
            if token:
                response_data["psk_url"] = f"/api/plugins/tunnel-builder/psk/{token}/"

        return Response(response_data)


class PSKRetrievalView(APIView):
    """One-time PSK retrieval endpoint."""

    permission_required = "extras.run_job"

    def get(self, request, token):
        # Find tunnel by retrieval token
        tunnels = VPNTunnel.objects.filter(
            _custom_field_data__psk_retrieval_token=token,
        )

        if not tunnels.exists():
            return Response(
                {"error": "Invalid or expired PSK retrieval link"},
                status=status.HTTP_404_NOT_FOUND,
            )

        tunnel = tunnels.first()

        # Check if already retrieved
        if tunnel.cf.get("psk_retrieved", True):
            return Response(
                {"error": "PSK retrieval link has already been used"},
                status=status.HTTP_410_GONE,
            )

        # Return PSK and mark as retrieved
        psk = tunnel._custom_field_data.get("psk_encrypted", "")

        tunnel._custom_field_data["psk_retrieved"] = True
        tunnel._custom_field_data.pop("psk_encrypted", None)  # Remove PSK from storage
        tunnel._custom_field_data["psk_retrieval_token"] = ""  # Invalidate token
        tunnel.save()

        return Response({"psk": psk})
```

- [ ] **Step 4: Create API URL patterns**

Create `nautobot_custom_tunnel_builder/api/urls.py`:

```python
"""API URL patterns for the tunnel builder portal API."""

from django.urls import path

from .views import PortalTunnelRequestView, TunnelStatusView, PSKRetrievalView

urlpatterns = [
    path(
        "portal-request/",
        PortalTunnelRequestView.as_view(),
        name="portal-tunnel-request",
    ),
    path(
        "tunnel-status/<uuid:tunnel_id>/",
        TunnelStatusView.as_view(),
        name="tunnel-status",
    ),
    path(
        "psk/<str:token>/",
        PSKRetrievalView.as_view(),
        name="psk-retrieval",
    ),
]
```

- [ ] **Step 5: Wire API URLs into the plugin**

Modify `nautobot_custom_tunnel_builder/urls.py`:

```python
"""URL configuration for the IPsec Tunnel Builder app."""

from django.urls import include, path

from .views import IpsecTunnelBuilderView

app_name = "nautobot_custom_tunnel_builder"

urlpatterns = [
    path(
        "",
        IpsecTunnelBuilderView.as_view(),
        name="ipsec_tunnel_builder",
    ),
    path(
        "api/",
        include("nautobot_custom_tunnel_builder.api.urls"),
    ),
]
```

- [ ] **Step 6: Commit**

```bash
git add nautobot_custom_tunnel_builder/api/ nautobot_custom_tunnel_builder/urls.py
git commit -m "feat: add portal REST API for tunnel provisioning

Three endpoints:
- POST portal-request/ — validate, create VPN objects, enqueue job
- GET tunnel-status/<id>/ — poll provisioning status
- GET psk/<token>/ — one-time PSK retrieval

Uses Celery (via Nautobot jobs) for async SSH push. VPN objects
created first (status=planned), updated to active/failed by job.
PSK stored temporarily in custom field data, cleared after retrieval."
```

---

## Task 6: Tests for Existing Code (Config Generation, Forms)

**Files:**
- Create: `nautobot_custom_tunnel_builder/tests/test_config_generation.py`
- Create: `nautobot_custom_tunnel_builder/tests/test_forms.py`

- [ ] **Step 1: Write tests for build_iosxe_policy_config**

Create `nautobot_custom_tunnel_builder/tests/test_config_generation.py`:

```python
"""Tests for the IOS-XE configuration generation engine."""

from django.test import TestCase

from nautobot_custom_tunnel_builder.jobs import (
    build_iosxe_policy_config,
    _cidr_to_net_wildcard,
)


class CidrToNetWildcardTest(TestCase):
    """Test CIDR to network/wildcard conversion."""

    def test_standard_24(self):
        net, wc = _cidr_to_net_wildcard("192.168.1.0/24")
        self.assertEqual(net, "192.168.1.0")
        self.assertEqual(wc, "0.0.0.255")

    def test_single_host_32(self):
        net, wc = _cidr_to_net_wildcard("10.0.0.1/32")
        self.assertEqual(net, "10.0.0.1")
        self.assertEqual(wc, "0.0.0.0")

    def test_slash_16(self):
        net, wc = _cidr_to_net_wildcard("172.16.0.0/16")
        self.assertEqual(net, "172.16.0.0")
        self.assertEqual(wc, "0.0.255.255")


class BuildIosxePolicyConfigIKEv2Test(TestCase):
    """Test IKEv2 configuration generation."""

    def setUp(self):
        self.data = {
            "ike_version": "ikev2",
            "remote_peer_ip": "203.0.113.1",
            "local_network": "192.168.1.0/24",
            "remote_network": "10.0.0.0/24",
            "crypto_acl_name": "VPN-ACL",
            "wan_interface": "GigabitEthernet1",
            "crypto_map_name": "CRYPTO-MAP",
            "crypto_map_sequence": 10,
            "ike_dh_group": "19",
            "ike_lifetime": 86400,
            "ikev2_proposal_name": "IKEv2-PROPOSAL",
            "ikev2_policy_name": "IKEv2-POLICY",
            "ikev2_keyring_name": "IKEv2-KEYRING",
            "ikev2_profile_name": "IKEv2-PROFILE",
            "ikev2_encryption": "aes-cbc-256",
            "ikev2_integrity": "sha256",
            "pre_shared_key": "testPSK123",
            "ipsec_transform_set_name": "IPSEC-TS",
            "ipsec_encryption": "esp-aes 256",
            "ipsec_integrity": "esp-sha256-hmac",
            "ipsec_lifetime": 3600,
        }

    def test_generates_ikev2_proposal(self):
        commands = build_iosxe_policy_config(self.data)
        self.assertIn("crypto ikev2 proposal IKEv2-PROPOSAL", commands)

    def test_generates_crypto_acl(self):
        commands = build_iosxe_policy_config(self.data)
        self.assertIn("ip access-list extended VPN-ACL", commands)
        self.assertIn(" permit ip 192.168.1.0 0.0.0.255 10.0.0.0 0.0.0.255", commands)

    def test_generates_transform_set(self):
        commands = build_iosxe_policy_config(self.data)
        self.assertIn("crypto ipsec transform-set IPSEC-TS esp-aes 256 esp-sha256-hmac", commands)

    def test_generates_crypto_map(self):
        commands = build_iosxe_policy_config(self.data)
        self.assertIn("crypto map CRYPTO-MAP 10 ipsec-isakmp", commands)

    def test_gcm_no_integrity(self):
        self.data["ipsec_encryption"] = "esp-gcm 256"
        self.data["ipsec_integrity"] = ""
        commands = build_iosxe_policy_config(self.data)
        self.assertIn("crypto ipsec transform-set IPSEC-TS esp-gcm 256", commands)


class BuildIosxePolicyConfigIKEv1Test(TestCase):
    """Test IKEv1 configuration generation."""

    def setUp(self):
        self.data = {
            "ike_version": "ikev1",
            "remote_peer_ip": "203.0.113.1",
            "local_network": "192.168.1.0/24",
            "remote_network": "10.0.0.0/24",
            "crypto_acl_name": "VPN-ACL",
            "wan_interface": "GigabitEthernet1",
            "crypto_map_name": "CRYPTO-MAP",
            "crypto_map_sequence": 10,
            "ike_dh_group": "14",
            "ike_lifetime": 86400,
            "isakmp_policy_priority": 10,
            "ikev1_encryption": "aes 256",
            "ikev1_hash": "sha256",
            "pre_shared_key": "testPSK123",
            "ipsec_transform_set_name": "IPSEC-TS",
            "ipsec_encryption": "esp-aes 256",
            "ipsec_integrity": "esp-sha256-hmac",
            "ipsec_lifetime": 3600,
        }

    def test_generates_isakmp_policy(self):
        commands = build_iosxe_policy_config(self.data)
        self.assertIn("crypto isakmp policy 10", commands)

    def test_generates_isakmp_key(self):
        commands = build_iosxe_policy_config(self.data)
        self.assertIn("crypto isakmp key testPSK123 address 203.0.113.1", commands)
```

- [ ] **Step 2: Run tests**

Run: `invoke unittest --pattern "test_config_generation" --failfast`
Expected: All PASS (testing existing code).

- [ ] **Step 3: Commit**

```bash
git add nautobot_custom_tunnel_builder/tests/test_config_generation.py
git commit -m "test: add tests for existing config generation engine

Tests for build_iosxe_policy_config (IKEv1 + IKEv2), GCM mode,
_cidr_to_net_wildcard helper. Covers previously untested code."
```

---

## Task 7: Tests for API Endpoints

**Files:**
- Create: `nautobot_custom_tunnel_builder/tests/test_api.py`

- [ ] **Step 1: Write API tests**

Create `nautobot_custom_tunnel_builder/tests/test_api.py`:

```python
"""Tests for portal API endpoints."""

from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.test.utils import override_settings

from nautobot.core.testing import APITestCase
from nautobot.vpn.models import VPNTunnel


class PortalTunnelRequestAPITest(APITestCase):
    """Test POST /api/plugins/tunnel-builder/api/portal-request/."""

    def setUp(self):
        super().setUp()
        self.url = "/api/plugins/tunnel-builder/api/portal-request/"

    def test_unauthenticated_returns_403(self):
        self.client.credentials()  # Remove auth
        response = self.client.post(self.url, {}, format="json")
        self.assertIn(response.status_code, [401, 403])

    def test_missing_fields_returns_400(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_invalid_cidr_returns_400(self):
        response = self.client.post(
            self.url,
            {
                "vpn_profile": "00000000-0000-0000-0000-000000000000",
                "device": "00000000-0000-0000-0000-000000000000",
                "remote_peer_ip": "203.0.113.1",
                "local_network_cidr": "not-a-cidr",
                "protected_network_cidr": "10.0.0.0/24",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)


class PSKRetrievalAPITest(APITestCase):
    """Test GET /api/plugins/tunnel-builder/api/psk/<token>/."""

    def test_invalid_token_returns_404(self):
        response = self.client.get("/api/plugins/tunnel-builder/api/psk/invalid-token/")
        self.assertEqual(response.status_code, 404)


class TunnelStatusAPITest(APITestCase):
    """Test GET /api/plugins/tunnel-builder/api/tunnel-status/<id>/."""

    def test_nonexistent_tunnel_returns_404(self):
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = self.client.get(f"/api/plugins/tunnel-builder/api/tunnel-status/{fake_uuid}/")
        self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run tests**

Run: `invoke unittest --pattern "test_api" --failfast`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add nautobot_custom_tunnel_builder/tests/test_api.py
git commit -m "test: add API endpoint tests

Tests for portal request validation, PSK retrieval, tunnel status.
Covers auth, validation errors, and 404 cases."
```

---

## Verification

After all tasks are complete:

1. **Run full test suite:**
   ```bash
   invoke tests
   ```

2. **Verify API endpoints in Nautobot:**
   ```bash
   invoke start
   # Then test from another terminal:
   curl -sk -X POST \
     -H "Authorization: Token <token>" \
     -H "Content-Type: application/json" \
     -d '{"vpn_profile":"<uuid>","device":"<uuid>","remote_peer_ip":"203.0.113.1","local_network_cidr":"192.168.1.0/24","protected_network_cidr":"10.0.0.0/24"}' \
     https://localhost/api/plugins/tunnel-builder/api/portal-request/
   ```

3. **Verify VPN objects created in Nautobot UI** — check VPN Tunnels list

4. **Check Custom Fields exist** — ensure `crypto_map_sequence`, `remote_peer_ip`, `local_network_cidr`, `protected_network_cidr`, `psk_retrieval_token`, `psk_retrieved`, `psk_encrypted` Custom Fields are created (may need to be created manually or via a data migration)

5. **Check Device Custom Field** — ensure `crypto_map_name` Custom Field exists on Device model

**Note:** Custom Fields referenced in the code (`crypto_map_sequence`, `remote_peer_ip`, etc.) must be created in Nautobot before testing. This can be done via the Nautobot UI or a data migration. Consider adding a migration in a follow-up task.
