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
)
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()

# ---------------------------------------------------------------------------
# Base URL for the portal API (under the plugin's base_url)
# ---------------------------------------------------------------------------

PORTAL_REQUEST_URL = "/plugins/tunnel-builder/api/portal-request/"
TUNNEL_STATUS_URL_TEMPLATE = "/plugins/tunnel-builder/api/tunnel-status/{}/"
PSK_URL_TEMPLATE = "/plugins/tunnel-builder/api/psk/{}/"

# Required fields for the new API schema
REQUIRED_FIELDS = (
    "member_name",
    "member_display_name",
    "location_city",
    "location_state",
    "device",
    "template_vpn_profile",
    "remote_peer_ip",
    "hub_protected_prefix",
    "member_protected_prefix",
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
        "hub_protected_prefix": "10.100.0.0/24",
        "member_protected_prefix": "192.168.1.0/24",
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

    def test_psk_retrieval_unauthenticated(self):
        """GET psk retrieval without credentials returns 401 or 403."""
        response = self.client.get(PSK_URL_TEMPLATE.format("fake-token-value"))
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
            "hub_protected_prefix": "10.100.0.0/24",
            "member_protected_prefix": "192.168.1.0/24",
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
            "hub_protected_prefix": "10.100.0.0/24",
            "member_protected_prefix": "192.168.1.0/24",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("location_state", response.json())

    def test_invalid_hub_prefix_returns_400(self):
        """POST with invalid hub_protected_prefix returns 400."""
        payload = {
            "member_name": "acme-corp",
            "member_display_name": "Acme Corp",
            "location_city": "Jackson",
            "location_state": "MS",
            "device": str(uuid.uuid4()),
            "template_vpn_profile": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "hub_protected_prefix": "not-a-cidr",
            "member_protected_prefix": "192.168.1.0/24",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("hub_protected_prefix", response.json())

    def test_invalid_member_prefix_returns_400(self):
        """POST with invalid member_protected_prefix returns 400."""
        payload = {
            "member_name": "acme-corp",
            "member_display_name": "Acme Corp",
            "location_city": "Jackson",
            "location_state": "MS",
            "device": str(uuid.uuid4()),
            "template_vpn_profile": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "hub_protected_prefix": "10.100.0.0/24",
            "member_protected_prefix": "garbage",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("member_protected_prefix", response.json())

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
            "hub_protected_prefix": "10.100.0.0/24",
            "member_protected_prefix": "192.168.1.0/24",
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
        self.assertIn("psk_url", data)
        self.assertEqual(data["vpn_id"], "vpn-nrtc-ms-acme-corp-jackson-ms-001")

        # Verify VPN created
        vpn = VPN.objects.get(vpn_id="vpn-nrtc-ms-acme-corp-jackson-ms-001")
        self.assertEqual(vpn.name, "Acme Corp - Jackson, MS")

        # Verify VPNTunnel created
        tunnel = VPNTunnel.objects.get(pk=data["tunnel_id"])
        self.assertEqual(tunnel.vpn, vpn)
        self.assertIn("Acme Corp - Jackson, MS - 2000", tunnel.name)

        # Verify VPNProfile cloned (not the template)
        profile = tunnel.vpn_profile
        self.assertNotEqual(profile.pk, self.template_profile.pk)
        self.assertIn("vpnprofile-nrtc-ms-acme-corp-jackson-ms-2000", profile.name)
        # Verify Phase1/Phase2 policies were copied
        self.assertEqual(profile.vpn_profile_phase1_policy_assignments.count(), 1)
        self.assertEqual(profile.vpn_profile_phase2_policy_assignments.count(), 1)
        # Verify custom fields on profile
        self.assertEqual(
            profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"],  # pylint: disable=protected-access
            2000,
        )
        self.assertFalse(
            profile._custom_field_data["custom_tunnel_builder_psk_retrieved"],  # pylint: disable=protected-access
        )

        # Verify hub endpoint
        hub = tunnel.endpoint_a
        self.assertEqual(hub.source_ipaddress, self.device.primary_ip)
        self.assertEqual(hub.protected_prefixes.count(), 1)
        self.assertEqual(str(hub.protected_prefixes.first().prefix), "10.100.0.0/24")
        self.assertEqual(
            hub._custom_field_data["custom_tunnel_builder_crypto_map_name"],  # pylint: disable=protected-access
            "VPN",
        )

        # Verify spoke endpoint
        spoke = tunnel.endpoint_z
        self.assertIsNotNone(spoke.source_ipaddress)
        self.assertEqual(str(spoke.source_ipaddress.address.ip), "203.0.113.50")
        self.assertEqual(spoke.protected_prefixes.count(), 1)
        self.assertEqual(str(spoke.protected_prefixes.first().prefix), "192.168.1.0/24")

        # Verify member device created
        member_device = Device.objects.get(name="member-acme-corp-jackson-ms")
        self.assertEqual(member_device.device_type.model, "Member VPN Endpoint")
        dummy0 = Interface.objects.get(device=member_device, name="dummy0")
        self.assertIsNotNone(dummy0)

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
    def test_crypto_map_sequence_starts_at_2000(self, _mock_op):
        """First tunnel gets sequence 2000."""
        payload = _valid_payload(self.device, self.template_profile)
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        tunnel = VPNTunnel.objects.get(pk=response.json()["tunnel_id"])
        profile = tunnel.vpn_profile
        seq = profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"]  # pylint: disable=protected-access
        self.assertEqual(seq, 2000)

    @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
    def test_crypto_map_sequence_increments(self, _mock_op):
        """Second tunnel on same device gets sequence 2010."""
        payload = _valid_payload(self.device, self.template_profile)
        self._post(PORTAL_REQUEST_URL, payload)

        payload2 = _valid_payload(self.device, self.template_profile)
        payload2["remote_peer_ip"] = "203.0.113.51"
        resp2 = self._post(PORTAL_REQUEST_URL, payload2)

        tunnel2 = VPNTunnel.objects.get(pk=resp2.json()["tunnel_id"])
        seq = tunnel2.vpn_profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"]  # pylint: disable=protected-access
        self.assertEqual(seq, 2010)

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


# ---------------------------------------------------------------------------
# PSK retrieval endpoint tests (authenticated)
# ---------------------------------------------------------------------------


class PSKRetrievalTest(APITestCase):  # pylint: disable=too-many-ancestors
    """Test the psk retrieval endpoint."""

    def _get(self, url):
        return self.client.get(url, **self.header)

    def test_invalid_token_returns_404(self):
        """GET with an invalid/unknown token returns 404."""
        response = self._get(PSK_URL_TEMPLATE.format("nonexistent-token-value"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        data = response.json()
        self.assertTrue("error" in data or "detail" in data)

    def test_random_uuid_token_returns_404(self):
        """GET with a random UUID-like token returns 404."""
        response = self._get(PSK_URL_TEMPLATE.format(str(uuid.uuid4())))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_already_retrieved_returns_410(self):
        """GET on a profile with psk_retrieved=True returns 410 Gone."""
        VPNProfile.objects.create(
            name="test-retrieved-profile",
            _custom_field_data={
                "custom_tunnel_builder_psk_retrieval_token": "test-token-already-used",
                "custom_tunnel_builder_psk_retrieved": True,
            },
        )
        response = self._get(PSK_URL_TEMPLATE.format("test-token-already-used"))
        self.assertEqual(response.status_code, status.HTTP_410_GONE)
