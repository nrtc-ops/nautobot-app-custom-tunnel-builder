"""Idempotent seed data for the local portal E2E harness.

Run inside the nautobot container:
    poetry run invoke seed-e2e
(pipes this file into `nautobot-server nbshell --plain`).

Creates (get_or_create throughout — safe to re-run):
  - Hub Device "fake-cisco" (Cisco IOS-XE, primary IPv4 172.18.0.100/32 — the
    pinned address of the fake-cisco container in docker-compose.fake-cisco.yml)
  - Template VPNProfiles "Standard-IKEv2-AES256" and "Standard-IKEv1-AES256"\n    with Phase 1/2 policies + assignments
  - Hub VPNTunnelEndpoint (device + role "Hub") with protected prefix + crypto map CF
  - "Planned", "Provisioned", "Decommissioning" statuses mapped to VPNTunnel
  - PortalBuildIpsecTunnel Job row enabled (disabled by default on a fresh DB;
    the portal view's enqueue would otherwise fail with RunJobTaskFailed). If
    the Job row hasn't been registered yet (registry not synced), this step
    prints an actionable error and everything else still gets seeded normally.
  - Portal service account "portal-svc" + API token (printed on first run only).
    This account is a Django superuser — deliberate for this local-only
    harness (see the WARNING it prints) rather than hand-granting scoped
    ObjectPermissions; do not reuse this pattern in a shared environment.
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer, Platform
from nautobot.extras.models import Job, Role, Status
from nautobot.ipam.models import IPAddress, IPAddressToInterface, Namespace, Prefix
from nautobot.users.models import Token
from nautobot.vpn.models import (
    VPNPhase1Policy,
    VPNPhase2Policy,
    VPNProfile,
    VPNProfilePhase1PolicyAssignment,
    VPNProfilePhase2PolicyAssignment,
    VPNTunnel,
    VPNTunnelEndpoint,
)

HUB_DEVICE_NAME = "fake-cisco"
HUB_IP = "172.18.0.100/32"  # pinned in docker-compose.fake-cisco.yml
HUB_PARENT_PREFIX = "172.18.0.0/16"  # the compose overlay's docker subnet
HUB_PROTECTED_PREFIX = "10.100.0.0/24"
TEMPLATE_PROFILE_NAME = "Standard-IKEv2-AES256"
TEMPLATE_PROFILE_IKEV1_NAME = "Standard-IKEv1-AES256"
SERVICE_ACCOUNT = "portal-svc"


def _status(model, name="Active"):
    return Status.objects.get_for_model(model).get(name=name)


def _seed_hub_device():
    manufacturer, _ = Manufacturer.objects.get_or_create(name="Cisco")
    device_type, _ = DeviceType.objects.get_or_create(model="CSR1000v", manufacturer=manufacturer)
    platform, _ = Platform.objects.get_or_create(
        name="Cisco IOS-XE",
        defaults={"network_driver": "cisco_xe"},
    )
    role, _ = Role.objects.get_or_create(name="Router")
    role.content_types.add(ContentType.objects.get_for_model(Device))
    location_type, _ = LocationType.objects.get_or_create(name="Site")
    location_type.content_types.add(ContentType.objects.get_for_model(Device))
    location, _ = Location.objects.get_or_create(
        name="NRTC Lab",
        location_type=location_type,
        defaults={"status": _status(Location)},
    )
    device, _ = Device.objects.get_or_create(
        name=HUB_DEVICE_NAME,
        defaults={
            "device_type": device_type,
            "platform": platform,
            "role": role,
            "location": location,
            "status": _status(Device),
        },
    )
    interface, _ = Interface.objects.get_or_create(
        device=device,
        name="GigabitEthernet1",
        defaults={"type": "1000base-t", "status": _status(Interface)},
    )
    global_ns, _ = Namespace.objects.get_or_create(name="Global")
    Prefix.objects.get_or_create(
        prefix=HUB_PARENT_PREFIX,
        namespace=global_ns,
        defaults={"status": _status(Prefix)},
    )
    # get_or_create keyed on the full "host/mask" address would miss a
    # pre-existing record for this host under a different mask (e.g. a device
    # hand-provisioned via the UI with a /24 instead of /32) and then crash on
    # the (parent, host) unique constraint when it tries to create a second
    # row for the same host. Look up by host first so the script is safe to
    # run against either a fresh environment or one that already has this
    # host address configured.
    hub_host = HUB_IP.split("/")[0]
    ip = IPAddress.objects.filter(host=hub_host, parent__namespace=global_ns).first()
    if ip is None:
        ip = IPAddress.objects.create(
            address=HUB_IP,
            namespace=global_ns,
            status=_status(IPAddress),
        )
        IPAddressToInterface.objects.get_or_create(ip_address=ip, interface=interface)
    if device.primary_ip4_id != ip.pk:
        device.primary_ip4 = ip
        device.save()
    return device, global_ns


def _seed_template_profile():
    phase1, _ = VPNPhase1Policy.objects.get_or_create(
        name="Standard-IKEv2-Phase1",
        defaults={
            "ike_version": "IKEv2",
            "encryption_algorithm": ["AES-256-CBC"],
            "integrity_algorithm": ["SHA256"],
            "dh_group": ["19"],
            "lifetime_seconds": 86400,
        },
    )
    phase2, _ = VPNPhase2Policy.objects.get_or_create(
        name="Standard-AES256-Phase2",
        defaults={
            "encryption_algorithm": ["AES-256-CBC"],
            "integrity_algorithm": ["SHA256"],
            "lifetime": 3600,
        },
    )
    profile, _ = VPNProfile.objects.get_or_create(
        name=TEMPLATE_PROFILE_NAME,
        defaults={"description": "Template profile cloned per portal tunnel."},
    )
    VPNProfilePhase1PolicyAssignment.objects.get_or_create(
        vpn_profile=profile,
        vpn_phase1_policy=phase1,
        defaults={"weight": 100},
    )
    VPNProfilePhase2PolicyAssignment.objects.get_or_create(
        vpn_profile=profile,
        vpn_phase2_policy=phase2,
        defaults={"weight": 100},
    )
    return profile


def _seed_ikev1_template_profile():
    # Legacy-compatibility template: members pick this in the wizard only when
    # their gear cannot do IKEv2. DH group 14 — v1 gear rarely does ECP curves.
    phase1, _ = VPNPhase1Policy.objects.get_or_create(
        name="Standard-IKEv1-Phase1",
        defaults={
            "ike_version": "IKEv1",
            "encryption_algorithm": ["AES-256-CBC"],
            "integrity_algorithm": ["SHA256"],
            "dh_group": ["14"],
            "lifetime_seconds": 86400,
        },
    )
    phase2, _ = VPNPhase2Policy.objects.get_or_create(
        name="Standard-AES256-Phase2",
        defaults={
            "encryption_algorithm": ["AES-256-CBC"],
            "integrity_algorithm": ["SHA256"],
            "lifetime": 3600,
        },
    )
    profile, _ = VPNProfile.objects.get_or_create(
        name=TEMPLATE_PROFILE_IKEV1_NAME,
        defaults={"description": "IKEv1 legacy template profile cloned per portal tunnel."},
    )
    VPNProfilePhase1PolicyAssignment.objects.get_or_create(
        vpn_profile=profile,
        vpn_phase1_policy=phase1,
        defaults={"weight": 100},
    )
    VPNProfilePhase2PolicyAssignment.objects.get_or_create(
        vpn_profile=profile,
        vpn_phase2_policy=phase2,
        defaults={"weight": 100},
    )
    return profile


def _seed_hub_endpoint(device, namespace):
    hub_role, _ = Role.objects.get_or_create(name="Hub")
    hub_role.content_types.add(ContentType.objects.get_for_model(VPNTunnelEndpoint))
    endpoint, created = VPNTunnelEndpoint.objects.get_or_create(
        device=device,
        role=hub_role,
        defaults={"source_ipaddress": device.primary_ip},
    )
    if created or not endpoint._custom_field_data.get("custom_tunnel_builder_crypto_map_name"):
        endpoint._custom_field_data["custom_tunnel_builder_crypto_map_name"] = "VPN"
        endpoint.save()
    prefix, _ = Prefix.objects.get_or_create(
        prefix=HUB_PROTECTED_PREFIX,
        namespace=namespace,
        defaults={"status": _status(Prefix)},
    )
    endpoint.protected_prefixes.add(prefix)
    return endpoint


def _seed_tunnel_statuses():
    vpntunnel_ct = ContentType.objects.get_for_model(VPNTunnel)
    for status_name in ("Planned", "Provisioned", "Decommissioning"):
        st, _ = Status.objects.get_or_create(name=status_name)
        st.content_types.add(vpntunnel_ct)


def _seed_portal_build_job():
    # On a fresh DB, Nautobot registers Job rows disabled by default. The
    # portal view enqueues this job by module_name/job_class_name (same
    # lookup as api/views.py); if it's not enabled, JobResult.enqueue_job()
    # raises RunJobTaskFailed and the tunnel is stuck Planned forever.
    #
    # The Job row itself is created by Nautobot's job-registry sync (normally
    # run during migrate/post_upgrade), not by this script. If that sync
    # hasn't happened yet, .get() would raise Job.DoesNotExist — guard it so
    # a registry hiccup doesn't abort the rest of the seed (device, profile,
    # service account/token all still need to get created either way).
    try:
        job = Job.objects.get(
            module_name="nautobot_custom_tunnel_builder.jobs",
            job_class_name="PortalBuildIpsecTunnel",
        )
    except Job.DoesNotExist:
        print(
            "  ERROR:            PortalBuildIpsecTunnel Job not registered yet — "
            "run 'nautobot-server post_upgrade' (or 'poetry run invoke post-upgrade') "
            "and re-run seed-e2e"
        )
        return None
    if not job.enabled:
        job.enabled = True
        job.save()
    return job


def _seed_service_account():
    # Superuser: the portal-request POST itself only requires IsAuthenticated
    # (it reads/writes via plain ORM calls, no RBAC-gated queryset), but
    # test-portal-api.sh's device-eligibility precheck and VPN profile
    # discovery hit Nautobot's standard REST API (dcim/devices,
    # vpn/vpn-profiles), which does enforce object permissions.
    #
    # Production-shaped alternative would be scoped ObjectPermissions (view on
    # dcim.device / vpn.vpnprofile, add/change on the handful of models the
    # portal view creates). Superuser is a deliberate shortcut for this local,
    # throwaway E2E harness only — never do this in a shared environment. The
    # WARNING below exists so that shortcut is never silent.
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(
        username=SERVICE_ACCOUNT,
        defaults={"is_active": True, "is_superuser": True, "is_staff": True},
    )
    if not (user.is_superuser and user.is_staff):
        user.is_superuser = True
        user.is_staff = True
        user.save()
    # Loud on every run, not just the creation/upgrade transition — a silent
    # superuser grant is exactly the risk this warning exists to prevent.
    print(
        "  WARNING:          portal-svc is a SUPERUSER (dev harness only — "
        "scope with ObjectPermissions before any shared environment)"
    )
    token = Token.objects.filter(user=user).first()
    if token is None:
        token = Token.objects.create(user=user, description="member-connect-portal service token")
        print(f"  portal token (printed ONCE — save it now): {token.key}")
    else:
        print("  portal token already exists — not re-printed (delete it in the UI to rotate).")
    return user


def _main():
    print("Seeding E2E harness objects (idempotent)...")
    device, global_ns = _seed_hub_device()
    print(f"  hub device:       {device.name}  {device.pk}")
    profile = _seed_template_profile()
    print(f"  template profile: {profile.name}  {profile.pk}")
    ikev1_profile = _seed_ikev1_template_profile()
    print(f"  ikev1 template:   {ikev1_profile.name}  {ikev1_profile.pk}")
    _seed_hub_endpoint(device, global_ns)
    print(f"  hub endpoint:     device={device.name} role=Hub prefix={HUB_PROTECTED_PREFIX}")
    _seed_tunnel_statuses()
    print("  statuses:         Planned + Provisioned + Decommissioning mapped to VPNTunnel")
    # Service account/token before the Job lookup: if the Job registry hasn't
    # synced yet, _seed_portal_build_job() only prints an error and moves on —
    # it must not be able to abort the run before the token gets created.
    _seed_service_account()
    job = _seed_portal_build_job()
    if job is not None:
        print(f"  job:              {job.name} enabled")
    print("Done. Use the UUIDs above as HUB_DEVICE_UUID / TEMPLATE_PROFILE_UUID for")
    print("development/test-portal-api.sh and as the portal's nautobot.hub_device_id /")
    print("nautobot.template_vpn_profile_id credentials.")


_main()
