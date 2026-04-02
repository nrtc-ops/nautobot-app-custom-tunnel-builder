"""DRF serializers for the portal API."""

import ipaddress

from nautobot.vpn.models import VPNProfile
from rest_framework import serializers

from ..constants import get_iosxe_device_queryset


class PortalTunnelRequestSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Validate a portal tunnel provisioning request."""

    vpn_profile = serializers.PrimaryKeyRelatedField(
        queryset=VPNProfile.objects.all(),
        help_text="UUID of the VPN profile to apply.",
    )

    device = serializers.PrimaryKeyRelatedField(
        queryset=get_iosxe_device_queryset(),
        help_text="UUID of the target IOS-XE device.",
    )

    remote_peer_ip = serializers.IPAddressField(
        protocol="IPv4",
        help_text="Public IP address of the remote IPsec peer.",
    )

    local_network_cidr = serializers.CharField(
        max_length=18,
        help_text="Local subnet to encrypt in CIDR notation (e.g. 192.168.1.0/24).",
    )

    protected_network_cidr = serializers.CharField(
        max_length=18,
        help_text="Remote (protected) subnet in CIDR notation (e.g. 10.0.0.0/24).",
    )

    def validate_local_network_cidr(self, value):
        """Validate that the value is a valid IPv4 CIDR network."""
        try:
            net = ipaddress.IPv4Network(value, strict=False)
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
            raise serializers.ValidationError(
                "Enter a valid IPv4 network in CIDR notation, e.g. 192.168.1.0/24."
            ) from exc
        return str(net)

    def validate_protected_network_cidr(self, value):
        """Validate that the value is a valid IPv4 CIDR network."""
        try:
            net = ipaddress.IPv4Network(value, strict=False)
        except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError) as exc:
            raise serializers.ValidationError("Enter a valid IPv4 network in CIDR notation, e.g. 10.0.0.0/24.") from exc
        return str(net)

    def validate_device(self, value):
        """Ensure the device has a primary IP for SSH connectivity."""
        if not value.primary_ip:
            raise serializers.ValidationError(
                f"Device '{value.name}' has no primary IP configured. "
                "Set a primary IPv4 address before requesting a tunnel."
            )
        return value
