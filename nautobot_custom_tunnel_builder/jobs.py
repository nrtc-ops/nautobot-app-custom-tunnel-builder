"""Nautobot Job: Build policy-based IPsec tunnel (IKEv1 or IKEv2) on a Cisco IOS-XE device."""

import ipaddress
import logging
import os
import traceback

from netmiko import ConnectHandler
from nautobot.apps.jobs import ChoiceVar, IntegerVar, Job, ObjectVar, StringVar, register_jobs
from nautobot.dcim.models import Device

from .constants import (
    IKE_DH_GROUP_CHOICES,
    IKE_VERSION_CHOICES,
    IKEV1_ENCRYPTION_CHOICES,
    IKEV1_HASH_CHOICES,
    IKEV2_ENCRYPTION_CHOICES,
    IKEV2_INTEGRITY_CHOICES,
    IPSEC_ENCRYPTION_CHOICES,
    IPSEC_INTEGRITY_CHOICES,
)

logger = logging.getLogger(__name__)

name = "NRTC Tunnel Builders"  # pylint: disable=invalid-name


# ---------------------------------------------------------------------------
# Helper: CIDR → (network_address, wildcard_mask)
# ---------------------------------------------------------------------------


def _cidr_to_net_wildcard(cidr: str) -> tuple[str, str]:
    """Convert '192.168.1.0/24' → ('192.168.1.0', '0.0.0.255')."""
    net = ipaddress.IPv4Network(cidr, strict=False)
    wildcard = str(ipaddress.IPv4Address(int(net.hostmask)))
    return str(net.network_address), wildcard


# ---------------------------------------------------------------------------
# Phase 1 config builders
# ---------------------------------------------------------------------------


def _build_ikev1_commands(data: dict) -> list[str]:
    """Build IKEv1 (ISAKMP) Phase 1 configuration commands."""
    priority = data["isakmp_policy_priority"]
    remote_peer = data["remote_peer_ip"]
    psk = data["pre_shared_key"]

    return [
        f"crypto isakmp policy {priority}",
        f" encr {data['ikev1_encryption']}",
        f" hash {data['ikev1_hash']}",
        " authentication pre-share",
        f" group {data['ike_dh_group']}",
        f" lifetime {data['ike_lifetime']}",
        f"crypto isakmp key {psk} address {remote_peer}",
    ]


def _build_ikev2_commands(data: dict) -> list[str]:
    """Build IKEv2 Phase 1 configuration commands."""
    remote_peer = data["remote_peer_ip"]
    psk = data["pre_shared_key"]
    peer_name = f"PEER_{remote_peer.replace('.', '_')}"

    return [
        f"crypto ikev2 proposal {data['ikev2_proposal_name']}",
        f" encryption {data['ikev2_encryption']}",
        f" integrity {data['ikev2_integrity']}",
        f" group {data['ike_dh_group']}",
        f"crypto ikev2 policy {data['ikev2_policy_name']}",
        f" proposal {data['ikev2_proposal_name']}",
        f"crypto ikev2 keyring {data['ikev2_keyring_name']}",
        f" peer {peer_name}",
        f"  address {remote_peer}",
        f"  pre-shared-key local {psk}",
        f"  pre-shared-key remote {psk}",
        f"crypto ikev2 profile {data['ikev2_profile_name']}",
        f" match identity remote address {remote_peer} 255.255.255.255",
        " authentication local pre-share",
        " authentication remote pre-share",
        f" keyring local {data['ikev2_keyring_name']}",
        f" lifetime {data['ike_lifetime']}",
    ]


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------


