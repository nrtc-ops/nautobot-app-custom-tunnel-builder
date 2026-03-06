"""Nautobot Job: Build IKEv2 VTI IPsec tunnel on a Cisco IOS-XE device."""

import ipaddress
import logging
import traceback

from nautobot.extras.jobs import Job, ObjectVar, StringVar, IntegerVar, ChoiceVar, IPAddressVar
from nautobot.dcim.models import Device

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Choices – must mirror forms.py so the Job can also be run from the
# Nautobot Jobs UI directly.
# ---------------------------------------------------------------------------

IKE_ENCRYPTION_CHOICES = (
    ("aes-cbc-128", "AES-CBC-128"),
    ("aes-cbc-256", "AES-CBC-256 (Recommended)"),
    ("aes-gcm-128", "AES-GCM-128"),
    ("aes-gcm-256", "AES-GCM-256"),
)

IKE_INTEGRITY_CHOICES = (
    ("sha256", "SHA-256 (Recommended)"),
    ("sha384", "SHA-384"),
    ("sha512", "SHA-512"),
)

IKE_DH_GROUP_CHOICES = (
    ("14", "Group 14 - 2048-bit MODP"),
    ("19", "Group 19 - 256-bit ECP (Recommended)"),
    ("20", "Group 20 - 384-bit ECP"),
    ("21", "Group 21 - 521-bit ECP"),
)

IPSEC_ENCRYPTION_CHOICES = (
    ("esp-aes 128", "ESP-AES-128"),
    ("esp-aes 256", "ESP-AES-256 (Recommended)"),
    ("esp-gcm 128", "ESP-GCM-128"),
    ("esp-gcm 256", "ESP-GCM-256"),
)

IPSEC_INTEGRITY_CHOICES = (
    ("esp-sha256-hmac", "ESP-SHA256-HMAC (Recommended)"),
    ("esp-sha384-hmac", "ESP-SHA384-HMAC"),
    ("esp-sha512-hmac", "ESP-SHA512-HMAC"),
    ("", "None (use with GCM encryption)"),
)


# ---------------------------------------------------------------------------
# Config builder helper
# ---------------------------------------------------------------------------

def _cidr_to_ip_mask(cidr: str) -> tuple[str, str]:
    """Convert '10.255.0.1/30' → ('10.255.0.1', '255.255.255.252')."""
    iface = ipaddress.IPv4Interface(cidr)
    return str(iface.ip), str(iface.netmask)


