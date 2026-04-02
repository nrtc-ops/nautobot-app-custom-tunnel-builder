"""Tests for algorithm translation maps in constants."""

from django.test import TestCase

from nautobot_custom_tunnel_builder.constants import (
    NAUTOBOT_TO_IOSXE_IKE_VERSION,
    NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_IKEV1_HASH,
    NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY,
    NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY,
    get_iosxe_device_queryset,
)


class Phase1EncryptionMapTest(TestCase):
    """Verify Phase 1 encryption translation map."""

    def test_aes256cbc(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["AES-256-CBC"], "aes-cbc-256")

    def test_aes128cbc(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["AES-128-CBC"], "aes-cbc-128")

    def test_aes256gcm(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["AES-256-GCM"], "aes-gcm-256")

    def test_aes128gcm(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["AES-128-GCM"], "aes-gcm-128")

    def test_unknown_raises_keyerror(self):
        with self.assertRaises(KeyError):
            _ = NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION["UNKNOWN"]


class Phase1IntegrityMapTest(TestCase):
    """Verify Phase 1 integrity translation map."""

    def test_sha256(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY["SHA256"], "sha256")

    def test_sha384(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY["SHA384"], "sha384")

    def test_sha512(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY["SHA512"], "sha512")

    def test_sha1(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY["SHA1"], "sha")

    def test_md5(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY["MD5"], "md5")


class Phase2EncryptionMapTest(TestCase):
    """Verify Phase 2 encryption translation map."""

    def test_aes256cbc(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION["AES-256-CBC"], "esp-aes 256")

    def test_aes128cbc(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION["AES-128-CBC"], "esp-aes 128")

    def test_aes256gcm(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION["AES-256-GCM"], "esp-gcm 256")

    def test_aes128gcm(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION["AES-128-GCM"], "esp-gcm 128")


class Phase2IntegrityMapTest(TestCase):
    """Verify Phase 2 integrity translation map."""

    def test_sha256(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY["SHA256"], "esp-sha256-hmac")

    def test_sha384(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY["SHA384"], "esp-sha384-hmac")

    def test_sha512(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY["SHA512"], "esp-sha512-hmac")


class IkeVersionMapTest(TestCase):
    """Verify IKE version translation map."""

    def test_ikev2(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKE_VERSION["IKEv2"], "ikev2")

    def test_ikev1(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKE_VERSION["IKEv1"], "ikev1")


class IKEv1EncryptionMapTest(TestCase):
    """Verify IKEv1-specific encryption translation map."""

    def test_aes256(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION["AES-256-CBC"], "aes 256")

    def test_aes128(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION["AES-128-CBC"], "aes")

    def test_aes192(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION["AES-192-CBC"], "aes 192")

    def test_3des(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION["3DES"], "3des")


class IKEv1HashMapTest(TestCase):
    """Verify IKEv1-specific hash translation map."""

    def test_sha256(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKEV1_HASH["SHA256"], "sha256")

    def test_sha1(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKEV1_HASH["SHA1"], "sha")

    def test_md5(self):
        self.assertEqual(NAUTOBOT_TO_IOSXE_IKEV1_HASH["MD5"], "md5")


class DeviceQuerysetTest(TestCase):
    """Verify shared device queryset filters both cisco_ios and cisco_xe."""

    def test_queryset_filters_correct_drivers(self):
        qs = get_iosxe_device_queryset()
        where_clause = str(qs.query)
        self.assertIn("cisco_xe", where_clause)
        self.assertIn("cisco_ios", where_clause)
