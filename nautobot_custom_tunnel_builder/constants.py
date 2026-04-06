"""Shared choice constants for the Custom Tunnel Builder app."""

IKE_VERSION_CHOICES = (
    ("ikev2", "IKEv2 (Recommended)"),
    ("ikev1", "IKEv1 (Legacy)"),
)

IKEV1_ENCRYPTION_CHOICES = (
    ("aes 256", "AES-256 (Recommended)"),
    ("aes", "AES-128"),
    ("aes 192", "AES-192"),
    ("3des", "3DES (Legacy)"),
)

IKEV1_HASH_CHOICES = (
    ("sha256", "SHA-256 (Recommended)"),
    ("sha384", "SHA-384"),
    ("sha512", "SHA-512"),
    ("sha", "SHA-1 (Legacy)"),
    ("md5", "MD5 (Legacy)"),
)

IKEV2_ENCRYPTION_CHOICES = (
    ("aes-cbc-256", "AES-CBC-256 (Recommended)"),
    ("aes-cbc-128", "AES-CBC-128"),
    ("aes-gcm-256", "AES-GCM-256"),
    ("aes-gcm-128", "AES-GCM-128"),
)

IKEV2_INTEGRITY_CHOICES = (
    ("sha256", "SHA-256 (Recommended)"),
    ("sha384", "SHA-384"),
    ("sha512", "SHA-512"),
)

IKE_DH_GROUP_CHOICES = (
    ("19", "Group 19 - 256-bit ECP (Recommended)"),
    ("20", "Group 20 - 384-bit ECP"),
    ("21", "Group 21 - 521-bit ECP"),
    ("14", "Group 14 - 2048-bit MODP"),
    ("5", "Group 5  - 1536-bit MODP (IKEv1 Legacy)"),
    ("2", "Group 2  - 1024-bit MODP (IKEv1 Legacy)"),
)

IPSEC_ENCRYPTION_CHOICES = (
    ("esp-aes 256", "ESP-AES-256 (Recommended)"),
    ("esp-aes 128", "ESP-AES-128"),
    ("esp-gcm 256", "ESP-GCM-256"),
    ("esp-gcm 128", "ESP-GCM-128"),
)

IPSEC_INTEGRITY_CHOICES = (
    ("esp-sha256-hmac", "ESP-SHA256-HMAC (Recommended)"),
    ("esp-sha384-hmac", "ESP-SHA384-HMAC"),
    ("esp-sha512-hmac", "ESP-SHA512-HMAC"),
    ("", "None (use with GCM encryption)"),
)

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

NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION = {
    "AES-256-CBC": "aes 256",
    "AES-128-CBC": "aes",
    "AES-192-CBC": "aes 192",
    "3DES": "3des",
}

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
    from nautobot.dcim.models import Device  # noqa: E402  # pylint: disable=import-outside-toplevel

    return Device.objects.filter(platform__network_driver__in=["cisco_ios", "cisco_xe"]).order_by("name")
