"""DRF serializers for the portal API."""

import ipaddress
import re

from nautobot.vpn.models import VPNProfile
from rest_framework import serializers

from ..constants import get_iosxe_device_queryset

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _validate_cidr(value, field_label):
    """Validate that a value is a valid IPv4 CIDR network."""
    try:
        net = ipaddress.IPv4Network(value, strict=False)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
        raise serializers.ValidationError(
            f"Enter a valid IPv4 network in CIDR notation for {field_label}, e.g. 192.168.1.0/24."
        ) from exc
    return str(net)


class PortalTunnelRequestSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Validate a portal tunnel provisioning request."""

    member_name = serializers.CharField(
        max_length=128,
        help_text="Member slug identifier (lowercase, hyphens, e.g. 'acme-corp').",
    )

    member_display_name = serializers.CharField(
        max_length=256,
        help_text="Human-friendly member name (e.g. 'Acme Corp').",
    )

    location_city = serializers.CharField(
        max_length=128,
        help_text="City name for the member location (e.g. 'Jackson').",
    )

    location_state = serializers.CharField(
        max_length=2,
        help_text="Two-letter state abbreviation (e.g. 'MS').",
    )

    device = serializers.PrimaryKeyRelatedField(
        queryset=get_iosxe_device_queryset(),
        help_text="UUID of the target IOS-XE concentrator device.",
    )

    template_vpn_profile = serializers.PrimaryKeyRelatedField(
        queryset=VPNProfile.objects.all(),
        help_text="UUID of the template VPN profile to clone.",
    )

    remote_peer_ip = serializers.IPAddressField(
        protocol="IPv4",
        help_text="Public IP address of the member's VPN endpoint.",
    )

    member_protected_prefixes = serializers.ListField(
        child=serializers.CharField(max_length=18),
        allow_empty=False,
        help_text="Member's protected networks in CIDR notation (e.g. ['192.168.1.0/24', '10.0.0.0/8']).",
    )

    def validate_member_name(self, value):
        """Validate member_name is a valid slug."""
        if not _SLUG_RE.match(value):
            raise serializers.ValidationError(
                "Must be lowercase letters, numbers, and hyphens only (e.g. 'acme-corp')."
            )
        return value

    def validate_location_state(self, value):
        """Validate state is a two-letter uppercase abbreviation."""
        value = value.upper()
        if not re.match(r"^[A-Z]{2}$", value):
            raise serializers.ValidationError("Enter a two-letter state abbreviation (e.g. 'MS').")
        return value

    def validate_member_protected_prefixes(self, value):
        """Validate each entry is a valid IPv4 CIDR."""
        return [_validate_cidr(v, "member protected prefix") for v in value]

    def validate_device(self, value):
        """Ensure the device has a primary IP for SSH connectivity."""
        if not value.primary_ip:
            raise serializers.ValidationError(
                f"Device '{value.name}' has no primary IP configured. "
                "Set a primary IPv4 address before requesting a tunnel."
            )
        return value
