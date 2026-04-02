"""Tests for the portal REST API endpoints."""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from nautobot.core.testing import APITestCase
from rest_framework import status
from rest_framework.test import APIClient

User = get_user_model()

# ---------------------------------------------------------------------------
# Base URL for the portal API (under the plugin's base_url)
# ---------------------------------------------------------------------------

PORTAL_REQUEST_URL = "/plugins/tunnel-builder/api/portal-request/"
TUNNEL_STATUS_URL_TEMPLATE = "/plugins/tunnel-builder/api/tunnel-status/{}/"
PSK_URL_TEMPLATE = "/plugins/tunnel-builder/api/psk/{}/"


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


class PortalRequestValidationTest(APITestCase): # pylint: disable=too-many-ancestors
    """Test validation on the portal-request endpoint."""

    def _post(self, url, data=None):
        """POST with auth header."""
        return self.client.post(url, data=data or {}, format="json", **self.header)

    def _get(self, url):
        """GET with auth header."""
        return self.client.get(url, **self.header)

    def test_empty_body_returns_400(self):
        """POST with empty body returns 400 with field errors."""
        response = self._post(PORTAL_REQUEST_URL)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.json()
        # All required fields should appear in the error response
        for field in ("vpn_profile", "device", "remote_peer_ip", "local_network_cidr", "protected_network_cidr"):
            self.assertIn(field, data, f"Expected error for missing field: {field}")

    def test_missing_vpn_profile_returns_400(self):
        """POST without vpn_profile returns 400."""
        payload = {
            "device": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "local_network_cidr": "192.168.1.0/24",
            "protected_network_cidr": "10.0.0.0/24",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vpn_profile", response.json())

    def test_missing_device_returns_400(self):
        """POST without device returns 400."""
        payload = {
            "vpn_profile": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "local_network_cidr": "192.168.1.0/24",
            "protected_network_cidr": "10.0.0.0/24",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("device", response.json())

    def test_invalid_cidr_local_returns_400(self):
        """POST with invalid local_network_cidr returns 400."""
        payload = {
            "vpn_profile": str(uuid.uuid4()),
            "device": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "local_network_cidr": "not-a-cidr",
            "protected_network_cidr": "10.0.0.0/24",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("local_network_cidr", response.json())

    def test_invalid_cidr_protected_returns_400(self):
        """POST with invalid protected_network_cidr returns 400."""
        payload = {
            "vpn_profile": str(uuid.uuid4()),
            "device": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "local_network_cidr": "192.168.1.0/24",
            "protected_network_cidr": "garbage",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("protected_network_cidr", response.json())

    def test_non_existent_profile_uuid_returns_400(self):
        """POST with a UUID that doesn't match any VPNProfile returns 400."""
        payload = {
            "vpn_profile": str(uuid.uuid4()),
            "device": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "local_network_cidr": "192.168.1.0/24",
            "protected_network_cidr": "10.0.0.0/24",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # At least vpn_profile or device should have an error (non-existent UUID)
        data = response.json()
        self.assertTrue(
            "vpn_profile" in data or "device" in data,
            "Expected validation error for non-existent UUID(s)",
        )

    def test_non_existent_device_uuid_returns_400(self):
        """POST with a UUID that doesn't match any Device returns 400."""
        payload = {
            "vpn_profile": str(uuid.uuid4()),
            "device": str(uuid.uuid4()),
            "remote_peer_ip": "203.0.113.1",
            "local_network_cidr": "192.168.1.0/24",
            "protected_network_cidr": "10.0.0.0/24",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("device", response.json())

    def test_invalid_remote_peer_ip_returns_400(self):
        """POST with an invalid IP address returns 400."""
        payload = {
            "vpn_profile": str(uuid.uuid4()),
            "device": str(uuid.uuid4()),
            "remote_peer_ip": "not-an-ip",
            "local_network_cidr": "192.168.1.0/24",
            "protected_network_cidr": "10.0.0.0/24",
        }
        response = self._post(PORTAL_REQUEST_URL, payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("remote_peer_ip", response.json())


# ---------------------------------------------------------------------------
# Tunnel status endpoint tests (authenticated)
# ---------------------------------------------------------------------------


class TunnelStatusTest(APITestCase): # pylint: disable=too-many-ancestors
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


class PSKRetrievalTest(APITestCase): # pylint: disable=too-many-ancestors
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
