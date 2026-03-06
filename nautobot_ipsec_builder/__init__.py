"""Nautobot IPsec Tunnel Builder App."""

__version__ = "0.1.0"

from nautobot.apps import NautobotAppConfig


class NautobotIpsecBuilderConfig(NautobotAppConfig):
    """Nautobot app configuration for IPsec Tunnel Builder."""

    name = "nautobot_ipsec_builder"
    verbose_name = "IPsec Tunnel Builder"
    description = "Build IKEv2 VTI IPsec tunnels on Cisco IOS-XE devices."
    version = __version__
    author = "NRTC Ops"
    author_email = ""
    base_url = "ipsec-builder"
    required_settings = []
    default_settings = {
        # Default SSH port for device connections
        "device_ssh_port": 22,
        # Connection timeout in seconds
        "connection_timeout": 30,
    }

    def ready(self):
        """App ready hook."""
        super().ready()


config = NautobotIpsecBuilderConfig
