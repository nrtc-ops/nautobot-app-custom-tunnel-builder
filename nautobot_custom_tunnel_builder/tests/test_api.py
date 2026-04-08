"""Tests for the portal REST API endpoints."""

import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from nautobot.core.testing import APITestCase
from nautobot.dcim.models import (
    Device,
    DeviceType,
    Interface,
    Location,
    LocationType,
    Manufacturer,
    Platform,
)
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix
from nautobot.vpn.models import (
    VPN,
    VPNPhase1Policy,
    VPNPhase2Policy,
    VPNProfile,
    VPNProfilePhase1PolicyAssignment,
    VPNProfilePhase2PolicyAssignment,
    VPNTunnel,
    VPNTunnelEndpoint,
)
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()

# ---------------------------------------------------------------------------
# Base URL for the portal API (under the plugin's base_url)
# ---------------------------------------------------------------------------

PORTAL_REQUEST_URL = "/plugins/tunnel-builder/api/portal-request/"
TUNNEL_STATUS_URL_TEMPLATE = "/plugins/tunnel-builder/api/tunnel-status/{}/"

# Required fields for the new API schema
REQUIRED_FIELDS = (
    "member_name",
    "member_display_name",
    "location_city",
    "location_state",
    "device",
    "template_vpn_profile",
    "remote_peer_ip",
    "member_protected_prefixes",
)

# Mock path for 1Password SDK
OP_MOCK_PATH = "nautobot_custom_tunnel_builder.api.views.store_psk_in_1password"


def _create_test_device(name="csr-vpn-router"):  # pylint: disable=too-many-locals
    """Create a Device with platform, IP, and all required FKs for testing."""
    manufacturer, _ = Manufacturer.objects.get_or_create(name="Cisco")
    device_type, _ = DeviceType.objects.get_or_create(model="CSR1000v", manufacturer=manufacturer)
    platform, _ = Platform.objects.get_or_create(
        name="Cisco IOS-XE",
        defaults={"network_driver": "cisco_xe"},
    )
    role, _ = Role.objects.get_or_create(name="Router")
    location_type, _ = LocationType.objects.get_or_create(name="Site")
    active_status = Status.objects.get_for_model(Location).get(name="Active")
    location, _ = Location.objects.get_or_create(
        name="HQ",
        location_type=location_type,
        defaults={"status": active_status},
    )
    device_status = Status.objects.get_for_model(Device).get(name="Active")
    device, _ = Device.objects.get_or_create(
        name=name,
        defaults={
            "device_type": device_type,
            "platform": platform,
            "role": role,
            "location": location,
            "status": device_status,
        },
    )

    # Create WAN interface + primary IP
    intf_status = Status.objects.get_for_model(Interface).get(name="Active")
    interface, _ = Interface.objects.get_or_create(
        device=device,
        name="GigabitEthernet1",
        defaults={"type": "1000base-t", "status": intf_status},
    )
    global_ns, _ = Namespace.objects.get_or_create(name="Global")
    prefix_status = Status.objects.get_for_model(Prefix).get(name="Active")
    Prefix.objects.get_or_create(
        prefix="10.1.1.0/24",
        namespace=global_ns,
        defaults={"status": prefix_status},
    )
    ip_status = Status.objects.get_for_model(IPAddress).get(name="Active")
    ip, _ = IPAddress.objects.get_or_create(
        address="10.1.1.1/32",
        namespace=global_ns,
        defaults={"status": ip_status},
    )
    from nautobot.ipam.models import IPAddressToInterface  # pylint: disable=import-outside-toplevel

    IPAddressToInterface.objects.get_or_create(ip_address=ip, interface=interface)
    device.primary_ip4 = ip
    device.save()

    return device


def _create_template_vpn_profile():
    """Create a template VPNProfile with Phase1 and Phase2 policies."""
    phase1 = VPNPhase1Policy.objects.create(
        name="Test-Phase1",
        ike_version="IKEv2",
        encryption_algorithm=["AES-256-CBC"],
        integrity_algorithm=["SHA256"],
        dh_group=["19"],
        lifetime_seconds=86400,
    )
    phase2 = VPNPhase2Policy.objects.create(
        name="Test-Phase2",
        encryption_algorithm=["AES-256-CBC"],
        integrity_algorithm=["SHA256"],
        lifetime=3600,
    )
    profile = VPNProfile.objects.create(
        name="Template-Standard-IKEv2",
        description="Test template profile.",
    )
    VPNProfilePhase1PolicyAssignment.objects.create(
        vpn_profile=profile,
        vpn_phase1_policy=phase1,
        weight=100,
    )
    VPNProfilePhase2PolicyAssignment.objects.create(
        vpn_profile=profile,
        vpn_phase2_policy=phase2,
        weight=100,
    )
    return profile


