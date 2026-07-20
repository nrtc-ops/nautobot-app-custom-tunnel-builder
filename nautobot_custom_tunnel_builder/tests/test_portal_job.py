"""Tests for PortalBuildIpsecTunnel job — real Nautobot objects, mocked SSH + 1Password."""

import logging
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from nautobot.core.testing import TestCase
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer, Platform
from nautobot.extras.models import Role, Secret, SecretsGroup, Status
from nautobot.ipam.models import IPAddress, IPAddressToInterface, Namespace, Prefix
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

from nautobot_custom_tunnel_builder.jobs import PortalBuildIpsecTunnel

CONNECT_HANDLER_PATH = "nautobot_custom_tunnel_builder.jobs.ConnectHandler"
SECRET_GET_VALUE_PATH = "nautobot.extras.models.Secret.get_value"


def _build_tunnel_objects():
    """Create a complete VPNTunnel hierarchy for portal job testing.

    Returns:
        Tuple of (tunnel, device) ready for PortalBuildIpsecTunnel.run().
    """
    # --- Device ---
    manufacturer, _ = Manufacturer.objects.get_or_create(name="Cisco")
    device_type, _ = DeviceType.objects.get_or_create(model="CSR1000v", manufacturer=manufacturer)
    platform, _ = Platform.objects.get_or_create(
        name="Cisco IOS-XE",
        defaults={"network_driver": "cisco_xe"},
    )
    role, _ = Role.objects.get_or_create(name="Router")
    location_type, _ = LocationType.objects.get_or_create(name="Site")
    active_loc = Status.objects.get_for_model(Location).get(name="Active")
    location, _ = Location.objects.get_or_create(
        name="HQ",
        location_type=location_type,
        defaults={"status": active_loc},
    )
    device, _ = Device.objects.get_or_create(
        name="job-test-router",
        defaults={
            "device_type": device_type,
            "platform": platform,
            "role": role,
            "location": location,
            "status": Status.objects.get_for_model(Device).get(name="Active"),
        },
    )
    intf, _ = Interface.objects.get_or_create(
        device=device,
        name="GigabitEthernet1",
        defaults={
            "type": "1000base-t",
            "status": Status.objects.get_for_model(Interface).get(name="Active"),
        },
    )
    global_ns, _ = Namespace.objects.get_or_create(name="Global")
    Prefix.objects.get_or_create(
        prefix="10.1.1.0/24",
        namespace=global_ns,
        defaults={"status": Status.objects.get_for_model(Prefix).get(name="Active")},
    )
    hub_ip, _ = IPAddress.objects.get_or_create(
        address="10.1.1.1/32",
        namespace=global_ns,
        defaults={"status": Status.objects.get_for_model(IPAddress).get(name="Active")},
    )
    IPAddressToInterface.objects.get_or_create(ip_address=hub_ip, interface=intf)
    device.primary_ip4 = hub_ip
    device.save()

    # --- Member device / spoke IP ---
    generic_mfr, _ = Manufacturer.objects.get_or_create(name="Generic")
    member_dt, _ = DeviceType.objects.get_or_create(model="Member VPN Endpoint", manufacturer=generic_mfr)
    member_loc_type, _ = LocationType.objects.get_or_create(name="Site")
    member_loc_active = Status.objects.get_for_model(Location).get(name="Active")
    member_loc, _ = Location.objects.get_or_create(
        name="Jackson, MS",
        location_type=member_loc_type,
        defaults={"status": member_loc_active},
    )
    member_role, _ = Role.objects.get_or_create(name="Member")
    member_device, _ = Device.objects.get_or_create(
        name="member-job-test-jackson-ms",
        defaults={
            "device_type": member_dt,
            "role": member_role,
            "location": member_loc,
            "status": Status.objects.get_for_model(Device).get(name="Active"),
        },
    )
    member_intf, _ = Interface.objects.get_or_create(
        device=member_device,
        name="dummy0",
        defaults={
            "type": "virtual",
            "status": Status.objects.get_for_model(Interface).get(name="Active"),
        },
    )
    members_ns, _ = Namespace.objects.get_or_create(name="Members")
    Prefix.objects.get_or_create(
        prefix="203.0.113.0/24",
        namespace=members_ns,
        defaults={"status": Status.objects.get_for_model(Prefix).get(name="Active")},
    )
    spoke_ip, _ = IPAddress.objects.get_or_create(
        address="203.0.113.50/32",
        namespace=members_ns,
        defaults={"status": Status.objects.get_for_model(IPAddress).get(name="Active")},
    )
    IPAddressToInterface.objects.get_or_create(ip_address=spoke_ip, interface=member_intf)

    # --- VPN Profile ---
    phase1 = VPNPhase1Policy.objects.create(
        name="JobTest-Phase1",
        ike_version="IKEv2",
        encryption_algorithm=["AES-256-CBC"],
        integrity_algorithm=["SHA256"],
        dh_group=["19"],
        lifetime_seconds=86400,
    )
    phase2 = VPNPhase2Policy.objects.create(
        name="JobTest-Phase2",
        encryption_algorithm=["AES-256-CBC"],
        integrity_algorithm=["SHA256"],
        lifetime=3600,
    )
    profile = VPNProfile.objects.create(name="jobtest-vpnprofile-3000")
    VPNProfilePhase1PolicyAssignment.objects.create(vpn_profile=profile, vpn_phase1_policy=phase1, weight=100)
    VPNProfilePhase2PolicyAssignment.objects.create(vpn_profile=profile, vpn_phase2_policy=phase2, weight=100)
    profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"] = 3000  # pylint: disable=protected-access
    profile.save()

    # --- Secret + SecretsGroup ---
    secret = Secret.objects.create(
        name="jobtest-psk-secret",
        provider="one-password",
        parameters={"item_id": "fake-op-item-id", "field": "password"},
    )
    sg = SecretsGroup.objects.create(name="jobtest-sg")
    sg.secrets.add(secret)
    profile.secrets_group = sg
    profile.save()

    # --- VPN + VPNTunnel ---
    vpn = VPN.objects.create(
        vpn_id="vpn-nrtc-ms-job-test-jackson-ms-001",
        name="Job Test - Jackson, MS",
    )
    tunnel_status = Status.objects.get_for_model(VPNTunnel).get(name="Active")
    tunnel = VPNTunnel.objects.create(
        name="Job Test - Jackson, MS - 3000",
        tunnel_id="vpn-tunnel-nrtc-ms-job-test-jackson-ms-3000",
        status=tunnel_status,
        vpn=vpn,
        vpn_profile=profile,
    )

    # --- Hub endpoint (endpoint_z = concentrator/NRTC side) ---
    hub_role, _ = Role.objects.get_or_create(name="Hub")
    hub_ep = VPNTunnelEndpoint.objects.create(role=hub_role, source_ipaddress=hub_ip)
    hub_ep._custom_field_data["custom_tunnel_builder_crypto_map_name"] = "VPN"  # pylint: disable=protected-access
    hub_ep.save()
    Prefix.objects.get_or_create(
        prefix="10.100.0.0/24",
        namespace=global_ns,
        defaults={"status": Status.objects.get_for_model(Prefix).get(name="Active")},
    )
    hub_prefix = Prefix.objects.get(prefix="10.100.0.0/24", namespace=global_ns)
    hub_ep.protected_prefixes.add(hub_prefix)
    tunnel.endpoint_z = hub_ep
    tunnel.save()

    # --- Spoke endpoint (endpoint_a = member/spoke side) ---
    spoke_role, _ = Role.objects.get_or_create(name="Spoke")
    spoke_ep = VPNTunnelEndpoint.objects.create(role=spoke_role, source_ipaddress=spoke_ip)
    Prefix.objects.get_or_create(
        prefix="192.168.1.0/24",
        namespace=members_ns,
        defaults={"status": Status.objects.get_for_model(Prefix).get(name="Active")},
    )
    spoke_prefix = Prefix.objects.get(prefix="192.168.1.0/24", namespace=members_ns)
    spoke_ep.protected_prefixes.add(spoke_prefix)
    tunnel.endpoint_a = spoke_ep
    tunnel.save()

    return tunnel, device


