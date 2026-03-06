"""Forms for the IPsec Tunnel Builder app."""

from django import forms
from nautobot.dcim.models import Device


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

IKE_ENCRYPTION_CHOICES = [
    ("aes-cbc-128", "AES-CBC-128"),
    ("aes-cbc-256", "AES-CBC-256 (Recommended)"),
    ("aes-gcm-128", "AES-GCM-128"),
    ("aes-gcm-256", "AES-GCM-256"),
]

IKE_INTEGRITY_CHOICES = [
    ("sha256", "SHA-256 (Recommended)"),
    ("sha384", "SHA-384"),
    ("sha512", "SHA-512"),
]

IKE_DH_GROUP_CHOICES = [
    ("14", "Group 14 - 2048-bit MODP"),
    ("19", "Group 19 - 256-bit ECP (Recommended)"),
    ("20", "Group 20 - 384-bit ECP"),
    ("21", "Group 21 - 521-bit ECP"),
]

IPSEC_ENCRYPTION_CHOICES = [
    ("esp-aes 128", "ESP-AES-128"),
    ("esp-aes 256", "ESP-AES-256 (Recommended)"),
    ("esp-gcm 128", "ESP-GCM-128"),
    ("esp-gcm 256", "ESP-GCM-256"),
]

IPSEC_INTEGRITY_CHOICES = [
    ("esp-sha256-hmac", "ESP-SHA256-HMAC (Recommended)"),
    ("esp-sha384-hmac", "ESP-SHA384-HMAC"),
    ("esp-sha512-hmac", "ESP-SHA512-HMAC"),
    # GCM modes provide authentication natively; no separate HMAC needed.
    # Users should leave this blank when selecting GCM encryption.
    ("", "None (use with GCM encryption)"),
]


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

class IpsecTunnelForm(forms.Form):
    """Form for building an IKEv2 VTI IPsec tunnel on a Cisco IOS-XE device."""

    # ------------------------------------------------------------------ #
    # Device                                                               #
    # ------------------------------------------------------------------ #
    device = forms.ModelChoiceField(
        queryset=Device.objects.filter(platform__network_driver="cisco_ios").order_by("name"),
        label="Target Device",
        help_text="Select the IOS-XE device to configure. Only devices with the 'cisco_ios' platform driver are listed.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # ------------------------------------------------------------------ #
    # Tunnel interface                                                      #
    # ------------------------------------------------------------------ #
    tunnel_number = forms.IntegerField(
        label="Tunnel Interface Number",
        min_value=0,
        max_value=9999,
        help_text="Tunnel interface number (e.g. 100 → interface Tunnel100).",
        widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "100"}),
    )

    tunnel_source_interface = forms.CharField(
        label="Tunnel Source Interface",
        max_length=64,
        help_text="Local WAN interface that originates the tunnel (e.g. GigabitEthernet1).",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "GigabitEthernet1"}),
    )

    tunnel_ip_address = forms.CharField(
        label="Tunnel IP Address",
        max_length=18,
        help_text="IP address for the tunnel interface in CIDR notation (e.g. 10.255.0.1/30).",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "10.255.0.1/30"}),
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
    # IKEv2 settings                                                       #
    # ------------------------------------------------------------------ #
    ikev2_proposal_name = forms.CharField(
        label="IKEv2 Proposal Name",
        max_length=64,
        initial="IKEv2-PROPOSAL",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IKEv2-PROPOSAL"}),
    )

    ikev2_policy_name = forms.CharField(
        label="IKEv2 Policy Name",
        max_length=64,
        initial="IKEv2-POLICY",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IKEv2-POLICY"}),
    )

    ikev2_keyring_name = forms.CharField(
        label="IKEv2 Keyring Name",
        max_length=64,
        initial="IKEv2-KEYRING",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IKEv2-KEYRING"}),
    )

    ikev2_profile_name = forms.CharField(
        label="IKEv2 Profile Name",
        max_length=64,
        initial="IKEv2-PROFILE",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IKEv2-PROFILE"}),
    )

    ike_encryption = forms.ChoiceField(
        label="IKE Encryption Algorithm",
        choices=IKE_ENCRYPTION_CHOICES,
        initial="aes-cbc-256",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ike_integrity = forms.ChoiceField(
        label="IKE Integrity Algorithm",
        choices=IKE_INTEGRITY_CHOICES,
        initial="sha256",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ike_dh_group = forms.ChoiceField(
        label="IKE Diffie-Hellman Group",
        choices=IKE_DH_GROUP_CHOICES,
        initial="19",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    ike_lifetime = forms.IntegerField(
        label="IKE SA Lifetime (seconds)",
        min_value=300,
        max_value=86400,
        initial=86400,
        help_text="IKEv2 SA lifetime in seconds (300–86400). Default: 86400 (24 h).",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    # ------------------------------------------------------------------ #
    # IPsec settings                                                       #
    # ------------------------------------------------------------------ #
    ipsec_transform_set_name = forms.CharField(
        label="IPsec Transform-Set Name",
        max_length=64,
        initial="IPSEC-TS",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IPSEC-TS"}),
    )

    ipsec_profile_name = forms.CharField(
        label="IPsec Profile Name",
        max_length=64,
        initial="IPSEC-PROFILE",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "IPSEC-PROFILE"}),
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
    # Authentication                                                       #
    # ------------------------------------------------------------------ #
    pre_shared_key = forms.CharField(
        label="Pre-Shared Key",
        max_length=128,
        help_text="IKEv2 pre-shared key. This value is sent over SSH and stored only in the device running-config.",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "••••••••"},
            render_value=False,
        ),
    )

    # ------------------------------------------------------------------ #
    # Validation                                                           #
    # ------------------------------------------------------------------ #
    def clean_tunnel_ip_address(self):
        """Validate CIDR notation for the tunnel IP."""
        import ipaddress

        value = self.cleaned_data["tunnel_ip_address"]
        try:
            iface = ipaddress.IPv4Interface(value)
        except ValueError:
            raise forms.ValidationError(
                "Enter a valid IPv4 address in CIDR notation, e.g. 10.255.0.1/30."
            )
        return str(iface)

    def clean(self):
        """Cross-field validation."""
        cleaned = super().clean()
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
