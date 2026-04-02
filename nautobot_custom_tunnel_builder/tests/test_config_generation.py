"""Tests for the IOS-XE policy-based IPsec config generation engine."""

from django.test import TestCase

from nautobot_custom_tunnel_builder.jobs import _cidr_to_net_wildcard, build_iosxe_policy_config

# ---------------------------------------------------------------------------
# Helper data dicts
# ---------------------------------------------------------------------------


def _ikev2_data(**overrides):
    """Return a complete IKEv2 data dict suitable for build_iosxe_policy_config()."""
    base = {
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
        "pre_shared_key": "SuperSecret123!",
        "ipsec_transform_set_name": "IPSEC-TS",
        "ipsec_encryption": "esp-aes 256",
        "ipsec_integrity": "esp-sha256-hmac",
        "ipsec_lifetime": 3600,
    }
    base.update(overrides)
    return base


def _ikev1_data(**overrides):
    """Return a complete IKEv1 data dict suitable for build_iosxe_policy_config()."""
    base = {
        "ike_version": "ikev1",
        "remote_peer_ip": "198.51.100.1",
        "local_network": "172.16.0.0/16",
        "remote_network": "10.10.0.0/24",
        "crypto_acl_name": "VPN-ACL-V1",
        "wan_interface": "GigabitEthernet2",
        "crypto_map_name": "CMAP-V1",
        "crypto_map_sequence": 20,
        "ike_dh_group": "14",
        "ike_lifetime": 28800,
        "isakmp_policy_priority": 10,
        "ikev1_encryption": "aes 256",
        "ikev1_hash": "sha256",
        "pre_shared_key": "V1Secret!",
        "ipsec_transform_set_name": "TS-V1",
        "ipsec_encryption": "esp-aes 256",
        "ipsec_integrity": "esp-sha256-hmac",
        "ipsec_lifetime": 7200,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _cidr_to_net_wildcard
# ---------------------------------------------------------------------------


class CidrToNetWildcardTest(TestCase):
    """Verify CIDR-to-network/wildcard conversion."""

    def test_slash_24(self):
        net, wildcard = _cidr_to_net_wildcard("192.168.1.0/24")
        self.assertEqual(net, "192.168.1.0")
        self.assertEqual(wildcard, "0.0.0.255")

    def test_host_slash_32(self):
        net, wildcard = _cidr_to_net_wildcard("10.0.0.1/32")
        self.assertEqual(net, "10.0.0.1")
        self.assertEqual(wildcard, "0.0.0.0")

    def test_slash_16(self):
        net, wildcard = _cidr_to_net_wildcard("172.16.0.0/16")
        self.assertEqual(net, "172.16.0.0")
        self.assertEqual(wildcard, "0.0.255.255")

    def test_slash_8(self):
        net, wildcard = _cidr_to_net_wildcard("10.0.0.0/8")
        self.assertEqual(net, "10.0.0.0")
        self.assertEqual(wildcard, "0.255.255.255")

    def test_slash_30(self):
        net, wildcard = _cidr_to_net_wildcard("192.168.1.0/30")
        self.assertEqual(net, "192.168.1.0")
        self.assertEqual(wildcard, "0.0.0.3")

    def test_non_boundary_host_normalised(self):
        """A host address in the middle of a subnet is normalised to network address."""
        net, wildcard = _cidr_to_net_wildcard("192.168.1.50/24")
        self.assertEqual(net, "192.168.1.0")
        self.assertEqual(wildcard, "0.0.0.255")


# ---------------------------------------------------------------------------
# build_iosxe_policy_config — IKEv2
# ---------------------------------------------------------------------------


class BuildIosxePolicyConfigIKEv2Test(TestCase):
    """Test IKEv2 configuration generation."""

    def setUp(self):
        self.data = _ikev2_data()
        self.commands = build_iosxe_policy_config(self.data)

    def test_contains_ikev2_proposal(self):
        self.assertIn("crypto ikev2 proposal IKEv2-PROPOSAL", self.commands)

    def test_contains_ikev2_policy(self):
        self.assertIn("crypto ikev2 policy IKEv2-POLICY", self.commands)

    def test_contains_ikev2_keyring(self):
        self.assertIn("crypto ikev2 keyring IKEv2-KEYRING", self.commands)

    def test_contains_ikev2_profile(self):
        self.assertIn("crypto ikev2 profile IKEv2-PROFILE", self.commands)

    def test_proposal_encryption(self):
        self.assertIn(" encryption aes-cbc-256", self.commands)

    def test_proposal_integrity(self):
        self.assertIn(" integrity sha256", self.commands)

    def test_proposal_dh_group(self):
        self.assertIn(" group 19", self.commands)

    def test_crypto_acl_network_wildcard(self):
        """ACL contains correct source/dest network and wildcard masks."""
        acl_line = " permit ip 192.168.1.0 0.0.0.255 10.0.0.0 0.0.255.255"
        self.assertIn(acl_line, self.commands)

    def test_crypto_acl_name(self):
        self.assertIn("ip access-list extended VPN-ACL", self.commands)

    def test_transform_set_with_integrity(self):
        self.assertIn("crypto ipsec transform-set IPSEC-TS esp-aes 256 esp-sha256-hmac", self.commands)

    def test_transform_set_tunnel_mode(self):
        self.assertIn(" mode tunnel", self.commands)

    def test_crypto_map_entry(self):
        self.assertIn("crypto map CRYPTO-MAP 10 ipsec-isakmp", self.commands)

    def test_crypto_map_peer(self):
        self.assertIn(" set peer 203.0.113.1", self.commands)

    def test_crypto_map_transform_set(self):
        self.assertIn(" set transform-set IPSEC-TS", self.commands)

    def test_crypto_map_sa_lifetime(self):
        self.assertIn(" set security-association lifetime seconds 3600", self.commands)

    def test_crypto_map_ikev2_profile(self):
        self.assertIn(" set ikev2-profile IKEv2-PROFILE", self.commands)

    def test_crypto_map_match_address(self):
        self.assertIn(" match address VPN-ACL", self.commands)

    def test_wan_interface_applied(self):
        self.assertIn("interface GigabitEthernet1", self.commands)
        self.assertIn(" crypto map CRYPTO-MAP", self.commands)

    def test_psk_in_keyring(self):
        self.assertIn("  pre-shared-key local SuperSecret123!", self.commands)
        self.assertIn("  pre-shared-key remote SuperSecret123!", self.commands)

    def test_ike_lifetime_in_profile(self):
        self.assertIn(f" lifetime {self.data['ike_lifetime']}", self.commands)


# ---------------------------------------------------------------------------
# build_iosxe_policy_config — IKEv1
# ---------------------------------------------------------------------------


class BuildIosxePolicyConfigIKEv1Test(TestCase):
    """Test IKEv1 (ISAKMP) configuration generation."""

    def setUp(self):
        self.data = _ikev1_data()
        self.commands = build_iosxe_policy_config(self.data)

    def test_contains_isakmp_policy(self):
        self.assertIn("crypto isakmp policy 10", self.commands)

    def test_isakmp_encryption(self):
        self.assertIn(" encr aes 256", self.commands)

    def test_isakmp_hash(self):
        self.assertIn(" hash sha256", self.commands)

    def test_isakmp_authentication(self):
        self.assertIn(" authentication pre-share", self.commands)

    def test_isakmp_dh_group(self):
        self.assertIn(" group 14", self.commands)

    def test_isakmp_lifetime(self):
        self.assertIn(" lifetime 28800", self.commands)

    def test_isakmp_key_with_psk_and_peer(self):
        self.assertIn("crypto isakmp key V1Secret! address 198.51.100.1", self.commands)

    def test_no_ikev2_profile_in_crypto_map(self):
        """IKEv1 crypto map must NOT contain an ikev2-profile line."""
        ikev2_lines = [cmd for cmd in self.commands if "ikev2-profile" in cmd]
        self.assertEqual(ikev2_lines, [])

    def test_crypto_acl_network_wildcard(self):
        acl_line = " permit ip 172.16.0.0 0.0.255.255 10.10.0.0 0.0.0.255"
        self.assertIn(acl_line, self.commands)

    def test_crypto_map_entry(self):
        self.assertIn("crypto map CMAP-V1 20 ipsec-isakmp", self.commands)

    def test_wan_interface_applied(self):
        self.assertIn("interface GigabitEthernet2", self.commands)
        self.assertIn(" crypto map CMAP-V1", self.commands)


# ---------------------------------------------------------------------------
# build_iosxe_policy_config — GCM (no integrity)
# ---------------------------------------------------------------------------


class BuildIosxePolicyConfigGCMTest(TestCase):
    """Test GCM encryption produces transform-set without integrity algorithm."""

    def test_gcm_transform_set_no_integrity(self):
        data = _ikev2_data(
            ipsec_encryption="esp-gcm 256",
            ipsec_integrity="",
        )
        commands = build_iosxe_policy_config(data)
        ts_line = f"crypto ipsec transform-set {data['ipsec_transform_set_name']} esp-gcm 256"
        self.assertIn(ts_line, commands)
        # There should be no transform-set line that also contains an integrity suffix
        ts_lines = [cmd for cmd in commands if cmd.startswith("crypto ipsec transform-set")]
        self.assertEqual(len(ts_lines), 1)
        self.assertNotIn("esp-sha", ts_lines[0])

    def test_gcm_128_transform_set_no_integrity(self):
        data = _ikev2_data(
            ipsec_encryption="esp-gcm 128",
            ipsec_integrity="",
        )
        commands = build_iosxe_policy_config(data)
        ts_line = f"crypto ipsec transform-set {data['ipsec_transform_set_name']} esp-gcm 128"
        self.assertIn(ts_line, commands)


# ---------------------------------------------------------------------------
# build_iosxe_policy_config — ordering sanity
# ---------------------------------------------------------------------------


class BuildIosxePolicyConfigOrderTest(TestCase):
    """Verify that command ordering is correct for IOS-XE."""

    def test_ikev2_acl_before_transform_set(self):
        commands = build_iosxe_policy_config(_ikev2_data())
        acl_idx = next(i for i, c in enumerate(commands) if c.startswith("ip access-list"))
        ts_idx = next(i for i, c in enumerate(commands) if c.startswith("crypto ipsec transform-set"))
        self.assertLess(acl_idx, ts_idx)

    def test_ikev2_transform_set_before_crypto_map(self):
        commands = build_iosxe_policy_config(_ikev2_data())
        ts_idx = next(i for i, c in enumerate(commands) if c.startswith("crypto ipsec transform-set"))
        map_idx = next(i for i, c in enumerate(commands) if c.startswith("crypto map"))
        self.assertLess(ts_idx, map_idx)

    def test_interface_is_last(self):
        commands = build_iosxe_policy_config(_ikev2_data())
        self.assertTrue(commands[-1].strip().startswith("crypto map"))
        self.assertTrue(commands[-2].strip().startswith("interface"))