def build_iosxe_policy_config(data: dict) -> list[str]:
    """Build Router Config.

    Build a list of IOS-XE configuration commands to create a policy-based
    IPsec tunnel based on the provided data dictionary.
    """
    ike_version = data["ike_version"]
    remote_peer = data["remote_peer_ip"]
    map_name = data["crypto_map_name"]
    map_seq = data["crypto_map_sequence"]
    acl_name = data["crypto_acl_name"]
    ts_name = data["ipsec_transform_set_name"]
    ipsec_enc = data["ipsec_encryption"]
    ipsec_integ = data.get("ipsec_integrity", "")
    ipsec_lifetime = data["ipsec_lifetime"]

    local_net, local_wildcard = _cidr_to_net_wildcard(data["local_network"])
    remote_net, remote_wildcard = _cidr_to_net_wildcard(data["remote_network"])

    # Phase 1: IKEv1 (ISAKMP) or IKEv2
    if ike_version == "ikev1":
        commands = _build_ikev1_commands(data)
    else:
        commands = _build_ikev2_commands(data)

    # Crypto ACL (interesting traffic)
    commands.append(f"ip access-list extended {acl_name}")
    commands.append(f" permit ip {local_net} {local_wildcard} {remote_net} {remote_wildcard}")

    # IPsec Transform-Set (Phase 2)
    if ipsec_integ:
        commands.append(f"crypto ipsec transform-set {ts_name} {ipsec_enc} {ipsec_integ}")
    else:
        # GCM — no separate integrity algorithm
        commands.append(f"crypto ipsec transform-set {ts_name} {ipsec_enc}")
    commands.append(" mode tunnel")

    # Crypto Map
    commands.append(f"crypto map {map_name} {map_seq} ipsec-isakmp")
    commands.append(f" set peer {remote_peer}")
    commands.append(f" set transform-set {ts_name}")
    commands.append(f" set security-association lifetime seconds {ipsec_lifetime}")
    if ike_version == "ikev2":
        commands.append(f" set ikev2-profile {data['ikev2_profile_name']}")
    commands.append(f" match address {acl_name}")

    # Apply crypto map to WAN interface
    commands.append(f"interface {data['wan_interface']}")
    commands.append(f" crypto map {map_name}")

    return commands


# ---------------------------------------------------------------------------
# Nautobot Job
# ---------------------------------------------------------------------------