def build_iosxe_ipsec_config(data: dict) -> list[str]:
    """
    Generate an ordered list of IOS-XE configuration commands for an
    IKEv2 Virtual Tunnel Interface (VTI) IPsec tunnel.

    Returns a list of strings ready to pass to Netmiko's
    ``send_config_set()``.
    """
    tunnel_ip, tunnel_mask = _cidr_to_ip_mask(data["tunnel_ip_address"])
    remote_peer = data["remote_peer_ip"]
    psk = data["pre_shared_key"]

    # IKEv2 transforms string varies by algorithm family
    ike_enc = data["ike_encryption"]
    ike_integ = data["ike_integrity"]
    ike_group = data["ike_dh_group"]
    ike_lifetime = data["ike_lifetime"]

    ipsec_enc = data["ipsec_encryption"]
    ipsec_integ = data.get("ipsec_integrity", "")
    ipsec_lifetime = data["ipsec_lifetime"]

    proposal_name = data["ikev2_proposal_name"]
    policy_name = data["ikev2_policy_name"]
    keyring_name = data["ikev2_keyring_name"]
    profile_name = data["ikev2_profile_name"]
    ts_name = data["ipsec_transform_set_name"]
    ipsec_prof_name = data["ipsec_profile_name"]

    tunnel_num = data["tunnel_number"]
    tunnel_src = data["tunnel_source_interface"]

    commands = []

    # ------------------------------------------------------------------ #
    # IKEv2 Proposal                                                       #
    # ------------------------------------------------------------------ #
    commands.append(f"crypto ikev2 proposal {proposal_name}")
    commands.append(f" encryption {ike_enc}")
    commands.append(f" integrity {ike_integ}")
    commands.append(f" group {ike_group}")

    # ------------------------------------------------------------------ #
    # IKEv2 Policy                                                         #
    # ------------------------------------------------------------------ #
    commands.append(f"crypto ikev2 policy {policy_name}")
    commands.append(f" proposal {proposal_name}")

    # ------------------------------------------------------------------ #
    # IKEv2 Keyring                                                        #
    # ------------------------------------------------------------------ #
    # Derive a peer name from the remote IP (dots → underscores)
    peer_name = f"PEER_{remote_peer.replace('.', '_')}"
    commands.append(f"crypto ikev2 keyring {keyring_name}")
    commands.append(f" peer {peer_name}")
    commands.append(f"  address {remote_peer}")
    commands.append(f"  pre-shared-key local {psk}")
    commands.append(f"  pre-shared-key remote {psk}")

    # ------------------------------------------------------------------ #
    # IKEv2 Profile                                                        #
    # ------------------------------------------------------------------ #
    commands.append(f"crypto ikev2 profile {profile_name}")
    commands.append(f" match identity remote address {remote_peer} 255.255.255.255")
    commands.append(" authentication local pre-share")
    commands.append(" authentication remote pre-share")
    commands.append(f" keyring local {keyring_name}")
    commands.append(f" lifetime {ike_lifetime}")

    # ------------------------------------------------------------------ #
    # IPsec Transform-Set                                                  #
    # ------------------------------------------------------------------ #
    if ipsec_integ:
        commands.append(f"crypto ipsec transform-set {ts_name} {ipsec_enc} {ipsec_integ}")
    else:
        # GCM – no separate integrity algorithm
        commands.append(f"crypto ipsec transform-set {ts_name} {ipsec_enc}")
    commands.append(" mode tunnel")

    # ------------------------------------------------------------------ #
    # IPsec Profile                                                        #
    # ------------------------------------------------------------------ #
    commands.append(f"crypto ipsec profile {ipsec_prof_name}")
    commands.append(f" set transform-set {ts_name}")
    commands.append(f" set ikev2-profile {profile_name}")
    commands.append(f" set security-association lifetime seconds {ipsec_lifetime}")

    # ------------------------------------------------------------------ #
    # Tunnel Interface                                                     #
    # ------------------------------------------------------------------ #
    commands.append(f"interface Tunnel{tunnel_num}")
    commands.append(f" ip address {tunnel_ip} {tunnel_mask}")
    commands.append(f" tunnel source {tunnel_src}")
    commands.append(f" tunnel destination {remote_peer}")
    commands.append(" tunnel mode ipsec ipv4")
    commands.append(f" tunnel protection ipsec profile {ipsec_prof_name}")
    commands.append(" no shutdown")

    return commands


# ---------------------------------------------------------------------------
# Nautobot Job
# ---------------------------------------------------------------------------

