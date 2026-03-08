"""Forms for the Custom Tunnel Builder app."""

import ipaddress

from django import forms
from nautobot.dcim.models import Device


# ---------------------------------------------------------------------------
# IKE Version
# ---------------------------------------------------------------------------

IKE_VERSION_CHOICES = [
    ("ikev2", "IKEv2 (Recommended)"),
    ("ikev1", "IKEv1 (Legacy)"),
]

# ---------------------------------------------------------------------------
# IKEv1 Phase 1 choices
# ---------------------------------------------------------------------------

IKEV1_ENCRYPTION_CHOICES = [
    ("aes 256", "AES-256 (Recommended)"),
    ("aes", "AES-128"),
    ("aes 192", "AES-192"),
    ("3des", "3DES (Legacy)"),
]

IKEV1_HASH_CHOICES = [
    ("sha256", "SHA-256 (Recommended)"),
    ("sha384", "SHA-384"),
    ("sha512", "SHA-512"),
    ("sha", "SHA-1 (Legacy)"),
    ("md5", "MD5 (Legacy)"),
]

# ---------------------------------------------------------------------------
# IKEv2 Phase 1 choices
# ---------------------------------------------------------------------------

IKEV2_ENCRYPTION_CHOICES = [
    ("aes-cbc-256", "AES-CBC-256 (Recommended)"),
    ("aes-cbc-128", "AES-CBC-128"),
    ("aes-gcm-256", "AES-GCM-256"),
    ("aes-gcm-128", "AES-GCM-128"),
]

IKEV2_INTEGRITY_CHOICES = [
    ("sha256", "SHA-256 (Recommended)"),
    ("sha384", "SHA-384"),
    ("sha512", "SHA-512"),
]

# ---------------------------------------------------------------------------
# Shared IKE choices
# ---------------------------------------------------------------------------

IKE_DH_GROUP_CHOICES = [
    ("19", "Group 19 - 256-bit ECP (Recommended)"),
    ("20", "Group 20 - 384-bit ECP"),
    ("21", "Group 21 - 521-bit ECP"),
    ("14", "Group 14 - 2048-bit MODP"),
    ("5",  "Group 5  - 1536-bit MODP (IKEv1 Legacy)"),
    ("2",  "Group 2  - 1024-bit MODP (IKEv1 Legacy)"),
]

# ---------------------------------------------------------------------------
# IPsec Phase 2 choices (shared between IKEv1 and IKEv2)
# ---------------------------------------------------------------------------

IPSEC_ENCRYPTION_CHOICES = [
    ("esp-aes 256", "ESP-AES-256 (Recommended)"),
    ("esp-aes 128", "ESP-AES-128"),
    ("esp-gcm 256", "ESP-GCM-256"),
    ("esp-gcm 128", "ESP-GCM-128"),
]

IPSEC_INTEGRITY_CHOICES = [
    ("esp-sha256-hmac", "ESP-SHA256-HMAC (Recommended)"),
    ("esp-sha384-hmac", "ESP-SHA384-HMAC"),
    ("esp-sha512-hmac", "ESP-SHA512-HMAC"),
    # GCM modes provide authentication natively; no separate HMAC needed.
    ("", "None (use with GCM encryption)"),
]


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

