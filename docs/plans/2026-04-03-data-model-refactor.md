# Portal API Data Model Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the portal API to use Nautobot's native VPN object hierarchy (VPN > VPNTunnel > VPNTunnelEndpoint) with proper native fields, eliminating redundant custom fields on VPNTunnel.

**Architecture:** Replace flat `_custom_field_data` bag on VPNTunnel with: member Device + dummy0 interface, VPN container per member+location, cloned VPNProfile per tunnel, Prefix objects in "Members" namespace, and VPNTunnelEndpoints with native `source_ip_address` and `protected_prefixes`. Remove `wan_interface` from both form and portal paths since crypto map is already applied.

**Tech Stack:** Python/Django, Nautobot 3.x VPN models, Django REST Framework, Nautobot CustomField/Prefix/Namespace models.

**Design doc:** `docs/plans/mdean-feature-portal-api-design-20260403-113000.md`

---

## Context

The current portal API (`api/views.py`) stuffs all tunnel parameters into `_custom_field_data` on VPNTunnel as a flat bag of strings. The design doc (approved 2026-04-03) specifies using Nautobot's native VPN hierarchy: VPN > VPNTunnel > VPNTunnelEndpoint with native fields (`source_ip_address`, `protected_prefixes`) and proper object relationships (member Device, cloned VPNProfile, Prefix objects).

### Key Changes from Current Code

- **Serializer:** New fields (`member_name`, `member_display_name`, `location_city`, `location_state`, `template_vpn_profile`); rename `local_network_cidr` → `hub_protected_prefix`, `protected_network_cidr` → `member_protected_prefix`
- **api/views.py:** Full rewrite of object creation flow (7-step hierarchy from design doc)
- **Migration:** Add 5th custom field (`psk_encrypted`), move fields to correct content types
- **jobs.py:** Portal job reads from native objects; remove `wan_interface` from config builder + internal job
- **forms.py + views.py:** Remove `wan_interface` field
- **Sequence numbering:** Start at 2000, step 10 (was: start at 10, step 10)

### Current Custom Fields (migration 0001)

| Key | Content Type | Notes |
|---|---|---|
| `custom_tunnel_builder_crypto_map_name` | vpntunnelendpoint | Correct per design |
| `custom_tunnel_builder_crypto_map_sequence` | vpnprofile | Correct per design |
| `custom_tunnel_builder_psk_retrieval_token` | vpnprofile | Correct per design |
| `custom_tunnel_builder_psk_retrieved` | vpnprofile | Correct per design |
| `custom_tunnel_builder_psk_encrypted` | **MISSING** | Needs adding to vpnprofile |

---

## File Structure

```text
nautobot_custom_tunnel_builder/
├── constants.py                   ← MODIFY: add sequence start/step constants
├── mapping.py                     ← (unchanged)
├── forms.py                       ← MODIFY: remove wan_interface
├── views.py                       ← MODIFY: remove wan_interface from job_kwargs
├── jobs.py                        ← MODIFY: remove wan_interface from BuildIpsecTunnel + config builder
├── migrations/
│   └── 0002_add_psk_encrypted.py  ← NEW: add psk_encrypted CF
├── api/
│   ├── serializers.py             ← MODIFY: new API fields
│   ├── views.py                   ← MODIFY: full VPN hierarchy creation
│   └── urls.py                    ← (unchanged)
├── tests/
│   ├── test_config_generation.py  ← MODIFY: remove wan_interface from test data
│   ├── test_mapping.py            ← (unchanged)
│   ├── test_api.py                ← MODIFY: update for new serializer fields
│   └── test_constants.py          ← (unchanged)
```

---

## Task 1: Remove `wan_interface` from Config Builder, Internal Job, and Form

The design doc says: "Neither the portal job nor the form job should use `wan_interface`. The crypto map is already applied to the concentrator's WAN interface." This is a standalone change that unblocks the rest.

**Files:**
- Modify: `nautobot_custom_tunnel_builder/jobs.py:147-197` (build_iosxe_policy_config)
- Modify: `nautobot_custom_tunnel_builder/jobs.py:229-555` (BuildIpsecTunnel job vars + run)
- Modify: `nautobot_custom_tunnel_builder/forms.py:89-95` (wan_interface field)
- Modify: `nautobot_custom_tunnel_builder/views.py:71` (wan_interface in job_kwargs)
- Modify: `nautobot_custom_tunnel_builder/tests/test_config_generation.py`

- [ ] **Step 1: Update test data helpers to remove `wan_interface`**

In `nautobot_custom_tunnel_builder/tests/test_config_generation.py`, remove `"wan_interface"` from both `_ikev2_data()` and `_ikev1_data()` helper dicts.

```python
# In _ikev2_data(), remove this line:
#     "wan_interface": "GigabitEthernet1",

# In _ikev1_data(), remove this line:
#     "wan_interface": "GigabitEthernet2",
```

- [ ] **Step 2: Update config generation tests**

Remove the two `test_wan_interface_applied` tests and update `test_interface_is_last` in the order test class.

In `BuildIosxePolicyConfigIKEv2Test`, remove:
```python
def test_wan_interface_applied(self):
    self.assertIn("interface GigabitEthernet1", self.commands)
    self.assertIn(" crypto map CRYPTO-MAP", self.commands)
```

In `BuildIosxePolicyConfigIKEv1Test`, remove:
```python
def test_wan_interface_applied(self):
    self.assertIn("interface GigabitEthernet2", self.commands)
    self.assertIn(" crypto map CMAP-V1", self.commands)
```