def _create_hub_endpoint(device, hub_prefix_cidr="10.100.0.0/24"):
    """Pre-configure a hub VPNTunnelEndpoint with a protected prefix for the given device."""
    hub_role, _ = Role.objects.get_or_create(name="Hub")
    hub_endpoint, created = VPNTunnelEndpoint.objects.get_or_create(
        device=device,
        role=hub_role,
        defaults={"source_ipaddress": device.primary_ip},
    )
    if created:
        hub_endpoint._custom_field_data["custom_tunnel_builder_crypto_map_name"] = "VPN"  # pylint: disable=protected-access
        hub_endpoint.save()
    global_ns, _ = Namespace.objects.get_or_create(name="Global")
    prefix_status = Status.objects.get_for_model(Prefix).get(name="Active")
    hub_prefix, _ = Prefix.objects.get_or_create(
        prefix=hub_prefix_cidr,
        namespace=global_ns,
        defaults={"status": prefix_status},
    )
    hub_endpoint.protected_prefixes.add(hub_prefix)
    return hub_endpoint


def _valid_payload(device, template_profile):
    """Return a valid portal request payload."""
    return {
        "member_name": "acme-corp",
        "member_display_name": "Acme Corp",
        "location_city": "Jackson",
        "location_state": "MS",
        "device": str(device.pk),
        "template_vpn_profile": str(template_profile.pk),
        "remote_peer_ip": "203.0.113.50",
        "member_protected_prefixes": ["192.168.1.0/24"],
    }


# ---------------------------------------------------------------------------
# Unauthenticated access tests (use plain APIClient, no token)
# ---------------------------------------------------------------------------


class UnauthenticatedAccessTest(TestCase):
    """Verify that unauthenticated requests are rejected."""

    def setUp(self):
        self.client = APIClient()

    def test_portal_request_unauthenticated(self):
        """POST portal-request without credentials returns 401 or 403."""
        response = self.client.post(PORTAL_REQUEST_URL, data={}, format="json")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_tunnel_status_unauthenticated(self):
        """GET tunnel-status without credentials returns 401 or 403."""
        fake_uuid = uuid.uuid4()
        response = self.client.get(TUNNEL_STATUS_URL_TEMPLATE.format(fake_uuid))
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


# ---------------------------------------------------------------------------
# Portal request validation tests (authenticated)
# ---------------------------------------------------------------------------