class BuildIpsecTunnel(Job):
    """

    Build a policy-based IPsec tunnel on a Cisco IOS-XE device.

    Supports both IKEv1 (ISAKMP) and IKEv2. Connects to the selected device
    over SSH using Netmiko, pushes the generated configuration, and saves the
    running config to startup-config.

    """

    class Meta:  # pylint: disable=too-few-public-methods
        """Meta attributes for the Job."""

        name = "Build Policy-Based IPsec Tunnel (IOS-XE)"
        description = (
            "Generates and pushes a policy-based IKEv1 or IKEv2 IPsec" " configuration to a Cisco IOS-XE device."
        )
        label = "Build IPsec Tunnel"
        commit_default = True
        has_sensitive_variables = True  # contains the PSK

    # ------------------------------------------------------------------ #
    # Job variables                                                        #
    # ------------------------------------------------------------------ #

    device = ObjectVar(
        model=Device,
        description="Target IOS-XE device.",
        label="Target Device",
    )

    ike_version = ChoiceVar(
        label="IKE Version",
        choices=IKE_VERSION_CHOICES,
        default="ikev2",
    )

    remote_peer_ip = StringVar(
        description="Public IP of the remote IPsec peer.",
        label="Remote Peer IP",
        max_length=15,
    )

    # Interesting traffic
    local_network = StringVar(
        description="Local subnet to encrypt in CIDR notation (e.g. 192.168.1.0/24).",
        label="Local Network (CIDR)",
        max_length=18,
    )

    remote_network = StringVar(
        description="Remote subnet to encrypt in CIDR notation (e.g. 10.0.0.0/24).",
        label="Remote Network (CIDR)",
        max_length=18,
    )

    crypto_acl_name = StringVar(
        label="Crypto ACL Name",
        default="VPN-ACL",
        max_length=64,
    )

    # Crypto map
    wan_interface = StringVar(
        description="Physical interface where the crypto map is applied (e.g. GigabitEthernet1).",
        label="WAN Interface",
        default="GigabitEthernet1",
        max_length=64,
    )

    crypto_map_name = StringVar(
        label="Crypto Map Name",
        default="CRYPTO-MAP",
        max_length=64,
    )

    crypto_map_sequence = IntegerVar(
        label="Crypto Map Sequence",
        default=10,
        min_value=1,
        max_value=65535,
    )

    # Shared IKE
    ike_dh_group = ChoiceVar(
        label="IKE DH Group",
        choices=IKE_DH_GROUP_CHOICES,
        default="19",
    )

    ike_lifetime = IntegerVar(
        label="IKE SA Lifetime (s)",
        default=86400,
        min_value=300,
        max_value=86400,
    )

    # IKEv1
    isakmp_policy_priority = IntegerVar(
        label="ISAKMP Policy Priority (IKEv1)",
        default=10,
        min_value=1,
        max_value=10000,
        required=False,
    )

    ikev1_encryption = ChoiceVar(
        label="ISAKMP Encryption (IKEv1)",
        choices=IKEV1_ENCRYPTION_CHOICES,
        default="aes 256",
        required=False,
    )

    ikev1_hash = ChoiceVar(
        label="ISAKMP Hash (IKEv1)",
        choices=IKEV1_HASH_CHOICES,
        default="sha256",
        required=False,
    )

    # IKEv2
    ikev2_proposal_name = StringVar(
        label="IKEv2 Proposal Name",
        default="IKEv2-PROPOSAL",
        max_length=64,
        required=False,
    )

    ikev2_policy_name = StringVar(
        label="IKEv2 Policy Name",
        default="IKEv2-POLICY",
        max_length=64,
        required=False,
    )

    ikev2_keyring_name = StringVar(
        label="IKEv2 Keyring Name",
        default="IKEv2-KEYRING",
        max_length=64,
        required=False,
    )

    ikev2_profile_name = StringVar(
        label="IKEv2 Profile Name",
        default="IKEv2-PROFILE",
        max_length=64,
        required=False,
    )

    ikev2_encryption = ChoiceVar(
        label="IKEv2 Encryption",
        choices=IKEV2_ENCRYPTION_CHOICES,
        default="aes-cbc-256",
        required=False,
    )

    ikev2_integrity = ChoiceVar(
        label="IKEv2 Integrity",
        choices=IKEV2_INTEGRITY_CHOICES,
        default="sha256",
        required=False,
    )

    # PSK — treated as sensitive; Nautobot will not log it.
    pre_shared_key = StringVar(
        label="Pre-Shared Key",
        description="IKE pre-shared key.",
        max_length=128,
    )

    # IPsec Phase 2
    ipsec_transform_set_name = StringVar(
        label="Transform-Set Name",
        default="IPSEC-TS",
        max_length=64,
    )

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

    ipsec_lifetime = IntegerVar(
        label="IPsec SA Lifetime (s)",
        default=3600,
        min_value=120,
        max_value=86400,
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

    def run(  # pylint: disable=arguments-differ,too-many-arguments,too-many-locals
        self,
        device,
        ike_version,
        remote_peer_ip,
        local_network,
        remote_network,
        crypto_acl_name,
        wan_interface,
        crypto_map_name,
        crypto_map_sequence,
        ike_dh_group,
        ike_lifetime,
        isakmp_policy_priority,
        ikev1_encryption,
        ikev1_hash,
        ikev2_proposal_name,
        ikev2_policy_name,
        ikev2_keyring_name,
        ikev2_profile_name,
        ikev2_encryption,
        ikev2_integrity,
        pre_shared_key,
        ipsec_transform_set_name,
        ipsec_encryption,
        ipsec_integrity,
        ipsec_lifetime,
    ):
        """Execute the policy-based IPsec tunnel build."""
        # ---------------------------------------------------------------- #
        # 1. Build configuration commands                                   #
        # ---------------------------------------------------------------- #
        self.logger.info(
            "Generating IOS-XE %s policy-based IPsec configuration for device '%s'.",
            ike_version.upper(),
            device.name,
        )

        job_data = {
            "ike_version": ike_version,
            "remote_peer_ip": remote_peer_ip,
            "local_network": local_network,
            "remote_network": remote_network,
            "crypto_acl_name": crypto_acl_name,
            "wan_interface": wan_interface,
            "crypto_map_name": crypto_map_name,
            "crypto_map_sequence": crypto_map_sequence,
            "ike_dh_group": ike_dh_group,
            "ike_lifetime": ike_lifetime,
            "isakmp_policy_priority": isakmp_policy_priority,
            "ikev1_encryption": ikev1_encryption,
            "ikev1_hash": ikev1_hash,
            "ikev2_proposal_name": ikev2_proposal_name,
            "ikev2_policy_name": ikev2_policy_name,
            "ikev2_keyring_name": ikev2_keyring_name,
            "ikev2_profile_name": ikev2_profile_name,
            "ikev2_encryption": ikev2_encryption,
            "ikev2_integrity": ikev2_integrity,
            "pre_shared_key": pre_shared_key,
            "ipsec_transform_set_name": ipsec_transform_set_name,
            "ipsec_encryption": ipsec_encryption,
            "ipsec_integrity": ipsec_integrity,
            "ipsec_lifetime": ipsec_lifetime,
        }

        commands = build_iosxe_policy_config(job_data)

        self.logger.info(
            "Generated %d configuration lines for %s IPsec → peer %s.",
            len(commands),
            ike_version.upper(),
            remote_peer_ip,
        )

        # Log config (redact PSK)
        redacted = [
            line.replace(pre_shared_key, "***REDACTED***") if pre_shared_key in line else line for line in commands
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
            "%s policy-based IPsec tunnel to %s successfully configured on %s.",
            ike_version.upper(),
            remote_peer_ip,
            device.name,
        )

        return (
            f"{ike_version.upper()} policy-based IPsec tunnel to {remote_peer_ip} "
            f"configured on {device.name} ({mgmt_ip})."
        )


register_jobs(BuildIpsecTunnel)