class PortalJobSSHTest(TestCase):
    """PortalBuildIpsecTunnel.run() with mocked SSH and 1Password."""

    @classmethod
    def setUpTestData(cls):
        cls.tunnel, cls.device = _build_tunnel_objects()
        # Ensure "Decommissioning" status exists and is mapped to VPNTunnel.
        # Nautobot's default seeded statuses may not include it; create if missing.
        vpntunnel_ct = ContentType.objects.get_for_model(VPNTunnel)
        decomm, _ = Status.objects.get_or_create(name="Decommissioning")
        decomm.content_types.add(vpntunnel_ct)

    def _run_job(self, mock_conn, mock_get_value, tunnel_id=None):
        """Instantiate the job, wire up a logger, and call run()."""
        job = PortalBuildIpsecTunnel()
        job.logger = logging.getLogger("test.portal_job")
        mock_get_value.return_value = "TestPSK-Secret-123!"
        mock_conn.return_value.__enter__ = MagicMock(return_value=mock_conn.return_value)
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.return_value.send_config_set.return_value = "config accepted"
        job.run(tunnel_id=str(tunnel_id or self.tunnel.pk))
        return mock_conn.return_value

    @patch(SECRET_GET_VALUE_PATH, return_value="TestPSK-Secret-123!")
    @patch(CONNECT_HANDLER_PATH)
    def test_ssh_connects_to_hub_ip(self, mock_connect, _mock_secret):
        """ConnectHandler is called with the hub device's primary IP."""
        self._run_job(mock_connect, _mock_secret)

        call_kwargs = mock_connect.call_args[1]
        self.assertEqual(call_kwargs["host"], "10.1.1.1")
        self.assertEqual(call_kwargs["device_type"], "cisco_xe")

    @patch(SECRET_GET_VALUE_PATH, return_value="TestPSK-Secret-123!")
    @patch(CONNECT_HANDLER_PATH)
    def test_send_config_set_called_once(self, mock_connect, _mock_secret):
        """send_config_set is called exactly once with a non-empty command list."""
        conn = self._run_job(mock_connect, _mock_secret)

        conn.send_config_set.assert_called_once()
        commands = conn.send_config_set.call_args[0][0]
        self.assertGreater(len(commands), 10)

    @patch(SECRET_GET_VALUE_PATH, return_value="TestPSK-Secret-123!")
    @patch(CONNECT_HANDLER_PATH)
    def test_save_config_called_on_success(self, mock_connect, _mock_secret):
        """save_config() is called after successful send_config_set."""
        conn = self._run_job(mock_connect, _mock_secret)
        conn.save_config.assert_called_once()

    @patch(SECRET_GET_VALUE_PATH, return_value="TestPSK-Secret-123!")
    @patch(CONNECT_HANDLER_PATH)
    def test_ikev2_commands_contain_correct_sequence(self, mock_connect, _mock_secret):
        """Config commands reference the correct crypto map sequence (3000)."""
        conn = self._run_job(mock_connect, _mock_secret)

        commands = conn.send_config_set.call_args[0][0]
        self.assertIn("crypto map VPN 3000 ipsec-isakmp", commands)
        self.assertIn("crypto ikev2 proposal PORTAL-PROP-3000", commands)
        self.assertIn("crypto ikev2 keyring PORTAL-KR-3000", commands)
        self.assertIn("ip access-list extended PORTAL-ACL-3000", commands)

    @patch(SECRET_GET_VALUE_PATH, return_value="TestPSK-Secret-123!")
    @patch(CONNECT_HANDLER_PATH)
    def test_peer_ip_in_commands(self, mock_connect, _mock_secret):
        """Spoke peer IP appears in the crypto map and keyring."""
        conn = self._run_job(mock_connect, _mock_secret)

        commands = conn.send_config_set.call_args[0][0]
        self.assertIn(" set peer 203.0.113.50", commands)
        self.assertIn("  address 203.0.113.50", commands)

    @patch(SECRET_GET_VALUE_PATH, return_value="TestPSK-Secret-123!")
    @patch(CONNECT_HANDLER_PATH)
    def test_psk_in_commands_but_not_logged(self, mock_connect, _mock_secret):
        """PSK appears in commands sent to device but is redacted in logs."""
        with self.assertLogs("test.portal_job", level="DEBUG") as log_ctx:
            conn = self._run_job(mock_connect, _mock_secret)

        commands = conn.send_config_set.call_args[0][0]
        psk = "TestPSK-Secret-123!"
        self.assertTrue(any(psk in cmd for cmd in commands), "PSK must appear in commands sent to device")

        full_log = "\n".join(log_ctx.output)
        self.assertNotIn(psk, full_log, "PSK must not appear in any log output")
        self.assertIn("***REDACTED***", full_log)

    @patch(SECRET_GET_VALUE_PATH, return_value="TestPSK-Secret-123!")
    @patch(CONNECT_HANDLER_PATH)
    def test_tunnel_status_set_to_active_on_success(self, mock_connect, _mock_secret):
        """Tunnel status is updated to Active after successful push."""
        self._run_job(mock_connect, _mock_secret)

        self.tunnel.refresh_from_db()
        self.assertEqual(self.tunnel.status.name, "Active")

    @patch(SECRET_GET_VALUE_PATH, return_value="TestPSK-Secret-123!")
    @patch(CONNECT_HANDLER_PATH)
    def test_tunnel_status_set_to_decommissioning_on_ssh_failure(self, mock_connect, _mock_secret):
        """Tunnel status is set to Decommissioning when SSH push fails."""
        mock_connect.side_effect = Exception("Connection refused")

        job = PortalBuildIpsecTunnel()
        job.logger = logging.getLogger("test.portal_job")
        _mock_secret.return_value = "TestPSK-Secret-123!"

        with self.assertRaises(Exception):
            job.run(tunnel_id=str(self.tunnel.pk))

        self.tunnel.refresh_from_db()
        self.assertEqual(self.tunnel.status.name, "Decommissioning")

    @patch(SECRET_GET_VALUE_PATH, side_effect=RuntimeError("1Password unavailable"))
    @patch(CONNECT_HANDLER_PATH)
    def test_psk_retrieval_failure_raises(self, mock_connect, _mock_secret):
        """If PSK retrieval from 1Password fails, job raises and SSH is never attempted."""
        job = PortalBuildIpsecTunnel()
        job.logger = logging.getLogger("test.portal_job")

        with self.assertRaises(RuntimeError):
            job.run(tunnel_id=str(self.tunnel.pk))

        mock_connect.assert_not_called()