In `BuildIosxePolicyConfigOrderTest`, replace `test_interface_is_last` with:
```python
def test_crypto_map_is_last_section(self):
    commands = build_iosxe_policy_config(_ikev2_data())
    # Last command should be match address (end of crypto map block)
    last_commands = commands[-3:]
    map_cmds = [c for c in last_commands if "match address" in c or "set " in c or "crypto map" in c.strip()]
    self.assertTrue(len(map_cmds) > 0, "Crypto map block should be at the end")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `poetry run pytest nautobot_custom_tunnel_builder/tests/test_config_generation.py -v --tb=short`
Expected: Failures because `build_iosxe_policy_config` still expects `wan_interface` in the data dict.

- [ ] **Step 4: Remove `wan_interface` from `build_iosxe_policy_config`**

In `nautobot_custom_tunnel_builder/jobs.py`, remove the last two lines of `build_iosxe_policy_config()` (lines 193-196):

```python
# DELETE these lines:
    # Apply crypto map to WAN interface
    commands.append(f"interface {data['wan_interface']}")
    commands.append(f" crypto map {map_name}")
```

- [ ] **Step 5: Run config generation tests to verify they pass**

Run: `poetry run pytest nautobot_custom_tunnel_builder/tests/test_config_generation.py -v --tb=short`
Expected: All pass.

- [ ] **Step 6: Remove `wan_interface` from `BuildIpsecTunnel` job**

In `nautobot_custom_tunnel_builder/jobs.py`:

Remove the `wan_interface` StringVar declaration (lines 267-272):
```python
# DELETE:
    wan_interface = StringVar(
        description="Physical interface where the crypto map is applied (e.g. GigabitEthernet1).",
        label="WAN Interface",
        default="GigabitEthernet1",
        max_length=64,
    )
```

Remove `wan_interface` from the `run()` method signature (line 437) and from `job_data` dict (line 473):
```python
# DELETE from run() signature:
#     wan_interface,

# DELETE from job_data dict:
#     "wan_interface": wan_interface,
```

- [ ] **Step 7: Remove `wan_interface` from forms.py**

In `nautobot_custom_tunnel_builder/forms.py`, delete the `wan_interface` field (lines 89-95):
```python
# DELETE:
    wan_interface = forms.CharField(
        label="WAN Interface",
        max_length=64,
        initial="GigabitEthernet1",
        help_text="Physical interface where the crypto map will be applied.",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "GigabitEthernet1"}),
    )
```

- [ ] **Step 8: Remove `wan_interface` from views.py**

In `nautobot_custom_tunnel_builder/views.py`, remove `wan_interface` from `job_kwargs` dict (line 71):
```python
# DELETE:
#     "wan_interface": data["wan_interface"],
```

- [ ] **Step 9: Remove `wan_interface` from portal job's strip logic**

In `nautobot_custom_tunnel_builder/jobs.py`, the `PortalBuildIpsecTunnel.run()` method (lines 673-676) strips the interface/crypto-map-apply lines. Since those lines no longer exist in the output, remove this dead code:

```python
# DELETE:
        # Remove interface/crypto-map-apply lines (last 2 if they start with "interface ")
        # The crypto map is already applied to the device; we only add new entries.
        if len(commands) >= 2 and commands[-2].strip().startswith("interface "):
            commands = commands[:-2]
```

- [ ] **Step 10: Run full test suite**

Run: `poetry run pytest nautobot_custom_tunnel_builder/tests/ -v --tb=short`
Expected: All pass. The `test_no_wan_interface_in_output` in test_mapping.py should still pass (it checks `mapping.py` output, which already excludes `wan_interface`).

- [ ] **Step 11: Commit**

```bash
git add nautobot_custom_tunnel_builder/jobs.py nautobot_custom_tunnel_builder/forms.py nautobot_custom_tunnel_builder/views.py nautobot_custom_tunnel_builder/tests/test_config_generation.py
git commit -m "refactor: remove wan_interface from config builder, form, and jobs

Crypto map is already applied to the concentrator's WAN interface.
Neither the portal job nor the internal form job needs to re-apply it."
```

---

## Task 2: Add `psk_encrypted` Custom Field via Migration

The current migration (0001) creates 4 custom fields but is missing `psk_encrypted` on VPNProfile.

**Files:**
- Create: `nautobot_custom_tunnel_builder/migrations/0002_add_psk_encrypted.py`

- [ ] **Step 1: Create the migration file**

Create `nautobot_custom_tunnel_builder/migrations/0002_add_psk_encrypted.py`:

```python
"""Add psk_encrypted custom field on VPNProfile."""

from django.db import migrations


def create_psk_encrypted_field(apps, schema_editor):
    """Create the psk_encrypted CustomField on VPNProfile."""
    CustomField = apps.get_model("extras", "CustomField")
    ContentType = apps.get_model("contenttypes", "ContentType")

    vpnprofile_ct = ContentType.objects.get(app_label="vpn", model="vpnprofile")

    cf, _ = CustomField.objects.get_or_create(
        key="custom_tunnel_builder_psk_encrypted",
        defaults={
            "label": "PSK Encrypted",
            "type": "text",
            "description": "Temporary encrypted PSK storage. Cleared after one-time retrieval.",
            "grouping": "Custom Tunnel Builder",
            "weight": 500,
            "required": False,
            "advanced_ui": True,
        },
    )
    cf.content_types.add(vpnprofile_ct)


