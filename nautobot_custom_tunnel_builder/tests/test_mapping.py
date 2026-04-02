"""Tests for VPNProfile → IOS-XE config parameter mapping."""

from unittest.mock import MagicMock

from django.test import TestCase

from nautobot_custom_tunnel_builder.mapping import profile_to_config_params


def _make_phase1_policy(ike_version="IKEv2", encryption=None, integrity=None, dh_group=None, lifetime=86400):
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


_COMMON_KWARGS = {
    "remote_peer_ip": "203.0.113.1",
    "local_network_cidr": "192.168.1.0/24",
    "protected_network_cidr": "10.0.0.0/24",
    "crypto_map_name": "CRYPTO-MAP",
    "sequence": 10,
}


class ProfileToConfigParamsIKEv2Test(TestCase):
    """Test IKEv2 profile mapping."""

    def test_standard_ikev2_profile(self):
        result = profile_to_config_params(vpn_profile=_make_profile(), **_COMMON_KWARGS)
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
        result = profile_to_config_params(vpn_profile=_make_profile(), **{**_COMMON_KWARGS, "sequence": 20})
        self.assertEqual(result["crypto_acl_name"], "PORTAL-ACL-20")
        self.assertEqual(result["ipsec_transform_set_name"], "PORTAL-TS-20")
        self.assertEqual(result["ikev2_proposal_name"], "PORTAL-PROP-20")
        self.assertEqual(result["ikev2_policy_name"], "PORTAL-POL-20")
        self.assertEqual(result["ikev2_keyring_name"], "PORTAL-KR-20")
        self.assertEqual(result["ikev2_profile_name"], "PORTAL-PROF-20")

    def test_gcm_encryption_clears_integrity(self):
        phase1 = _make_phase1_policy(encryption=["AES-256-GCM"])
        phase2 = _make_phase2_policy(encryption=["AES-256-GCM"])
        result = profile_to_config_params(vpn_profile=_make_profile(phase1, phase2), **_COMMON_KWARGS)
        self.assertEqual(result["ipsec_encryption"], "esp-gcm 256")
        self.assertEqual(result["ipsec_integrity"], "")

    def test_no_wan_interface_in_output(self):
        result = profile_to_config_params(vpn_profile=_make_profile(), **_COMMON_KWARGS)
        self.assertNotIn("wan_interface", result)


class ProfileToConfigParamsIKEv1Test(TestCase):
    """Test IKEv1 profile mapping."""

    def test_ikev1_profile(self):
        phase1 = _make_phase1_policy(ike_version="IKEv1", encryption=["AES-256-CBC"], dh_group=["14"])
        result = profile_to_config_params(vpn_profile=_make_profile(phase1=phase1), **_COMMON_KWARGS)
        self.assertEqual(result["ike_version"], "ikev1")
        self.assertEqual(result["ikev1_encryption"], "aes 256")
        self.assertEqual(result["ikev1_hash"], "sha256")
        self.assertEqual(result["isakmp_policy_priority"], 10)
        self.assertNotIn("ikev2_encryption", result)


class ProfileToConfigParamsEdgeCasesTest(TestCase):
    """Test edge cases in profile mapping."""

    def test_missing_phase1_raises(self):
        profile = MagicMock()
        profile.vpnprofilephase1policyassignment_set.order_by.return_value.first.return_value = None
        with self.assertRaises(ValueError) as ctx:
            profile_to_config_params(vpn_profile=profile, **_COMMON_KWARGS)
        self.assertIn("Phase 1", str(ctx.exception))

    def test_missing_phase2_raises(self):
        profile = _make_profile()
        profile.vpnprofilephase2policyassignment_set.order_by.return_value.first.return_value = None
        with self.assertRaises(ValueError) as ctx:
            profile_to_config_params(vpn_profile=profile, **_COMMON_KWARGS)
        self.assertIn("Phase 2", str(ctx.exception))
