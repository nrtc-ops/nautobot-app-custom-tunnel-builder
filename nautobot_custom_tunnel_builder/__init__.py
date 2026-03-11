"""Nautobot Custom Tunnel Builder App."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as get_version

from nautobot.apps import NautobotAppConfig

try:
    __version__ = get_version("nautobot-custom-tunnel-builder")
except PackageNotFoundError:
    # Fallback version when package metadata is unavailable (e.g., running from source)
    __version__ = "0.0.0"


class NautobotCustomTunnelBuilderConfig(NautobotAppConfig):
    """Nautobot app configuration for Custom Tunnel Builder."""

    name = "nautobot_custom_tunnel_builder"
    verbose_name = "Custom Tunnel Builder"
    description = "Build policy-based IPsec tunnels (IKEv1/IKEv2) on Cisco IOS-XE devices."
    version = __version__
    author = "NRTC Ops"
    author_email = ""
    base_url = "tunnel-builder"
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
        # Explicitly import jobs so Nautobot registers them during migrate.
        from . import jobs  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import


config = NautobotCustomTunnelBuilderConfig  # pylint: disable=invalid-name