def remove_psk_encrypted_field(apps, schema_editor):
    """Reverse: delete the psk_encrypted CustomField."""
    CustomField = apps.get_model("extras", "CustomField")
    CustomField.objects.filter(key="custom_tunnel_builder_psk_encrypted").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nautobot_custom_tunnel_builder", "0001_create_custom_fields"),
        ("extras", "0001_initial"),
        ("vpn", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_psk_encrypted_field,
            remove_psk_encrypted_field,
        ),
    ]
```

- [ ] **Step 2: Verify migration file is valid**

Run: `poetry run python -c "import importlib; importlib.import_module('nautobot_custom_tunnel_builder.migrations.0002_add_psk_encrypted'); print('OK')"`
Expected: `OK` (no syntax errors).

- [ ] **Step 3: Commit**

```bash
git add nautobot_custom_tunnel_builder/migrations/0002_add_psk_encrypted.py
git commit -m "feat: add psk_encrypted custom field migration on VPNProfile"
```

---

## Task 3: Add Sequence Constants to `constants.py`

The design doc specifies sequence starts at 2000 with step 10. Add constants so the values aren't magic numbers.

**Files:**
- Modify: `nautobot_custom_tunnel_builder/constants.py`

- [ ] **Step 1: Add constants**

Add to the end of `nautobot_custom_tunnel_builder/constants.py` (before the `get_iosxe_device_queryset` function):

```python
# ---------------------------------------------------------------------------
# Portal tunnel sequence numbering
# ---------------------------------------------------------------------------

PORTAL_SEQUENCE_START = 2000
PORTAL_SEQUENCE_STEP = 10
```

- [ ] **Step 2: Commit**

```bash
git add nautobot_custom_tunnel_builder/constants.py
git commit -m "feat: add portal sequence start/step constants"
```

---

## Task 4: Update Serializer for New API Fields

The API request shape changes per the design doc: new member/location fields, renamed network fields, `template_vpn_profile` instead of `vpn_profile`.

**Files:**
- Modify: `nautobot_custom_tunnel_builder/api/serializers.py`
- Modify: `nautobot_custom_tunnel_builder/tests/test_api.py`

- [ ] **Step 1: Update test for new required fields**

In `nautobot_custom_tunnel_builder/tests/test_api.py`, update `test_empty_body_returns_400` to check for the new field names:

```python
def test_empty_body_returns_400(self):
    """POST with empty body returns 400 with field errors."""
    response = self._post(PORTAL_REQUEST_URL)
    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    data = response.json()
    for field in (
        "member_name",
        "location_city",
        "location_state",
        "device",
        "remote_peer_ip",
        "hub_protected_prefix",
        "member_protected_prefix",
    ):
        self.assertIn(field, data, f"Expected error for missing field: {field}")
```

Update `test_missing_vpn_profile_returns_400` → rename to `test_missing_member_name_returns_400`:
```python
def test_missing_member_name_returns_400(self):
    """POST without member_name returns 400."""
    payload = {
        "location_city": "Jackson",
        "location_state": "MS",
        "device": str(uuid.uuid4()),
        "remote_peer_ip": "203.0.113.1",
        "hub_protected_prefix": "192.168.1.0/24",
        "member_protected_prefix": "10.0.0.0/24",
    }
    response = self._post(PORTAL_REQUEST_URL, payload)
    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    self.assertIn("member_name", response.json())
```

Update `test_invalid_cidr_local_returns_400` and `test_invalid_cidr_protected_returns_400` to use `hub_protected_prefix` and `member_protected_prefix`:
```python
def test_invalid_cidr_hub_returns_400(self):
    """POST with invalid hub_protected_prefix returns 400."""
    payload = {
        "member_name": "acme-corp",
        "location_city": "Jackson",
        "location_state": "MS",
        "device": str(uuid.uuid4()),
        "remote_peer_ip": "203.0.113.1",
        "hub_protected_prefix": "not-a-cidr",
        "member_protected_prefix": "10.0.0.0/24",
    }
    response = self._post(PORTAL_REQUEST_URL, payload)
    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    self.assertIn("hub_protected_prefix", response.json())

def test_invalid_cidr_member_returns_400(self):
    """POST with invalid member_protected_prefix returns 400."""
    payload = {
        "member_name": "acme-corp",
        "location_city": "Jackson",
        "location_state": "MS",
        "device": str(uuid.uuid4()),
        "remote_peer_ip": "203.0.113.1",
        "hub_protected_prefix": "192.168.1.0/24",
        "member_protected_prefix": "garbage",
    }
    response = self._post(PORTAL_REQUEST_URL, payload)
    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    self.assertIn("member_protected_prefix", response.json())
```

Remove `test_missing_device_returns_400`, `test_non_existent_profile_uuid_returns_400`, `test_non_existent_device_uuid_returns_400` (these test the old field names). Replace with:

```python
def test_non_existent_device_uuid_returns_400(self):
    """POST with a UUID that doesn't match any Device returns 400."""
    payload = {
        "member_name": "acme-corp",
        "location_city": "Jackson",
        "location_state": "MS",
        "device": str(uuid.uuid4()),
        "remote_peer_ip": "203.0.113.1",
        "hub_protected_prefix": "192.168.1.0/24",
        "member_protected_prefix": "10.0.0.0/24",
    }
    response = self._post(PORTAL_REQUEST_URL, payload)
    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    self.assertIn("device", response.json())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest nautobot_custom_tunnel_builder/tests/test_api.py -v --tb=short`
Expected: Failures because serializer still has old fields.

- [ ] **Step 3: Rewrite the serializer**

Replace `nautobot_custom_tunnel_builder/api/serializers.py` with:

```python
"""DRF serializers for the portal API."""