class PortalRequestValidationTest(APITestCase):  # pylint: disable=too-many-ancestors
    """Test validation on the portal-request endpoint."""

    def _post(self, url, data=None):
        """POST with auth header."""
        return self.client.post(url, data=data or {}, format="json", **self.header)

    def test_empty_body_returns_400(self):
        """POST with empty body returns 400 with field errors."""
        response = self._post(PORTAL_REQUEST_URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        for field in REQUIRED_FIELDS:
            self.assertIn(field, data, f"Expected error for missing field: {field}")

    def test_invalid_member_name_slug_returns_400(self):
        """POST with uppercase/spaces in member_name returns 400."""
        payload = {
            "member_name": "Acme Corp",
            "member_display_name": "Acme Corp",
            "location_city": "Jackson",
            "location_state": "MS",
            "device": str(uuid.uuid4()),
            "template_vpn_profile": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "member_protected_prefixes": ["192.168.1.0/24"],
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("member_name", response.json())

    def test_invalid_location_state_returns_400(self):
        """POST with invalid state abbreviation returns 400."""
        payload = {
            "member_name": "acme-corp",
            "member_display_name": "Acme Corp",
            "location_city": "Jackson",
            "location_state": "Mississippi",
            "device": str(uuid.uuid4()),
            "template_vpn_profile": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "member_protected_prefixes": ["192.168.1.0/24"],
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("location_state", response.json())

    def test_hub_protected_prefix_field_ignored(self):
        """hub_protected_prefix is no longer accepted — it is read from the hub endpoint."""
        payload = {
            "member_name": "acme-corp",
            "member_display_name": "Acme Corp",
            "location_city": "Jackson",
            "location_state": "MS",
            "device": str(uuid.uuid4()),
            "template_vpn_profile": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "hub_protected_prefix": "10.100.0.0/24",
            "member_protected_prefixes": ["192.168.1.0/24"],
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        # Field is unknown to the serializer; request fails on device/profile UUID validation,
        # not on hub_protected_prefix — confirming the field is no longer required or validated.
        self.assertNotIn("hub_protected_prefix", response.json())

    def test_invalid_member_prefix_returns_400(self):
        """POST with invalid member_protected_prefixes entry returns 400."""
        payload = {
            "member_name": "acme-corp",
            "member_display_name": "Acme Corp",
            "location_city": "Jackson",
            "location_state": "MS",
            "device": str(uuid.uuid4()),
            "template_vpn_profile": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "member_protected_prefixes": ["garbage"],
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("member_protected_prefixes", response.json())

    def test_invalid_remote_peer_ip_returns_400(self):
        """POST with an invalid IP address returns 400."""
        payload = {
            "member_name": "acme-corp",
            "member_display_name": "Acme Corp",
            "location_city": "Jackson",
            "location_state": "MS",
            "device": str(uuid.uuid4()),
            "template_vpn_profile": str(uuid.uuid4()),
            "remote_peer_ip": "not-an-ip",
            "member_protected_prefixes": ["192.168.1.0/24"],
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("remote_peer_ip", response.json())


# ---------------------------------------------------------------------------
# Happy path integration tests (1Password mocked)
# ---------------------------------------------------------------------------


class PortalTunnelCreationTest(APITestCase):  # pylint: disable=too-many-ancestors
    """Test the full tunnel creation flow with mocked 1Password."""

    @classmethod
    def setUpTestData(cls):
        cls.device = _create_test_device()
        cls.template_profile = _create_template_vpn_profile()
        # Ensure "Member VPN Endpoint" DeviceType exists (normally created by migration)
        manufacturer, _ = Manufacturer.objects.get_or_create(name="Generic")
        DeviceType.objects.get_or_create(model="Member VPN Endpoint", manufacturer=manufacturer)
        # Ensure "Site" LocationType exists
        LocationType.objects.get_or_create(name="Site")
        # Pre-configure hub endpoint with protected prefix (required before portal can provision)
        _create_hub_endpoint(cls.device)

    def _post(self, url, data=None):
        return self.client.post(url, data=data or {}, format="json", **self.header)

    def _get(self, url):
        return self.client.get(url, **self.header)

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_happy_path_creates_full_hierarchy(self, _mock_op):
        """POST with valid data creates VPN, VPNTunnel, endpoints, profile, member device."""
        payload = _valid_payload(self.device, self.template_profile)
        response = self._post(PORTAL_REQUEST_URL, payload)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertIn("tunnel_id", data)
        self.assertIn("vpn_id", data)
        self.assertEqual(data["vpn_id"], "vpn-nrtc-ms-acme-corp-jackson-ms-001")

        # Verify VPN created
        vpn = VPN.objects.get(vpn_id="vpn-nrtc-ms-acme-corp-jackson-ms-001")
        self.assertEqual(vpn.name, "Acme Corp - Jackson, MS")

        # Verify VPNTunnel created
        tunnel = VPNTunnel.objects.get(pk=data["tunnel_id"])
        self.assertEqual(tunnel.vpn, vpn)
        self.assertIn("Acme Corp - Jackson, MS - 3000", tunnel.name)

        # Verify VPNProfile cloned (not the template)
        profile = tunnel.vpn_profile
        self.assertNotEqual(profile.pk, self.template_profile.pk)
        self.assertIn("vpnprofile-nrtc-ms-acme-corp-jackson-ms-3000", profile.name)
        # Verify Phase1/Phase2 policies were copied
        self.assertEqual(profile.vpn_profile_phase1_policy_assignments.count(), 1)
        self.assertEqual(profile.vpn_profile_phase2_policy_assignments.count(), 1)
        # Verify custom fields on profile
        self.assertEqual(
            profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"],  # pylint: disable=protected-access
            3000,
        )

        # Verify hub endpoint (endpoint_z = concentrator/NRTC side)
        hub = tunnel.endpoint_z
        self.assertEqual(hub.source_ipaddress, self.device.primary_ip)
        self.assertGreaterEqual(hub.protected_prefixes.count(), 1)
        self.assertIn("10.100.0.0/24", [str(p.prefix) for p in hub.protected_prefixes.all()])
        self.assertEqual(
            hub._custom_field_data["custom_tunnel_builder_crypto_map_name"],  # pylint: disable=protected-access
            "VPN",
        )

        # Verify spoke endpoint (endpoint_a = member/spoke side)
        spoke = tunnel.endpoint_a
        self.assertIsNotNone(spoke.source_ipaddress)
        self.assertEqual(str(spoke.source_ipaddress.address.ip), "203.0.113.50")
        self.assertEqual(spoke.protected_prefixes.count(), 1)
        self.assertEqual(str(spoke.protected_prefixes.first().prefix), "192.168.1.0/24")

        # Verify member device created with a per-peer interface
        member_device = Device.objects.get(name="member-acme-corp-jackson-ms")
        self.assertEqual(member_device.device_type.model, "Member VPN Endpoint")
        peer_intf = Interface.objects.get(device=member_device, name="peer-203-0-113-50")
        self.assertIsNotNone(peer_intf)

        # Verify 1Password was called
        _mock_op.assert_called_once()

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_vpn_reuse_same_member_location(self, _mock_op):
        """Second tunnel for same member+location reuses the VPN object."""
        payload = _valid_payload(self.device, self.template_profile)
        resp1 = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(resp1.status_code, status.HTTP_202_ACCEPTED)

        # Second request with different remote IP (not a duplicate)
        payload2 = _valid_payload(self.device, self.template_profile)
        payload2["remote_peer_ip"] = "203.0.113.51"
        resp2 = self._post(PORTAL_REQUEST_URL, payload2)
        self.assertEqual(resp2.status_code, status.HTTP_202_ACCEPTED)

        # Same VPN, different tunnels
        self.assertEqual(resp1.json()["vpn_id"], resp2.json()["vpn_id"])
        self.assertNotEqual(resp1.json()["tunnel_id"], resp2.json()["tunnel_id"])
        self.assertEqual(VPN.objects.filter(vpn_id="vpn-nrtc-ms-acme-corp-jackson-ms-001").count(), 1)

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_duplicate_detection_returns_409(self, _mock_op):
        """Second request with identical parameters returns 409 Conflict."""
        payload = _valid_payload(self.device, self.template_profile)
        resp1 = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(resp1.status_code, status.HTTP_202_ACCEPTED)

        # Exact same request
        resp2 = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("tunnel_id", resp2.json())

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_crypto_map_sequence_starts_at_3000(self, _mock_op):
        """First tunnel gets sequence 3000."""
        payload = _valid_payload(self.device, self.template_profile)
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        tunnel = VPNTunnel.objects.get(pk=response.json()["tunnel_id"])
        profile = tunnel.vpn_profile
        seq = profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"]  # pylint: disable=protected-access
        self.assertEqual(seq, 3000)

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_crypto_map_sequence_increments(self, _mock_op):
        """Second tunnel on same device gets sequence 3010."""
        payload = _valid_payload(self.device, self.template_profile)
        self._post(PORTAL_REQUEST_URL, payload)

        payload2 = _valid_payload(self.device, self.template_profile)
        payload2["remote_peer_ip"] = "203.0.113.51"
        resp2 = self._post(PORTAL_REQUEST_URL, payload2)

        tunnel2 = VPNTunnel.objects.get(pk=resp2.json()["tunnel_id"])
        seq = tunnel2.vpn_profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"]  # pylint: disable=protected-access
        self.assertEqual(seq, 3010)

    @patch(OP_MOCK_PATH, side_effect=RuntimeError("1Password credentials not configured"))
    def test_1password_failure_rolls_back(self, _mock_op):
        """If 1Password fails, the transaction rolls back and no VPN objects are created."""
        payload = _valid_payload(self.device, self.template_profile)
        response = self._post(PORTAL_REQUEST_URL, payload)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        # No VPN objects should exist
        self.assertEqual(VPN.objects.filter(vpn_id="vpn-nrtc-ms-acme-corp-jackson-ms-001").count(), 0)

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_location_created_if_not_exists(self, _mock_op):
        """A new Location is created from city/state if it doesn't exist."""
        payload = _valid_payload(self.device, self.template_profile)
        payload["location_city"] = "Tupelo"
        payload["location_state"] = "MS"
        response = self._post(PORTAL_REQUEST_URL, payload)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(Location.objects.filter(name="Tupelo, MS").exists())

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_multiple_member_prefixes_added_to_spoke_endpoint(self, _mock_op):
        """Multiple CIDRs in member_protected_prefixes are all added to the spoke endpoint."""
        payload = _valid_payload(self.device, self.template_profile)
        payload["member_name"] = "multi-prefix-member"
        payload["member_display_name"] = "Multi Prefix Member"
        payload["remote_peer_ip"] = "203.0.113.99"
        payload["member_protected_prefixes"] = ["192.168.10.0/24", "10.50.0.0/16"]
        response = self._post(PORTAL_REQUEST_URL, payload)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        tunnel = VPNTunnel.objects.get(pk=response.json()["tunnel_id"])
        spoke = tunnel.endpoint_a
        self.assertEqual(spoke.protected_prefixes.count(), 2)
        prefix_strs = {str(p.prefix) for p in spoke.protected_prefixes.all()}
        self.assertIn("192.168.10.0/24", prefix_strs)
        self.assertIn("10.50.0.0/16", prefix_strs)


# ---------------------------------------------------------------------------
# Tunnel status endpoint tests (authenticated)
# ---------------------------------------------------------------------------


class TunnelStatusTest(APITestCase):  # pylint: disable=too-many-ancestors
    """Test the tunnel-status endpoint."""

    def _get(self, url):
        return self.client.get(url, **self.header)

    def test_non_existent_tunnel_returns_404(self):
        """GET with a UUID that doesn't match any VPNTunnel returns 404."""
        fake_uuid = uuid.uuid4()
        response = self._get(TUNNEL_STATUS_URL_TEMPLATE.format(fake_uuid))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        data = response.json()
        self.assertTrue("error" in data or "detail" in data)

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-psk-test")
    @patch("nautobot.extras.models.Secret.get_value", return_value="TestPSKReturnedOnce!")
    def test_active_tunnel_returns_psk(self, _mock_get_value, _mock_op):
        """Status endpoint returns pre_shared_key when tunnel is Active."""
        device = _create_test_device(name="psk-test-router")
        template = _create_template_vpn_profile()
        manufacturer, _ = Manufacturer.objects.get_or_create(name="Generic")
        DeviceType.objects.get_or_create(model="Member VPN Endpoint", manufacturer=manufacturer)
        LocationType.objects.get_or_create(name="Site")
        _create_hub_endpoint(device)

        payload = _valid_payload(device, template)
        payload["member_name"] = "psk-test-member"
        payload["remote_peer_ip"] = "203.0.113.77"
        post_response = self.client.post(PORTAL_REQUEST_URL, data=payload, format="json", **self.header)
        self.assertEqual(post_response.status_code, status.HTTP_202_ACCEPTED)

        tunnel_id = post_response.json()["tunnel_id"]
        response = self._get(TUNNEL_STATUS_URL_TEMPLATE.format(tunnel_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "Active")
        self.assertIn("pre_shared_key", data)
        self.assertEqual(data["pre_shared_key"], "TestPSKReturnedOnce!")


# ---------------------------------------------------------------------------
# End-to-end: API request → object creation → config generation
# ---------------------------------------------------------------------------


class EndToEndConfigGenerationTest(APITestCase):  # pylint: disable=too-many-ancestors
    """Test the full flow from API request through VPN object creation to IOS-XE config generation.

    Mocks: 1Password SDK, SSH push (Netmiko).
    Real: All Nautobot objects, profile cloning, config generation.
    """

    @classmethod
    def setUpTestData(cls):
        cls.device = _create_test_device()
        cls.template_profile = _create_template_vpn_profile()
        manufacturer, _ = Manufacturer.objects.get_or_create(name="Generic")
        DeviceType.objects.get_or_create(model="Member VPN Endpoint", manufacturer=manufacturer)
        LocationType.objects.get_or_create(name="Site")
        # Pre-configure hub endpoint with protected prefix (required before portal can provision)
        _create_hub_endpoint(cls.device)

    def _post(self, url, data=None):
        return self.client.post(url, data=data or {}, format="json", **self.header)

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_api_to_config_generation_ikev2(self, _mock_op):  # pylint: disable=too-many-locals,too-many-statements
        """Full flow: POST creates objects, job reads them, config generation produces valid IOS-XE."""
        payload = _valid_payload(self.device, self.template_profile)
        payload["member_name"] = "e2e-test-alpha"
        payload["member_display_name"] = "E2E Test Alpha"
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        tunnel_id = response.json()["tunnel_id"]
        tunnel = VPNTunnel.objects.get(pk=tunnel_id)

        # -- Extract parameters exactly as the job does --
        hub_endpoint = tunnel.endpoint_z
        spoke_endpoint = tunnel.endpoint_a
        self.assertIsNotNone(hub_endpoint)
        self.assertIsNotNone(spoke_endpoint)
        self.assertIsNotNone(hub_endpoint.source_ipaddress)
        self.assertIsNotNone(spoke_endpoint.source_ipaddress)

        remote_peer_ip = str(spoke_endpoint.source_ipaddress.address.ip)
        self.assertEqual(remote_peer_ip, "203.0.113.50")

        hub_prefix = hub_endpoint.protected_prefixes.first()
        spoke_prefix = spoke_endpoint.protected_prefixes.first()
        self.assertIsNotNone(hub_prefix)
        self.assertIsNotNone(spoke_prefix)

        local_network_cidr = str(hub_prefix.prefix)
        protected_network_cidr = str(spoke_prefix.prefix)
        self.assertEqual(local_network_cidr, "10.100.0.0/24")
        self.assertEqual(protected_network_cidr, "192.168.1.0/24")

        vpn_profile = tunnel.vpn_profile
        self.assertIsNotNone(vpn_profile)

        profile_cf = vpn_profile._custom_field_data  # pylint: disable=protected-access
        sequence = profile_cf.get("custom_tunnel_builder_crypto_map_sequence")
        self.assertEqual(sequence, 3000)

        crypto_map_name = (
            hub_endpoint._custom_field_data.get(  # pylint: disable=protected-access
                "custom_tunnel_builder_crypto_map_name", "VPN"
            )
            or "VPN"
        )
        self.assertEqual(crypto_map_name, "VPN")

        # -- Run config generation (same calls as the job) --
        from nautobot_custom_tunnel_builder.jobs import (  # pylint: disable=import-outside-toplevel
            build_iosxe_policy_config,
        )
        from nautobot_custom_tunnel_builder.mapping import (  # pylint: disable=import-outside-toplevel
            profile_to_config_params,
        )

        params = profile_to_config_params(  # pylint: disable=duplicate-code
            vpn_profile=vpn_profile,
            remote_peer_ip=remote_peer_ip,
            local_network_cidr=local_network_cidr,
            protected_network_cidr=protected_network_cidr,
            crypto_map_name=crypto_map_name,
            sequence=sequence,
        )
        params["pre_shared_key"] = "TestPSK123!"
        commands = build_iosxe_policy_config(params)

        # -- Verify IOS-XE config correctness --
        self.assertGreater(len(commands), 10, "Expected at least 10 config lines")

        # IKEv2 proposal (template uses IKEv2 + AES-256-CBC + SHA256 + DH19)
        # mapping.py generates names with PORTAL- prefix + sequence
        self.assertIn("crypto ikev2 proposal PORTAL-PROP-3000", commands)
        self.assertIn(" encryption aes-cbc-256", commands)
        self.assertIn(" integrity sha256", commands)
        self.assertIn(" group 19", commands)

        # No per-tunnel IKEv2 policy — hub uses a shared policy
        self.assertNotIn("crypto ikev2 policy PORTAL-POL-3000", commands)

        # IKEv2 keyring with single combined PSK declaration
        self.assertIn("crypto ikev2 keyring PORTAL-KR-3000", commands)
        self.assertIn("  pre-shared-key TestPSK123!", commands)

        # IKEv2 profile
        self.assertIn("crypto ikev2 profile PORTAL-PROF-3000", commands)

        # Crypto ACL with correct networks
        self.assertIn("ip access-list extended PORTAL-ACL-3000", commands)
        self.assertIn(" permit ip 10.100.0.0 0.0.0.255 192.168.1.0 0.0.0.255", commands)

        # Transform set (AES-256 + SHA256)
        self.assertIn("crypto ipsec transform-set PORTAL-TS-3000 esp-aes 256 esp-sha256-hmac", commands)
        self.assertIn(" mode tunnel", commands)

        # Crypto map entry with correct map name and sequence
        self.assertIn("crypto map VPN 3000 ipsec-isakmp", commands)
        self.assertIn(" set peer 203.0.113.50", commands)
        self.assertIn(" set transform-set PORTAL-TS-3000", commands)
        self.assertIn(" set security-association lifetime seconds 3600", commands)
        self.assertIn(" set ikev2-profile PORTAL-PROF-3000", commands)
        self.assertIn(" match address PORTAL-ACL-3000", commands)

        # No interface/crypto-map-apply lines
        interface_lines = [c for c in commands if c.strip().startswith("interface ")]
        self.assertEqual(interface_lines, [], "Config should not contain interface apply lines")

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_second_tunnel_increments_sequence_in_config(self, _mock_op):
        """Second tunnel on same device uses sequence 3010 in all config objects."""
        payload = _valid_payload(self.device, self.template_profile)
        payload["member_name"] = "e2e-seq-first"
        payload["member_display_name"] = "E2E Seq First"
        self._post(PORTAL_REQUEST_URL, payload)

        # Second tunnel with different remote IP
        payload2 = _valid_payload(self.device, self.template_profile)
        payload2["remote_peer_ip"] = "203.0.113.51"
        payload2["member_name"] = "e2e-seq-second"
        payload2["member_display_name"] = "E2E Seq Second"
        resp2 = self._post(PORTAL_REQUEST_URL, payload2)
        self.assertEqual(resp2.status_code, status.HTTP_202_ACCEPTED)

        tunnel2 = VPNTunnel.objects.get(pk=resp2.json()["tunnel_id"])
        profile2 = tunnel2.vpn_profile
        seq2 = profile2._custom_field_data["custom_tunnel_builder_crypto_map_sequence"]  # pylint: disable=protected-access
        self.assertEqual(seq2, 3010)

        from nautobot_custom_tunnel_builder.jobs import (  # pylint: disable=import-outside-toplevel
            build_iosxe_policy_config,
        )
        from nautobot_custom_tunnel_builder.mapping import (  # pylint: disable=import-outside-toplevel
            profile_to_config_params,
        )

        hub2 = tunnel2.endpoint_z
        params = profile_to_config_params(
            vpn_profile=profile2,
            remote_peer_ip="203.0.113.51",
            local_network_cidr=str(hub2.protected_prefixes.first().prefix),
            protected_network_cidr=str(tunnel2.endpoint_a.protected_prefixes.first().prefix),
            crypto_map_name=hub2._custom_field_data.get(  # pylint: disable=protected-access
                "custom_tunnel_builder_crypto_map_name", "VPN"
            ),
            sequence=seq2,
        )
        params["pre_shared_key"] = "TestPSK456!"
        commands = build_iosxe_policy_config(params)

        # All naming uses sequence 3010
        self.assertIn("crypto ikev2 proposal PORTAL-PROP-3010", commands)
        self.assertIn("crypto map VPN 3010 ipsec-isakmp", commands)
        self.assertIn(" set peer 203.0.113.51", commands)

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_device_resolution_from_hub_endpoint(self, _mock_op):
        """The job can resolve the concentrator Device from the hub endpoint's IP."""
        payload = _valid_payload(self.device, self.template_profile)
        payload["member_name"] = "e2e-dev-resolve"
        payload["member_display_name"] = "E2E Dev Resolve"
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        tunnel = VPNTunnel.objects.get(pk=response.json()["tunnel_id"])
        hub = tunnel.endpoint_z

        # Traverse the same path the job uses: source_ipaddress → interface → device
        ip_addr = hub.source_ipaddress
        self.assertIsNotNone(ip_addr)

        # In Nautobot 3.x, get the device through IPAddressToInterface
        from nautobot.ipam.models import IPAddressToInterface  # pylint: disable=import-outside-toplevel

        assignment = IPAddressToInterface.objects.filter(ip_address=ip_addr).first()
        self.assertIsNotNone(assignment, "Hub IP must be assigned to an interface")
        resolved_device = assignment.interface.device
        self.assertEqual(resolved_device.pk, self.device.pk)
        self.assertEqual(resolved_device.name, "csr-vpn-router")
