"""Map VPNProfile objects to build_iosxe_policy_config() input parameters."""

from .constants import (
    NAUTOBOT_TO_IOSXE_IKE_VERSION,
    NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_IKEV1_HASH,
    NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY,
    NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION,
    NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY,
)

# Phase 2 encryption algorithms that provide built-in authentication (no HMAC needed)
_GCM_PHASE2_ALGORITHMS = {"esp-gcm 256", "esp-gcm 128"}


def profile_to_config_params(
    vpn_profile,
    remote_peer_ip: str,
    local_network_cidr: str,
    protected_network_cidr: str,
    crypto_map_name: str,
    sequence: int,
) -> dict:
    """Translate a VPNProfile + request params into a dict for build_iosxe_policy_config().

    Args:
        vpn_profile: Nautobot VPNProfile model instance.
        remote_peer_ip: Remote peer IP address.
        local_network_cidr: Local network in CIDR notation.
        protected_network_cidr: Remote (protected) network in CIDR notation.
        crypto_map_name: Name of the existing crypto map on the device.
        sequence: Crypto map sequence number for this tunnel.

    Returns:
        Dict compatible with build_iosxe_policy_config().

    Raises:
        ValueError: If the profile has no Phase 1 or Phase 2 policy assignment.
        KeyError: If an algorithm value has no IOS-XE translation.
    """
    p1_assignment = vpn_profile.vpnprofilephase1policyassignment_set.order_by("weight").first()
    if not p1_assignment:
        raise ValueError(f"VPNProfile '{vpn_profile}' has no Phase 1 policy assignment.")

    p2_assignment = vpn_profile.vpnprofilephase2policyassignment_set.order_by("weight").first()
    if not p2_assignment:
        raise ValueError(f"VPNProfile '{vpn_profile}' has no Phase 2 policy assignment.")

    phase1 = p1_assignment.vpn_phase1_policy
    phase2 = p2_assignment.vpn_phase2_policy

    ike_version = NAUTOBOT_TO_IOSXE_IKE_VERSION[phase1.ike_version]

    # Phase 2 (IPsec)
    ipsec_enc = NAUTOBOT_TO_IOSXE_PHASE2_ENCRYPTION[phase2.encryption_algorithm[0]]
    ipsec_integ = "" if ipsec_enc in _GCM_PHASE2_ALGORITHMS else NAUTOBOT_TO_IOSXE_PHASE2_INTEGRITY[phase2.integrity_algorithm[0]]

    params = {
        "ike_version": ike_version,
        "remote_peer_ip": remote_peer_ip,
        "local_network": local_network_cidr,
        "remote_network": protected_network_cidr,
        "crypto_map_name": crypto_map_name,
        "crypto_map_sequence": sequence,
        "crypto_acl_name": f"PORTAL-ACL-{sequence}",
        "ipsec_transform_set_name": f"PORTAL-TS-{sequence}",
        "ike_dh_group": phase1.dh_group[0],
        "ike_lifetime": phase1.lifetime_seconds,
        "ipsec_encryption": ipsec_enc,
        "ipsec_integrity": ipsec_integ,
        "ipsec_lifetime": phase2.lifetime,
        "pre_shared_key": "",  # Populated by caller
    }

    if ike_version == "ikev2":
        params.update({
            "ikev2_encryption": NAUTOBOT_TO_IOSXE_PHASE1_ENCRYPTION[phase1.encryption_algorithm[0]],
            "ikev2_integrity": NAUTOBOT_TO_IOSXE_PHASE1_INTEGRITY[phase1.integrity_algorithm[0]],
            "ikev2_proposal_name": f"PORTAL-PROP-{sequence}",
            "ikev2_policy_name": f"PORTAL-POL-{sequence}",
            "ikev2_keyring_name": f"PORTAL-KR-{sequence}",
            "ikev2_profile_name": f"PORTAL-PROF-{sequence}",
        })
    else:
        params.update({
            "ikev1_encryption": NAUTOBOT_TO_IOSXE_IKEV1_ENCRYPTION[phase1.encryption_algorithm[0]],
            "ikev1_hash": NAUTOBOT_TO_IOSXE_IKEV1_HASH[phase1.integrity_algorithm[0]],
            "isakmp_policy_priority": sequence,
        })

    return params