import ipaddress
import re

from rest_framework import serializers

from ..constants import get_iosxe_device_queryset


class PortalTunnelRequestSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Validate a portal tunnel provisioning request.

    Accepts member identity + location + network params. The template_vpn_profile
    field is optional for forward compatibility (beta uses a hardcoded profile).
    """

    member_name = serializers.SlugField(
        max_length=64,
        help_text="Machine-readable member identifier (lowercase, hyphens). E.g. 'acme-corp'.",
    )

    member_display_name = serializers.CharField(
        max_length=128,
        required=False,
        default="",
        help_text="Human-friendly member name for Nautobot UI. E.g. 'Acme Corp'. Defaults to member_name if blank.",
    )

    location_city = serializers.CharField(
        max_length=64,
        help_text="City name for the member location. E.g. 'Jackson'.",
    )

    location_state = serializers.CharField(
        max_length=2,
        help_text="Two-letter state abbreviation. E.g. 'MS'.",
    )

    device = serializers.PrimaryKeyRelatedField(
        queryset=get_iosxe_device_queryset(),
        help_text="UUID of the hub/concentrator IOS-XE device.",
    )

    template_vpn_profile = serializers.UUIDField(
        required=False,
        help_text="UUID of the template VPNProfile to clone. Optional for beta (hardcoded profile used).",
    )

    remote_peer_ip = serializers.IPAddressField(
        protocol="IPv4",
        help_text="Public IP address of the remote (member) IPsec peer.",
    )

    hub_protected_prefix = serializers.CharField(
        max_length=18,
        help_text="Hub-side protected subnet in CIDR notation (e.g. 10.100.0.0/24).",
    )

    member_protected_prefix = serializers.CharField(
        max_length=18,
        help_text="Member-side protected subnet in CIDR notation (e.g. 192.168.1.0/24).",
    )

    def validate_member_name(self, value):
        """Ensure member_name is a valid slug (lowercase, hyphens, digits)."""
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", value):
            raise serializers.ValidationError(
                "member_name must be lowercase letters, digits, and hyphens (e.g. 'acme-corp')."
            )
        return value

    def validate_location_state(self, value):
        """Normalize state to uppercase."""
        return value.upper()

    def validate_hub_protected_prefix(self, value):
        """Validate that the value is a valid IPv4 CIDR network."""
        try:
            net = ipaddress.IPv4Network(value, strict=False)
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
            raise serializers.ValidationError(
                "Enter a valid IPv4 network in CIDR notation, e.g. 10.100.0.0/24."
            ) from exc
        return str(net)

    def validate_member_protected_prefix(self, value):
        """Validate that the value is a valid IPv4 CIDR network."""
        try:
            net = ipaddress.IPv4Network(value, strict=False)
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
            raise serializers.ValidationError(
                "Enter a valid IPv4 network in CIDR notation, e.g. 192.168.1.0/24."
            ) from exc
        return str(net)

    def validate_device(self, value):
        """Ensure the device has a primary IP for SSH connectivity."""
        if not value.primary_ip:
            raise serializers.ValidationError(
                f"Device '{value.name}' has no primary IP configured. "
                "Set a primary IPv4 address before requesting a tunnel."
            )
        return value

    def validate(self, attrs):
        """Set defaults: member_display_name from member_name if blank."""
        if not attrs.get("member_display_name"):
            attrs["member_display_name"] = attrs["member_name"].replace("-", " ").title()
        return attrs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest nautobot_custom_tunnel_builder/tests/test_api.py -v --tb=short`
Expected: All validation tests pass.

- [ ] **Step 5: Commit**

```bash
git add nautobot_custom_tunnel_builder/api/serializers.py nautobot_custom_tunnel_builder/tests/test_api.py
git commit -m "feat: update serializer for member/location API fields

New fields: member_name, member_display_name, location_city, location_state.
Renamed: local_network_cidr -> hub_protected_prefix, protected_network_cidr -> member_protected_prefix.
Added template_vpn_profile (optional, for forward compatibility)."
```

---

## Task 5: Rewrite `api/views.py` — Full VPN Hierarchy Creation

This is the core refactor. Replace the flat custom-field approach with the 7-step object creation flow from the design doc.

**Files:**
- Modify: `nautobot_custom_tunnel_builder/api/views.py`

- [ ] **Step 1: Rewrite `PortalTunnelRequestView.post()`**

Replace the entire `nautobot_custom_tunnel_builder/api/views.py` with:

```python
"""Portal API views for self-service IPsec tunnel provisioning."""

import logging
import secrets

from django.db import transaction
from django.db.models import Max
from nautobot.core.api.authentication import TokenAuthentication
from nautobot.dcim.models import DeviceType, Interface, Manufacturer
from nautobot.extras.models import Job as JobModel
from nautobot.extras.models import JobResult, Role, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix
from nautobot.vpn.models import VPN, VPNProfile, VPNTunnel, VPNTunnelEndpoint
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from ..constants import PORTAL_SEQUENCE_START, PORTAL_SEQUENCE_STEP
from .serializers import PortalTunnelRequestSerializer

logger = logging.getLogger(__name__)


def _location_slug(city: str, state: str) -> str:
    """Build a location slug from city + state: 'jackson-ms'."""
    return f"{city.lower().replace(' ', '-')}-{state.lower()}"


def _get_or_create_member_device(member_name, location_slug, location_obj):
    """Step 1: get_or_create member Device + dummy0 interface."""
    manufacturer, _ = Manufacturer.objects.get_or_create(
        name="Generic",
        defaults={"description": "Generic/virtual manufacturer for placeholder devices."},
    )
    device_type, _ = DeviceType.objects.get_or_create(
        model="Member VPN Endpoint",
        manufacturer=manufacturer,
        defaults={"description": "Virtual device representing a member VPN endpoint."},
    )
    role, _ = Role.objects.get_or_create(name="Member")
    role.content_types.add(
        *[ct for ct in role.content_types.all()]  # no-op if already set
    )
    # Ensure the Role applies to dcim.device
    from django.contrib.contenttypes.models import ContentType  # pylint: disable=import-outside-toplevel

    device_ct = ContentType.objects.get_for_model(
        __import__("nautobot.dcim.models", fromlist=["Device"]).Device
    )
    role.content_types.add(device_ct)

    device_name = f"member-{member_name}-{location_slug}"
    active_status = Status.objects.get_for_model(
        __import__("nautobot.dcim.models", fromlist=["Device"]).Device
    ).get(name="Active")

    from nautobot.dcim.models import Device  # pylint: disable=import-outside-toplevel

    device, _ = Device.objects.get_or_create(
        name=device_name,
        defaults={
            "device_type": device_type,
            "role": role,
            "location": location_obj,
            "status": active_status,
        },
    )

    interface, _ = Interface.objects.get_or_create(
        device=device,
        name="dummy0",
        defaults={"type": "virtual"},
    )
    return device, interface


class PortalTunnelRequestView(APIView):
    """Accept a portal tunnel provisioning request and enqueue the build job."""

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):  # pylint: disable=too-many-locals,too-many-statements
        """Validate, create full VPN object hierarchy, enqueue build job, return 202."""
        serializer = PortalTunnelRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        device = data["device"]
        member_name = data["member_name"]
        member_display = data["member_display_name"]
        city = data["location_city"]
        state = data["location_state"]
        remote_peer_ip = str(data["remote_peer_ip"])
        hub_prefix_cidr = data["hub_protected_prefix"]
        member_prefix_cidr = data["member_protected_prefix"]

        loc_slug = _location_slug(city, state)
        loc_display = f"{city}, {state}"

        # ------------------------------------------------------------------ #
        # Duplicate check (native fields)                                      #
        # ------------------------------------------------------------------ #
        existing_spoke_eps = VPNTunnelEndpoint.objects.filter(
            source_ip_address__host=remote_peer_ip,
            vpn_tunnel__vpn__name=f"vpn-nrtc-ms-{member_name}-{loc_slug}-001",
        )
        if existing_spoke_eps.exists():
            ep = existing_spoke_eps.first()
            return Response(
                {
                    "detail": "A tunnel with these parameters already exists.",
                    "tunnel_id": str(ep.vpn_tunnel.pk),
                },
                status=status.HTTP_409_CONFLICT,
            )

        # ------------------------------------------------------------------ #
        # Create full VPN hierarchy inside a transaction                       #
        # ------------------------------------------------------------------ #
        with transaction.atomic():
            # -- Step 1: Member Device + dummy0 + IP --
            from nautobot.dcim.models import Location  # pylint: disable=import-outside-toplevel

            location_obj, _ = Location.objects.get_or_create(
                name=loc_display,
                defaults={
                    "status": Status.objects.get_for_model(Location).get(name="Active"),
                },
            )

            member_device, dummy_iface = _get_or_create_member_device(
                member_name, loc_slug, location_obj
            )

            # Assign member's remote IP to dummy0
            ip_status = Status.objects.get_for_model(IPAddress).get(name="Active")
            members_ns, _ = Namespace.objects.get_or_create(
                name="Members",
                defaults={"description": "Namespace for member VPN prefixes."},
            )

            member_ip, _ = IPAddress.objects.get_or_create(
                host=remote_peer_ip,
                mask_length=32,
                parent__namespace=members_ns,
                defaults={
                    "status": ip_status,
                },
            )
            member_ip.assigned_object = dummy_iface
            member_ip.save()

            # -- Step 2: VPN container --
            vpn_name = f"vpn-nrtc-ms-{member_name}-{loc_slug}-001"
            vpn_display = f"{member_display} - {loc_display}"
            active_vpn = Status.objects.get_for_model(VPN).get(name="Active")
            vpn, _ = VPN.objects.get_or_create(
                name=vpn_name,
                defaults={
                    "status": active_vpn,
                    "description": vpn_display,
                },
            )

            # -- Step 3: Resolve template VPNProfile --
            # Beta: use hardcoded medium-security profile or the one the portal sends
            template_uuid = data.get("template_vpn_profile")
            if template_uuid:
                template_profile = VPNProfile.objects.get(pk=template_uuid)
            else:
                # Beta fallback: first available VPNProfile
                template_profile = VPNProfile.objects.first()
                if not template_profile:
                    return Response(
                        {"detail": "No VPNProfile templates exist. Create one in Nautobot first."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            # Calculate next sequence for this concentrator
            existing_seqs = VPNTunnel.objects.select_for_update().filter(
                vpntunnelendpoint__source_ip_address=device.primary_ip,
            ).aggregate(max_seq=Max("vpn_profile___custom_field_data__custom_tunnel_builder_crypto_map_sequence"))

            max_seq = existing_seqs.get("max_seq")
            if max_seq and max_seq >= PORTAL_SEQUENCE_START:
                next_seq = max_seq + PORTAL_SEQUENCE_STEP
            else:
                next_seq = PORTAL_SEQUENCE_START

            # Generate PSK and retrieval token
            psk = secrets.token_urlsafe(32)
            psk_token = secrets.token_urlsafe(48)

            # Clone template profile → per-tunnel profile
            profile_name = f"vpnprofile-nrtc-ms-{member_name}-{loc_slug}-{next_seq}"
            cloned_profile = VPNProfile.objects.create(name=profile_name)

            # Copy Phase1/Phase2 policy assignments from template
            for p1a in template_profile.vpnprofilephase1policyassignment_set.all():
                cloned_profile.vpnprofilephase1policyassignment_set.create(
                    vpn_phase1_policy=p1a.vpn_phase1_policy,
                    weight=p1a.weight,
                )
            for p2a in template_profile.vpnprofilephase2policyassignment_set.all():
                cloned_profile.vpnprofilephase2policyassignment_set.create(
                    vpn_phase2_policy=p2a.vpn_phase2_policy,
                    weight=p2a.weight,
                )

            # Set custom fields on the cloned profile
            cloned_profile._custom_field_data[  # pylint: disable=protected-access
                "custom_tunnel_builder_crypto_map_sequence"
            ] = next_seq
            cloned_profile._custom_field_data[  # pylint: disable=protected-access
                "custom_tunnel_builder_psk_retrieval_token"
            ] = psk_token
            cloned_profile._custom_field_data[  # pylint: disable=protected-access
                "custom_tunnel_builder_psk_retrieved"
            ] = False
            cloned_profile._custom_field_data[  # pylint: disable=protected-access
                "custom_tunnel_builder_psk_encrypted"
            ] = psk
            cloned_profile.save()

            # -- Step 4: VPNTunnel --
            tunnel_name = f"vpn-tunnel-nrtc-ms-{member_name}-{loc_slug}-{next_seq}"
            tunnel_display = f"{member_display} - {loc_display} - {next_seq}"
            planned_status = Status.objects.get_for_model(VPNTunnel).get(name="Planned")

            tunnel = VPNTunnel.objects.create(
                name=tunnel_name,
                status=planned_status,
                vpn=vpn,
                vpn_profile=cloned_profile,
            )

            # -- Step 5: Prefix objects in "Members" namespace --
            prefix_status = Status.objects.get_for_model(Prefix).get(name="Active")

            hub_prefix, _ = Prefix.objects.get_or_create(
                network=hub_prefix_cidr.split("/")[0],
                prefix_length=int(hub_prefix_cidr.split("/")[1]),
                namespace=members_ns,
                defaults={"status": prefix_status},
            )
            member_prefix, _ = Prefix.objects.get_or_create(
                network=member_prefix_cidr.split("/")[0],
                prefix_length=int(member_prefix_cidr.split("/")[1]),
                namespace=members_ns,
                defaults={"status": prefix_status},
            )

            # -- Step 6: Hub VPNTunnelEndpoint --
            hub_ep = VPNTunnelEndpoint.objects.create(
                vpn_tunnel=tunnel,
                role="hub",
                source_ip_address=device.primary_ip,
            )
            hub_ep.protected_prefixes.add(hub_prefix)

            # crypto_map_name: look up from existing hub endpoints on same device
            existing_hub_eps = VPNTunnelEndpoint.objects.filter(
                source_ip_address=device.primary_ip,
                role="hub",
            ).exclude(pk=hub_ep.pk)

            crypto_map_name = "VPN"
            for ep in existing_hub_eps:
                cf_name = ep._custom_field_data.get(  # pylint: disable=protected-access
                    "custom_tunnel_builder_crypto_map_name"
                )
                if cf_name:
                    crypto_map_name = cf_name
                    break

            hub_ep._custom_field_data[  # pylint: disable=protected-access
                "custom_tunnel_builder_crypto_map_name"
            ] = crypto_map_name
            hub_ep.save()

            # -- Step 7: Spoke/Member VPNTunnelEndpoint --
            spoke_ep = VPNTunnelEndpoint.objects.create(
                vpn_tunnel=tunnel,
                role="spoke",
                source_ip_address=member_ip,
            )
            spoke_ep.protected_prefixes.add(member_prefix)

        # ------------------------------------------------------------------ #
        # Enqueue the build job                                                #
        # ------------------------------------------------------------------ #
        try:
            job_model = JobModel.objects.get(
                module_name="nautobot_custom_tunnel_builder.jobs",
                job_class_name="PortalBuildIpsecTunnel",
            )
        except JobModel.DoesNotExist:
            logger.error("PortalBuildIpsecTunnel job is not registered.")
            return Response(
                {"detail": "Build job is not registered. Contact an administrator."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        job_result = JobResult.enqueue_job(
            job_model=job_model,
            user=request.user,
            tunnel_id=str(tunnel.pk),
            pre_shared_key=psk,
        )

        # Build response URLs
        status_url = reverse(
            "plugins-api:nautobot_custom_tunnel_builder-api:tunnel-status",
            kwargs={"tunnel_id": tunnel.pk},
            request=request,
        )
        psk_url = reverse(
            "plugins-api:nautobot_custom_tunnel_builder-api:psk-retrieval",
            kwargs={"token": psk_token},
            request=request,
        )

        return Response(
            {
                "tunnel_id": str(tunnel.pk),
                "tunnel_name": tunnel.name,
                "vpn_name": vpn.name,
                "member_device": member_device.name,
                "job_id": str(job_result.pk),
                "status_url": status_url,
                "psk_url": psk_url,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class TunnelStatusView(APIView):
    """Return the current status of a portal-created VPN tunnel."""

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, tunnel_id):
        """Return tunnel status, name, and conditional PSK URL."""
        try:
            tunnel = VPNTunnel.objects.get(pk=tunnel_id)
        except VPNTunnel.DoesNotExist:
            return Response(
                {"detail": "Tunnel not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        response_data = {
            "tunnel_id": str(tunnel.pk),
            "tunnel_name": tunnel.name,
            "status": tunnel.status.name,
        }

        # PSK fields are now on the VPNProfile, not VPNTunnel
        profile = tunnel.vpn_profile
        if profile:
            cf = profile._custom_field_data  # pylint: disable=protected-access
            psk_token = cf.get("custom_tunnel_builder_psk_retrieval_token")
            psk_retrieved = cf.get("custom_tunnel_builder_psk_retrieved", False)
            if tunnel.status.name == "Active" and psk_token and not psk_retrieved:
                response_data["psk_url"] = reverse(
                    "plugins-api:nautobot_custom_tunnel_builder-api:psk-retrieval",
                    kwargs={"token": psk_token},
                    request=request,
                )

        return Response(response_data)


class PSKRetrievalView(APIView):
    """One-time PSK retrieval by token. Returns 410 Gone if already retrieved."""

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        """Return the PSK and mark as retrieved (one-time use)."""
        # PSK fields are now on VPNProfile, not VPNTunnel
        try:
            profile = VPNProfile.objects.get(
                _custom_field_data__custom_tunnel_builder_psk_retrieval_token=token,
            )
        except VPNProfile.DoesNotExist:
            return Response(
                {"detail": "Invalid or expired PSK token."},
                status=status.HTTP_404_NOT_FOUND,
            )

        cf = profile._custom_field_data  # pylint: disable=protected-access

        if cf.get("custom_tunnel_builder_psk_retrieved", False):
            return Response(
                {"detail": "PSK has already been retrieved. This token is no longer valid."},
                status=status.HTTP_410_GONE,
            )

        psk = cf.get("custom_tunnel_builder_psk_encrypted", "")

        # Mark as retrieved and clear sensitive data
        profile._custom_field_data["custom_tunnel_builder_psk_retrieved"] = True  # pylint: disable=protected-access
        profile._custom_field_data["custom_tunnel_builder_psk_encrypted"] = ""  # pylint: disable=protected-access
        profile._custom_field_data[  # pylint: disable=protected-access
            "custom_tunnel_builder_psk_retrieval_token"
        ] = ""
        profile.save()

        # Find the tunnel for this profile
        tunnel = VPNTunnel.objects.filter(vpn_profile=profile).first()
        tunnel_name = tunnel.name if tunnel else "Unknown"
        tunnel_id = str(tunnel.pk) if tunnel else ""

        return Response(
            {
                "tunnel_id": tunnel_id,
                "tunnel_name": tunnel_name,
                "pre_shared_key": psk,
            }
        )
```

- [ ] **Step 2: Run tests**

Run: `poetry run pytest nautobot_custom_tunnel_builder/tests/test_api.py -v --tb=short`
Expected: All validation/auth tests pass (they don't require real DB objects for the hierarchy, just serializer validation and 401/404 checks).

- [ ] **Step 3: Commit**

```bash
git add nautobot_custom_tunnel_builder/api/views.py
git commit -m "feat: rewrite portal API for native VPN object hierarchy

Creates full object tree: member Device + dummy0 interface, VPN container,
cloned VPNProfile with PSK custom fields, VPNTunnel, Prefix objects in
Members namespace, hub + spoke VPNTunnelEndpoints with protected_prefixes.

Duplicate detection uses native source_ip_address on endpoints.
PSK fields moved from VPNTunnel to VPNProfile custom fields."
```

---

## Task 6: Update `PortalBuildIpsecTunnel` Job to Read from Native Objects

The portal job currently reads tunnel params from VPNTunnel `_custom_field_data`. After the refactor, it reads from native fields on the VPN hierarchy objects.

**Files:**
- Modify: `nautobot_custom_tunnel_builder/jobs.py` (PortalBuildIpsecTunnel class)

- [ ] **Step 1: Rewrite `PortalBuildIpsecTunnel.run()`**

Replace the `run()` method body (starting at line 617) in the `PortalBuildIpsecTunnel` class:

```python
def run(self, tunnel_id, pre_shared_key):  # pylint: disable=arguments-differ,too-many-locals
    """Execute the portal-requested IPsec tunnel build."""
    # 1. Load VPNTunnel and extract parameters from native objects
    try:
        tunnel = VPNTunnel.objects.get(pk=tunnel_id)
    except VPNTunnel.DoesNotExist:
        self.logger.error("VPNTunnel with id '%s' not found.", tunnel_id)
        raise

    # Get hub and spoke endpoints
    endpoints = tunnel.vpntunnelendpoint_set.all()
    hub_endpoint = endpoints.filter(role="hub").first()
    spoke_endpoint = endpoints.filter(role="spoke").first()

    if not hub_endpoint or not hub_endpoint.source_ip_address:
        self.logger.error("No hub endpoint with source IP found on tunnel '%s'.", tunnel.name)
        raise ValueError(f"Tunnel '{tunnel.name}' has no hub endpoint with a source IP address.")

    if not spoke_endpoint or not spoke_endpoint.source_ip_address:
        self.logger.error("No spoke endpoint with source IP found on tunnel '%s'.", tunnel.name)
        raise ValueError(f"Tunnel '{tunnel.name}' has no spoke endpoint with a source IP address.")

    # Resolve device from hub endpoint's IP
    device = hub_endpoint.source_ip_address.assigned_object.parent
    self.logger.info("Device resolved: %s", device.name)

    # Read native fields
    remote_peer_ip = str(spoke_endpoint.source_ip_address.host)

    hub_prefixes = hub_endpoint.protected_prefixes.all()
    spoke_prefixes = spoke_endpoint.protected_prefixes.all()
    local_network_cidr = str(hub_prefixes.first()) if hub_prefixes.exists() else None
    protected_network_cidr = str(spoke_prefixes.first()) if spoke_prefixes.exists() else None

    if not local_network_cidr or not protected_network_cidr:
        raise ValueError(f"Tunnel '{tunnel.name}' is missing protected prefixes on endpoints.")

    # Read custom fields from VPNProfile and hub endpoint
    vpn_profile = tunnel.vpn_profile
    if not vpn_profile:
        self.logger.error("Tunnel '%s' has no VPN profile assigned.", tunnel.name)
        raise ValueError(f"Tunnel '{tunnel.name}' has no VPN profile assigned.")

    profile_cf = vpn_profile._custom_field_data  # pylint: disable=protected-access
    sequence = profile_cf.get("custom_tunnel_builder_crypto_map_sequence")

    hub_cf = hub_endpoint._custom_field_data  # pylint: disable=protected-access
    crypto_map_name = hub_cf.get("custom_tunnel_builder_crypto_map_name", "VPN")

    self.logger.info(
        "Tunnel '%s': seq=%s, peer=%s, local=%s, protected=%s, map=%s",
        tunnel.name,
        sequence,
        remote_peer_ip,
        local_network_cidr,
        protected_network_cidr,
        crypto_map_name,
    )

    # 2. Map VPN profile to config params
    params = profile_to_config_params(
        vpn_profile=vpn_profile,
        remote_peer_ip=remote_peer_ip,
        local_network_cidr=local_network_cidr,
        protected_network_cidr=protected_network_cidr,
        crypto_map_name=crypto_map_name,
        sequence=sequence,
    )
    params["pre_shared_key"] = pre_shared_key

    # 3. Build IOS-XE configuration commands
    commands = build_iosxe_policy_config(params)

    self.logger.info(
        "Generated %d configuration lines for tunnel '%s'.",
        len(commands),
        tunnel.name,
    )

    # Log config with redacted PSK
    redacted = [
        line.replace(pre_shared_key, "***REDACTED***") if pre_shared_key in line else line for line in commands
    ]
    self.logger.debug("Configuration preview:\n%s", "\n".join(redacted))

    # 4. Build device connection parameters and push config
    mgmt_ip = self._get_management_ip(device)
    device_type = self._get_netmiko_platform(device)

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
            "Failed to configure %s for tunnel '%s': %s\n%s",
            device.name,
            tunnel.name,
            exc,
            traceback.format_exc(),
        )
        decommissioning = Status.objects.get_for_model(VPNTunnel).get(name="Decommissioning")
        tunnel.status = decommissioning
        tunnel.save()
        raise

    # 5. Update tunnel status to Active on success
    active_status = Status.objects.get_for_model(VPNTunnel).get(name="Active")
    tunnel.status = active_status
    tunnel.save()

    self.logger.info(
        "Portal IPsec tunnel '%s' successfully configured on %s.",
        tunnel.name,
        device.name,
    )

    return f"Portal tunnel '{tunnel.name}' configured on {device.name} ({mgmt_ip})."
```

- [ ] **Step 2: Run tests**

Run: `poetry run pytest nautobot_custom_tunnel_builder/tests/ -v --tb=short`
Expected: All pass. The job changes are internal to the run method and don't affect the unit tests (which mock SSH).

- [ ] **Step 3: Commit**

```bash
git add nautobot_custom_tunnel_builder/jobs.py
git commit -m "refactor: portal job reads tunnel params from native VPN objects

Hub endpoint source_ip_address -> device resolution.
Spoke endpoint source_ip_address -> remote_peer_ip.
Protected prefixes from endpoint M2M -> local/remote networks.
Crypto map sequence from VPNProfile custom field.
Crypto map name from hub endpoint custom field."
```

---

## Task 7: Run Full Test Suite and Lint

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `poetry run pytest nautobot_custom_tunnel_builder/tests/ -v --tb=long`
Expected: All tests pass.

- [ ] **Step 2: Run ruff format**

Run: `poetry run ruff format nautobot_custom_tunnel_builder/`

- [ ] **Step 3: Run ruff lint**

Run: `poetry run ruff check nautobot_custom_tunnel_builder/ --fix`

- [ ] **Step 4: Fix any issues and commit**

```bash
git add -u
git commit -m "style: ruff format + lint fixes"
```

---

## Summary

| Task | What | Files touched |
|------|------|---------------|
| 1 | Remove `wan_interface` everywhere | jobs.py, forms.py, views.py, test_config_generation.py |
| 2 | Add `psk_encrypted` migration | migrations/0002_add_psk_encrypted.py |
| 3 | Add sequence constants | constants.py |
| 4 | Update serializer for new API fields | api/serializers.py, test_api.py |
| 5 | Rewrite api/views.py for VPN hierarchy | api/views.py |
| 6 | Update portal job to read native objects | jobs.py |
| 7 | Verify: full tests + lint | (none) |

Tasks 1-3 are independent and can run in parallel. Task 4 is independent. Tasks 5-6 depend on Tasks 1-4. Task 7 is final verification.