class BuildIpsecTunnel(Job):
    """
    Build an IKEv2 VTI IPsec tunnel on a Cisco IOS-XE device.

    This Job connects to the selected device over SSH using Netmiko and
    pushes the generated configuration.  It can be run directly from the
    Nautobot Jobs UI or dispatched programmatically by the IPsec Tunnel
    Builder custom view.
    """

    class Meta:
        name = "Build IKEv2 IPsec Tunnel (IOS-XE)"
        description = (
            "Generates and pushes an IKEv2 Virtual Tunnel Interface (VTI) "
            "IPsec configuration to a Cisco IOS-XE device."
        )
        label = "Build IPsec Tunnel"
        commit_default = True
        has_sensitive_variables = True  # contains the PSK

    # ------------------------------------------------------------------ #
    # Job variables (shown in the Nautobot Jobs UI)                       #
    # ------------------------------------------------------------------ #
    device = ObjectVar(
        model=Device,
        description="Target IOS-XE device.",
        label="Target Device",
    )

    tunnel_number = IntegerVar(
        description="Tunnel interface number (e.g. 100 → interface Tunnel100).",
        label="Tunnel Interface Number",
        min_value=0,
        max_value=9999,
        default=100,
    )

    tunnel_source_interface = StringVar(
        description="Local WAN interface name (e.g. GigabitEthernet1).",
        label="Tunnel Source Interface",
        max_length=64,
        default="GigabitEthernet1",
    )

    tunnel_ip_address = StringVar(
        description="Tunnel IP in CIDR notation (e.g. 10.255.0.1/30).",
        label="Tunnel IP Address (CIDR)",
        max_length=18,
    )

    remote_peer_ip = StringVar(
        description="Public IP of the remote IPsec peer.",
        label="Remote Peer IP",
        max_length=15,
    )

    # IKEv2
    ikev2_proposal_name = StringVar(label="IKEv2 Proposal Name", default="IKEv2-PROPOSAL", max_length=64)
    ikev2_policy_name = StringVar(label="IKEv2 Policy Name", default="IKEv2-POLICY", max_length=64)
    ikev2_keyring_name = StringVar(label="IKEv2 Keyring Name", default="IKEv2-KEYRING", max_length=64)
    ikev2_profile_name = StringVar(label="IKEv2 Profile Name", default="IKEv2-PROFILE", max_length=64)

    ike_encryption = ChoiceVar(
        label="IKE Encryption",
        choices=IKE_ENCRYPTION_CHOICES,
        default="aes-cbc-256",
    )
    ike_integrity = ChoiceVar(
        label="IKE Integrity",
        choices=IKE_INTEGRITY_CHOICES,
        default="sha256",
    )
    ike_dh_group = ChoiceVar(
        label="IKE DH Group",
        choices=IKE_DH_GROUP_CHOICES,
        default="19",
    )
    ike_lifetime = IntegerVar(label="IKE SA Lifetime (s)", default=86400, min_value=300, max_value=86400)

    # IPsec
    ipsec_transform_set_name = StringVar(label="Transform-Set Name", default="IPSEC-TS", max_length=64)
    ipsec_profile_name = StringVar(label="IPsec Profile Name", default="IPSEC-PROFILE", max_length=64)

    ipsec_encryption = ChoiceVar(
        label="IPsec Encryption",
        choices=IPSEC_ENCRYPTION_CHOICES,
        default="esp-aes 256",
    )
    ipsec_integrity = ChoiceVar(
        label="IPsec Integrity",
        choices=IPSEC_INTEGRITY_CHOICES,
        default="esp-sha256-hmac",
    )
    ipsec_lifetime = IntegerVar(label="IPsec SA Lifetime (s)", default=3600, min_value=120, max_value=86400)

    # PSK – treated as sensitive; Nautobot will not log it.
    pre_shared_key = StringVar(
        label="Pre-Shared Key",
        description="IKEv2 pre-shared key.",
        max_length=128,
    )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _get_management_ip(self, device: Device) -> str:
        """Return the device's primary IP as a plain string (no prefix length)."""
        if not device.primary_ip:
            raise ValueError(
                f"Device '{device.name}' has no primary IP configured in Nautobot. "
                "Set a primary IPv4 address before running this job."
            )
        return str(device.primary_ip.address.ip)

    def _get_netmiko_platform(self, device: Device) -> str:
        """Map the Nautobot platform network driver to a Netmiko device_type."""
        platform_map = {
            "cisco_ios": "cisco_ios",
            "cisco_xe": "cisco_xe",
            "cisco_iosxe": "cisco_xe",
        }
        driver = ""
        if device.platform:
            driver = (device.platform.network_driver or "").lower()
        return platform_map.get(driver, "cisco_ios")

    # ------------------------------------------------------------------ #
    # Main run method                                                      #
    # ------------------------------------------------------------------ #

    def run(self, device, tunnel_number, tunnel_source_interface, tunnel_ip_address,
            remote_peer_ip, ikev2_proposal_name, ikev2_policy_name, ikev2_keyring_name,
            ikev2_profile_name, ike_encryption, ike_integrity, ike_dh_group, ike_lifetime,
            ipsec_transform_set_name, ipsec_profile_name, ipsec_encryption, ipsec_integrity,
            ipsec_lifetime, pre_shared_key):
        """Execute the IPsec tunnel build."""

        # ---------------------------------------------------------------- #
        # 1. Build configuration commands                                   #
        # ---------------------------------------------------------------- #
        self.logger.info("Generating IOS-XE configuration for device '%s'.", device.name)

        job_data = {
            "tunnel_number": tunnel_number,
            "tunnel_source_interface": tunnel_source_interface,
            "tunnel_ip_address": tunnel_ip_address,
            "remote_peer_ip": remote_peer_ip,
            "ikev2_proposal_name": ikev2_proposal_name,
            "ikev2_policy_name": ikev2_policy_name,
            "ikev2_keyring_name": ikev2_keyring_name,
            "ikev2_profile_name": ikev2_profile_name,
            "ike_encryption": ike_encryption,
            "ike_integrity": ike_integrity,
            "ike_dh_group": ike_dh_group,
            "ike_lifetime": ike_lifetime,
            "ipsec_transform_set_name": ipsec_transform_set_name,
            "ipsec_profile_name": ipsec_profile_name,
            "ipsec_encryption": ipsec_encryption,
            "ipsec_integrity": ipsec_integrity,
            "ipsec_lifetime": ipsec_lifetime,
            "pre_shared_key": pre_shared_key,
        }

        commands = build_iosxe_ipsec_config(job_data)

        self.logger.info(
            "Generated %d configuration lines for Tunnel%s → %s.",
            len(commands),
            tunnel_number,
            remote_peer_ip,
        )

        # Log config (redact PSK)
        redacted = [
            line.replace(pre_shared_key, "***REDACTED***") if pre_shared_key in line else line
            for line in commands
        ]
        self.logger.debug("Configuration preview:\n%s", "\n".join(redacted))

        # ---------------------------------------------------------------- #
        # 2. Connect to device and push config                             #
        # ---------------------------------------------------------------- #
        mgmt_ip = self._get_management_ip(device)
        device_type = self._get_netmiko_platform(device)

        self.logger.info(
            "Connecting to %s (%s) via SSH as device_type='%s'.",
            device.name,
            mgmt_ip,
            device_type,
        )

        try:
            from netmiko import ConnectHandler
            from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException
        except ImportError:
            self.logger.error(
                "Netmiko is not installed. Install it with: pip install netmiko"
            )
            raise

        # Netmiko device dictionary.
        # Credentials: pull from environment variables or a secrets backend.
        # Nautobot 3.x SecretsGroup integration can be added here.
        import os

        device_params = {
            "device_type": device_type,
            "host": mgmt_ip,
            "username": os.environ.get("NAUTOBOT_DEVICE_USERNAME", "admin"),
            "password": os.environ.get("NAUTOBOT_DEVICE_PASSWORD", ""),
            "secret": os.environ.get("NAUTOBOT_DEVICE_ENABLE_SECRET", ""),
            "port": int(os.environ.get("NAUTOBOT_DEVICE_SSH_PORT", 22)),
            "timeout": 30,
            "session_log": None,  # Avoids logging PSK to session file
        }

        try:
            with ConnectHandler(**device_params) as conn:
                if device_params.get("secret"):
                    conn.enable()

                self.logger.info("Connected. Pushing %d commands.", len(commands))
                output = conn.send_config_set(commands, cmd_verify=False)
                self.logger.info("Configuration output:\n%s", output)

                # Save running config to startup
                conn.save_config()
                self.logger.info("Running configuration saved to startup-config.")

        except Exception as exc:
            self.logger.error(
                "Failed to configure %s: %s\n%s",
                device.name,
                exc,
                traceback.format_exc(),
            )
            raise

        self.logger.info(
            "IPsec tunnel Tunnel%s successfully built on %s.",
            tunnel_number,
            device.name,
        )

        return (
            f"IPsec tunnel Tunnel{tunnel_number} ↔ {remote_peer_ip} "
            f"configured on {device.name} ({mgmt_ip})."
        )