class IpsecTunnelForm(forms.Form):
    """Form for building a policy-based IPsec tunnel (IKEv1 or IKEv2) on a Cisco IOS-XE device."""

    # ------------------------------------------------------------------ #
    # Device                                                               #
    # ------------------------------------------------------------------ #
    device = forms.ModelChoiceField(
        queryset=Device.objects.filter(platform__network_driver="cisco_xe").order_by("name"),
        label="Target Device",
        help_text="Select the IOS-XE device to configure. Only devices with the 'cisco_ios' platform driver are listed.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # ------------------------------------------------------------------ #
    # IKE version                                                          #
    # ------------------------------------------------------------------ #
    ike_version = forms.ChoiceField(
        label="IKE Version",
        choices=IKE_VERSION_CHOICES,
        initial="ikev2",
        help_text="IKEv2 is strongly recommended. Select IKEv1 only for compatibility with legacy peers.",
        widget=forms.Select(attrs={"class": "form-select", "id": "id_ike_version"}),
    )

    # ------------------------------------------------------------------ #
    # Remote peer                                                          #
    # ------------------------------------------------------------------ #
    remote_peer_ip = forms.GenericIPAddressField(
        label="Remote Peer IP Address",
        protocol="IPv4",
        help_text="Public IP address of the remote IPsec peer.",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "203.0.113.1"}),
    )

    # ------------------------------------------------------------------ #
    # Interesting traffic (crypto ACL)                                     #
    # ------------------------------------------------------------------ #
    local_network = forms.CharField(
        label="Local Network (CIDR)",
        max_length=18,
        help_text="Local subnet to encrypt (e.g. 192.168.1.0/24).",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "192.168.1.0/24"}),
    )

    remote_network = forms.CharField(
        label="Remote Network (CIDR)",
        max_length=18,
        help_text="Remote subnet to encrypt (e.g. 10.0.0.0/24).",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "10.0.0.0/24"}),
    )

    crypto_acl_name = forms.CharField(
        label="Crypto ACL Name",
        max_length=64,
        initial="VPN-ACL",
        help_text="Name of the extended ACL that defines interesting traffic.",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "VPN-ACL"}),
    )

    # ------------------------------------------------------------------ #
    # Crypto map                                                           #
    # ------------------------------------------------------------------ #
    wan_interface = forms.CharField(
        label="WAN Interface",
        max_length=64,
        initial="GigabitEthernet1",
        help_text="Physical interface where the crypto map will be applied.",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "GigabitEthernet1"}),
    )

    crypto_map_name = forms.CharField(
        label="Crypto Map Name",
        max_length=64,
        initial="CRYPTO-MAP",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "CRYPTO-MAP"}),
    )

    crypto_map_sequence = forms.IntegerField(
        label="Crypto Map Sequence",
        min_value=1,
        max_value=65535,
        initial=10,
        help_text="Sequence number within the crypto map (lower numbers evaluated first).",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    # ------------------------------------------------------------------ #
    # Shared IKE parameters                                                #
    # ------------------------------------------------------------------ #
    ike_dh_group = forms.ChoiceField(
        label="IKE Diffie-Hellman Group",
        choices=IKE_DH_GROUP_CHOICES,
        initial="19",
        help_text="Groups 2 and 5 are IKEv1 legacy only — rejected if IKEv2 is selected.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ike_lifetime = forms.IntegerField(
        label="IKE SA Lifetime (seconds)",
        min_value=300,
        max_value=86400,
        initial=86400,
        help_text="IKE SA lifetime in seconds (300–86400). Default: 86400 (24 h).",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    # ------------------------------------------------------------------ #
    # IKEv1-specific Phase 1                                               #
    # ------------------------------------------------------------------ #
    isakmp_policy_priority = forms.IntegerField(
        label="ISAKMP Policy Priority",
        min_value=1,
        max_value=10000,
        initial=10,
        required=False,
        help_text="Lower number = higher priority. Required when IKEv1 is selected.",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    ikev1_encryption = forms.ChoiceField(
        label="ISAKMP Encryption",
        choices=IKEV1_ENCRYPTION_CHOICES,
        initial="aes 256",
        required=False,
        help_text="Phase 1 encryption cipher (crypto isakmp policy).",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ikev1_hash = forms.ChoiceField(
        label="ISAKMP Hash / Integrity",
        choices=IKEV1_HASH_CHOICES,
        initial="sha256",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # ------------------------------------------------------------------ #
    # IKEv2-specific Phase 1                                               #
    # ------------------------------------------------------------------ #
    ikev2_proposal_name = forms.CharField(
        label="IKEv2 Proposal Name",
        max_length=64,
        initial="IKEv2-PROPOSAL",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IKEv2-PROPOSAL"}),
    )

    ikev2_policy_name = forms.CharField(
        label="IKEv2 Policy Name",
        max_length=64,
        initial="IKEv2-POLICY",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IKEv2-POLICY"}),
    )

    ikev2_keyring_name = forms.CharField(
        label="IKEv2 Keyring Name",
        max_length=64,
        initial="IKEv2-KEYRING",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IKEv2-KEYRING"}),
    )

    ikev2_profile_name = forms.CharField(
        label="IKEv2 Profile Name",
        max_length=64,
        initial="IKEv2-PROFILE",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IKEv2-PROFILE"}),
    )

    ikev2_encryption = forms.ChoiceField(
        label="IKEv2 Encryption",
        choices=IKEV2_ENCRYPTION_CHOICES,
        initial="aes-cbc-256",
        required=False,
        help_text="Phase 1 encryption cipher (crypto ikev2 proposal).",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ikev2_integrity = forms.ChoiceField(
        label="IKEv2 Integrity",
        choices=IKEV2_INTEGRITY_CHOICES,
        initial="sha256",
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # ------------------------------------------------------------------ #
    # Pre-shared key                                                       #
    # ------------------------------------------------------------------ #
    pre_shared_key = forms.CharField(
        label="Pre-Shared Key",
        max_length=128,
        help_text="IKE pre-shared key. Transmitted to the device over SSH; not stored in Nautobot.",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "••••••••"},
            render_value=False,
        ),
    )

    # ------------------------------------------------------------------ #
    # IPsec Phase 2                                                        #
    # ------------------------------------------------------------------ #
    ipsec_transform_set_name = forms.CharField(
        label="IPsec Transform-Set Name",
        max_length=64,
        initial="IPSEC-TS",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IPSEC-TS"}),
    )

    ipsec_encryption = forms.ChoiceField(
        label="IPsec Encryption Algorithm",
        choices=IPSEC_ENCRYPTION_CHOICES,
        initial="esp-aes 256",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ipsec_integrity = forms.ChoiceField(
        label="IPsec Integrity Algorithm",
        choices=IPSEC_INTEGRITY_CHOICES,
        initial="esp-sha256-hmac",
        help_text="Leave blank when using GCM encryption (authentication is built-in).",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ipsec_lifetime = forms.IntegerField(
        label="IPsec SA Lifetime (seconds)",
        min_value=120,
        max_value=86400,
        initial=3600,
        help_text="IPsec SA lifetime in seconds (120–86400). Default: 3600 (1 h).",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    # ------------------------------------------------------------------ #
    # Validation                                                           #
    # ------------------------------------------------------------------ #

    def _validate_cidr_network(self, field_name):
        value = self.cleaned_data.get(field_name, "")
        if not value:
            return value
        try:
            net = ipaddress.IPv4Network(value, strict=False)
        except ValueError:
            raise forms.ValidationError(
                "Enter a valid IPv4 network in CIDR notation, e.g. 192.168.1.0/24."
            )
        return str(net)

    def clean_local_network(self):
        return self._validate_cidr_network("local_network")

    def clean_remote_network(self):
        return self._validate_cidr_network("remote_network")

    def clean(self):
        cleaned = super().clean()
        version = cleaned.get("ike_version", "ikev2")
        dh_group = cleaned.get("ike_dh_group", "")

        # IKEv2 rejects legacy DH groups
        if version == "ikev2" and dh_group in ("2", "5"):
            self.add_error(
                "ike_dh_group",
                "DH Groups 2 and 5 are not supported with IKEv2. Select Group 14 or higher.",
            )

        # IKEv1-specific required fields
        if version == "ikev1":
            for field in ("isakmp_policy_priority", "ikev1_encryption", "ikev1_hash"):
                if not cleaned.get(field):
                    self.add_error(field, "This field is required when IKEv1 is selected.")

        # IKEv2-specific required fields
        if version == "ikev2":
            for field in (
                "ikev2_proposal_name", "ikev2_policy_name",
                "ikev2_keyring_name", "ikev2_profile_name",
                "ikev2_encryption", "ikev2_integrity",
            ):
                if not cleaned.get(field):
                    self.add_error(field, "This field is required when IKEv2 is selected.")

        # IPsec Phase 2: GCM provides authentication natively — no HMAC allowed
        enc = cleaned.get("ipsec_encryption", "")
        integ = cleaned.get("ipsec_integrity", "")
        gcm_modes = {"esp-gcm 128", "esp-gcm 256"}
        if enc in gcm_modes and integ:
            self.add_error(
                "ipsec_integrity",
                "GCM encryption provides authentication natively. Select 'None' for the integrity algorithm.",
            )
        if enc not in gcm_modes and not integ:
            self.add_error(
                "ipsec_integrity",
                "An integrity algorithm is required when not using GCM encryption.",
            )

        return cleaned
