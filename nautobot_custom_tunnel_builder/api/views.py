"""Portal API views for self-service IPsec tunnel provisioning."""

import logging
import secrets

from django.db import connection, transaction
from nautobot.core.api.authentication import TokenAuthentication
from nautobot.dcim.models import Device, DeviceType, Interface, Manufacturer
from nautobot.extras.models import Job as JobModel
from nautobot.extras.models import JobResult, Role, Secret, SecretsGroup, Status
from nautobot.ipam.models import IPAddress, Namespace, Prefix
from nautobot.vpn.models import (
    VPN,
    VPNProfile,
    VPNProfilePhase1PolicyAssignment,
    VPNProfilePhase2PolicyAssignment,
    VPNTunnel,
    VPNTunnelEndpoint,
)
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from ..mapping import profile_to_config_params
from ..onepassword_utils import get_secret_provider_params, store_psk_in_1password
from .serializers import PortalTunnelRequestSerializer

logger = logging.getLogger(__name__)


def _location_slug(city, state):
    """Compose a location slug from city and state."""
    return f"{city.lower().replace(' ', '-')}-{state.lower()}"


def _member_role():
    """The 'Member' role, or None if it hasn't been bootstrapped yet.

    Defensive: provisioning must not fail just because the role is absent —
    we set it when present and leave the field null otherwise. The portal
    bootstrap scopes this role to the VPN object types before members are
    exposed.
    """
    return Role.objects.filter(name="Member").first()


def _member_namespace(member_name, tenant):
    """Per-member IPAM namespace — keeps each member's address space isolated.

    Falls back to the shared "Members" namespace only when no tenant is
    supplied (legacy callers). Assigning the tenant here is safe on re-runs:
    get_or_create keys on name, and we set the tenant on first creation.
    """
    if tenant is None:
        ns, _ = Namespace.objects.get_or_create(
            name="Members",
            defaults={"description": "Namespace for member VPN endpoint addresses."},
        )
        return ns
    ns, _ = Namespace.objects.get_or_create(
        name=f"member-{member_name}",
        defaults={
            "description": f"IPAM namespace for member '{member_name}'.",
            "tenant": tenant,
        },
    )
    return ns


def _get_or_create_member_device(member_name, location_slug, remote_peer_ip, location_obj, tenant=None):  # pylint: disable=too-many-locals
    """Create or retrieve the member placeholder Device with a per-peer interface and IP."""
    manufacturer, _ = Manufacturer.objects.get_or_create(
        name="Generic",
        defaults={"description": "Generic/virtual manufacturer for placeholder devices."},
    )
    device_type, _ = DeviceType.objects.get_or_create(
        model="Member VPN Endpoint",
        manufacturer=manufacturer,
    )
    role, _ = Role.objects.get_or_create(name="Member")

    device_name = f"member-{member_name}-{location_slug}"
    device_status = Status.objects.get_for_model(Device).get(name="Active")

    device, _ = Device.objects.get_or_create(
        name=device_name,
        defaults={
            "device_type": device_type,
            "role": role,
            "location": location_obj,
            "status": device_status,
            "tenant": tenant,
        },
    )

    intf_status = Status.objects.get_for_model(Interface).get(name="Active")
    interface_name = f"peer-{remote_peer_ip.replace('.', '-')}"
    interface, _ = Interface.objects.get_or_create(
        device=device,
        name=interface_name,
        defaults={"type": "virtual", "status": intf_status},
    )

    # Get or create the IP address and assign to the interface
    # Nautobot 3.x requires a parent Prefix for every IPAddress
    members_ns = _member_namespace(member_name, tenant)
    prefix_status = Status.objects.get_for_model(Prefix).get(name="Active")
    # Create a /32 parent prefix scoped to just this member's peer IP — we do
    # not model the member's surrounding /24, only the single host we peer with.
    import ipaddress as ipaddresslib  # pylint: disable=import-outside-toplevel

    ip_obj = ipaddresslib.ip_address(remote_peer_ip)
    parent_network = ipaddresslib.ip_network(f"{ip_obj}/32", strict=False)
    Prefix.objects.get_or_create(
        prefix=str(parent_network),
        namespace=members_ns,
        defaults={"status": prefix_status, "tenant": tenant},
    )
    ip_str = f"{remote_peer_ip}/32"
    ip_address, _ = IPAddress.objects.get_or_create(
        address=ip_str,
        namespace=members_ns,
        defaults={
            "status": Status.objects.get_for_model(IPAddress).get(name="Active"),
            "tenant": tenant,
        },
    )
    from nautobot.ipam.models import IPAddressToInterface  # pylint: disable=import-outside-toplevel

    IPAddressToInterface.objects.get_or_create(
        ip_address=ip_address,
        interface=interface,
    )

    return device, ip_address


def _get_or_create_location(city, state):
    """Look up or create a Nautobot Location by city-state slug."""
    from nautobot.dcim.models import Location, LocationType  # pylint: disable=import-outside-toplevel

    loc_name = f"{city}, {state.upper()}"
    location_type, _ = LocationType.objects.get_or_create(name="Site")

    location, _ = Location.objects.get_or_create(
        name=loc_name,
        location_type=location_type,
        defaults={
            "status": Status.objects.get_for_model(Location).get(name="Active"),
        },
    )
    return location


def _clone_vpn_profile(template, name, sequence, tenant=None):
    """Clone a template VPNProfile into a per-tunnel profile with custom fields."""
    profile = VPNProfile.objects.create(
        name=name,
        description=f"Cloned from template '{template.name}' for portal tunnel.",
        tenant=tenant,
    )

    # Copy Phase 1 policy assignments
    for assignment in template.vpn_profile_phase1_policy_assignments.all():
        VPNProfilePhase1PolicyAssignment.objects.create(
            vpn_profile=profile,
            vpn_phase1_policy=assignment.vpn_phase1_policy,
            weight=assignment.weight,
        )

    # Copy Phase 2 policy assignments
    for assignment in template.vpn_profile_phase2_policy_assignments.all():
        VPNProfilePhase2PolicyAssignment.objects.create(
            vpn_profile=profile,
            vpn_phase2_policy=assignment.vpn_phase2_policy,
            weight=assignment.weight,
        )

    # Copy secrets_group, keepalive, NAT settings from template
    if template.secrets_group:
        profile.secrets_group = template.secrets_group
    profile.save()

    # Set custom fields
    profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"] = sequence  # pylint: disable=protected-access
    profile.save()

    return profile


SEQUENCE_FLOOR = 3000
SEQUENCE_STEP = 10


def _allocate_crypto_map_sequence(device):
    """Return the next crypto map sequence (>= 3000, step 10) for a hub device.

    Must be called inside transaction.atomic(). On PostgreSQL a
    transaction-scoped advisory lock keyed on the device pk serializes
    concurrent allocations so two first-tunnel requests cannot both compute
    3000. Sequences below the floor (legacy manual crypto map entries) are
    ignored so they cannot drag next_seq down into colliding values.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [str(device.pk)])
    existing_tunnels = VPNTunnel.objects.filter(endpoint_z__device=device).select_related("vpn_profile")
    sequences = [
        t.vpn_profile._custom_field_data.get("custom_tunnel_builder_crypto_map_sequence")  # pylint: disable=protected-access
        for t in existing_tunnels
        if t.vpn_profile
    ]
    portal_sequences = [s for s in sequences if isinstance(s, int) and s >= SEQUENCE_FLOOR]
    if portal_sequences:
        return max(portal_sequences) + SEQUENCE_STEP
    return SEQUENCE_FLOOR


def _get_or_create_prefix(cidr, member_name, tenant=None):
    """Get or create a member protected-prefix in the member's namespace."""
    members_ns = _member_namespace(member_name, tenant)
    prefix, _ = Prefix.objects.get_or_create(
        prefix=cidr,
        namespace=members_ns,
        defaults={
            "status": Status.objects.get_for_model(Prefix).get(name="Active"),
            "tenant": tenant,
        },
    )
    return prefix


class PortalTunnelRequestView(APIView):
    """Accept a portal tunnel provisioning request and enqueue the build job."""

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):  # pylint: disable=too-many-locals,too-many-return-statements
        """Validate, create VPN object hierarchy, enqueue build job, return 202."""
        # Authenticated is not enough: provisioning creates objects and pushes
        # crypto config to a real device. Gate on the Nautobot add permission
        # for VPNTunnel — the representative capability for "provision a
        # tunnel." has_perm() with no object is True for a superuser or any
        # ObjectPermission granting add on VPNTunnel, False otherwise.
        if not request.user.has_perm("vpn.add_vpntunnel"):
            return Response(
                {"detail": "You do not have permission to provision tunnels."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = PortalTunnelRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        device = data["device"]
        template = data["template_vpn_profile"]
        remote_peer_ip = str(data["remote_peer_ip"])
        member_name = data["member_name"]
        member_display = data["member_display_name"]
        city = data["location_city"]
        state = data["location_state"]
        member_prefix_cidrs = data["member_protected_prefixes"]
        request_id = data["member_connect_request_id"]
        tenant = data.get("tenant")

        loc_slug = _location_slug(city, state)
        display_location = f"{city}, {state.upper()}"

        # -------------------------------------------------------------- #
        # Serialize check-then-create on the request id: one transaction  #
        # shared by the dedupe check and hierarchy creation, guarded by a  #
        # Postgres transaction-scoped advisory lock so two concurrent      #
        # replays of the same request_id can't both pass the dedupe check. #
        # -------------------------------------------------------------- #
        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        [f"member-connect-request/{request_id}"],
                    )

            # ---------------------------------------------------------- #
            # Idempotency: a replayed portal request returns the original #
            # tunnel. Checked before every other gate.                    #
            # ---------------------------------------------------------- #
            existing_tunnel = VPNTunnel.objects.filter(_custom_field_data__member_connect_request_id=request_id).first()
            if existing_tunnel:
                return Response(
                    {
                        "detail": "A tunnel for this member_connect_request_id already exists.",
                        "tunnel_id": str(existing_tunnel.pk),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            # ---------------------------------------------------------- #
            # Hub endpoint pre-check. The hub protected prefix comes from  #
            # the pre-configured hub VPNTunnelEndpoint, never the request. #
            # ---------------------------------------------------------- #
            hub_endpoint = VPNTunnelEndpoint.objects.filter(device=device, role__name="Hub").first()
            if hub_endpoint is None:
                return Response(
                    {
                        "device": [
                            f"Device '{device.name}' has no pre-configured hub VPN tunnel endpoint "
                            "(role 'Hub'). An administrator must create one with a protected prefix "
                            "before tunnels can be requested."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not hub_endpoint.protected_prefixes.exists():
                return Response(
                    {
                        "device": [
                            f"The hub endpoint on device '{device.name}' has no protected prefix. "
                            "An administrator must add one before tunnels can be requested."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ---------------------------------------------------------- #
            # Duplicate check (same member+location VPN, same remote peer) #
            # ---------------------------------------------------------- #
            vpn_name = f"vpn-nrtc-ms-{member_name}-{loc_slug}-001"
            existing_vpn = VPN.objects.filter(vpn_id=vpn_name).first()
            if existing_vpn:
                for tun in existing_vpn.vpn_tunnels.all():
                    spoke = tun.endpoint_a
                    if spoke and spoke.source_ipaddress and str(spoke.source_ipaddress.address.ip) == remote_peer_ip:
                        return Response(
                            {
                                "detail": "A tunnel with these parameters already exists.",
                                "tunnel_id": str(tun.pk),
                            },
                            status=status.HTTP_409_CONFLICT,
                        )

            # ---------------------------------------------------------- #
            # Create full object hierarchy (nested savepoint)              #
            # ---------------------------------------------------------- #
            try:
                tunnel, vpn = self._create_tunnel_hierarchy(
                    device,
                    template,
                    member_name,
                    member_display,
                    city,
                    state,
                    loc_slug,
                    display_location,
                    remote_peer_ip,
                    hub_endpoint,
                    member_prefix_cidrs,
                    vpn_name,
                    request_id,
                    tenant,
                )
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("Failed to create tunnel for member '%s'.", member_name)
                return Response(
                    {"detail": "Failed to create tunnel. Contact an administrator."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # -------------------------------------------------------------- #
        # Enqueue the build job                                            #
        # -------------------------------------------------------------- #
        try:
            job_model = JobModel.objects.get(
                module_name="nautobot_custom_tunnel_builder.jobs",
                job_class_name="PortalBuildIpsecTunnel",
            )
        except JobModel.DoesNotExist:
            logger.error("PortalBuildIpsecTunnel job is not registered.")
            return Response(
                {"detail": "Build job is not registered. Contact an administrator."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        job_result = JobResult.enqueue_job(
            job_model=job_model,
            user=request.user,
            tunnel_id=str(tunnel.pk),
        )

        # Build response URLs
        status_url = reverse(
            "plugins-api:nautobot_custom_tunnel_builder-api:tunnel-status",
            kwargs={"tunnel_id": tunnel.pk},
            request=request,
        )

        return Response(
            {
                "tunnel_id": str(tunnel.pk),
                "tunnel_name": tunnel.name,
                "vpn_id": vpn.vpn_id,
                "job_id": str(job_result.pk),
                "status_url": status_url,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @staticmethod
    def _create_tunnel_hierarchy(  # pylint: disable=too-many-locals,too-many-arguments
        device,
        template,
        member_name,
        member_display,
        city,
        state,
        loc_slug,
        display_location,
        remote_peer_ip,
        hub_endpoint,
        member_prefix_cidrs,
        vpn_name,
        request_id,
        tenant=None,
    ):
        """Create the full VPN object hierarchy inside an atomic transaction.

        The tunnel is created with status "Planned"; PortalBuildIpsecTunnel flips
        it to Active on a successful push, Decommissioning on failure.

        Returns:
            Tuple of (tunnel, vpn).

        Raises:
            Exception: If any step fails (1Password, DB, etc.), the transaction rolls back.
        """
        with transaction.atomic():
            # 1. Location
            location_obj = _get_or_create_location(city, state)

            # 2. Member Device + per-peer interface + IP
            member_device, member_ip = _get_or_create_member_device(
                member_name,
                loc_slug,
                remote_peer_ip,
                location_obj,
                tenant=tenant,
            )

            # 3. VPN (get_or_create by member+location) — the top-level
            # Member-Connect-owned object; stamped managed for teardown.
            member_role = _member_role()
            vpn, vpn_created = VPN.objects.get_or_create(
                vpn_id=vpn_name,
                defaults={
                    "name": f"{member_display} - {display_location}",
                    "tenant": tenant,
                    "role": member_role,
                },
            )
            if vpn_created:
                vpn._custom_field_data["member_connect_managed"] = True  # pylint: disable=protected-access
                vpn.save()

            # 4. Allocate the next crypto map sequence (advisory-locked, floor 3000).
            next_seq = _allocate_crypto_map_sequence(device)

            # 5. Generate PSK
            psk = secrets.token_urlsafe(32)

            # 6. Store PSK in 1Password.
            # NOTE: external call inside transaction.atomic() — orphaned items are
            # identifiable by name pattern vpn-psk-nrtc-ms-{member}-{loc_slug}-{seq}.
            # TODO: two-phase commit (logged fast-follow).
            op_item_id = store_psk_in_1password(
                psk,
                member_name,
                loc_slug,
                next_seq,
                note_context={
                    "member": f"{member_display} ({member_name})",
                    "location": display_location,
                    "remote_peer_ip": remote_peer_ip,
                    "hub_device": device.name,
                    "sequence": next_seq,
                    "request_id": request_id,
                },
            )

            # 7. Nautobot Secret + SecretsGroup for this tunnel's PSK
            _secret_provider, _secret_params = get_secret_provider_params(op_item_id)
            tunnel_secret = Secret.objects.create(
                name=f"vpn-psk-nrtc-ms-{member_name}-{loc_slug}-{next_seq}",
                provider=_secret_provider,
                parameters=_secret_params,
            )
            tunnel_sg = SecretsGroup.objects.create(
                name=f"vpn-sg-nrtc-ms-{member_name}-{loc_slug}-{next_seq}",
            )
            tunnel_sg.secrets.add(tunnel_secret)

            # 8. Clone template VPNProfile
            profile_name = f"vpnprofile-nrtc-ms-{member_name}-{loc_slug}-{next_seq}"
            profile = _clone_vpn_profile(template, profile_name, next_seq, tenant=tenant)
            profile.secrets_group = tunnel_sg
            profile.save()

            # Point the VPN at this profile on first creation (a reused VPN keeps
            # the profile from its first tunnel).
            if vpn_created and not vpn.vpn_profile:
                vpn.vpn_profile = profile
                vpn.save()

            # 9. Create VPNTunnel — born Planned.
            tunnel_name = f"{member_display} - {display_location} - {next_seq}"
            tunnel_id_str = f"vpn-tunnel-nrtc-ms-{member_name}-{loc_slug}-{next_seq}"
            tunnel_status = Status.objects.get_for_model(VPNTunnel).get(name="Planned")
            tunnel = VPNTunnel.objects.create(
                name=tunnel_name,
                tunnel_id=tunnel_id_str,
                status=tunnel_status,
                vpn=vpn,
                vpn_profile=profile,
                tenant=tenant,
                role=member_role,
                encapsulation="IPsec-Tunnel",
            )
            tunnel._custom_field_data["member_connect_request_id"] = request_id  # pylint: disable=protected-access
            tunnel._custom_field_data["member_connect_managed"] = True  # pylint: disable=protected-access

            # 10. Attach the pre-configured hub endpoint (endpoint_z).
            tunnel.endpoint_z = hub_endpoint

            # 11. Spoke VPNTunnelEndpoint (endpoint_a) — one protected prefix
            # association per entry in member_protected_prefixes.
            spoke_role = member_role or Role.objects.get_or_create(name="Spoke")[0]
            spoke_endpoint = VPNTunnelEndpoint.objects.create(
                name=f"{member_name}-{loc_slug}",
                role=spoke_role,
                device=member_device,
                source_ipaddress=member_ip,
                vpn_profile=profile,
                tenant=tenant,
            )
            for cidr in member_prefix_cidrs:
                spoke_endpoint.protected_prefixes.add(_get_or_create_prefix(cidr, member_name, tenant=tenant))
            tunnel.endpoint_a = spoke_endpoint
            tunnel.save()

        return tunnel, vpn


def _config_summary(tunnel):
    """Non-secret configuration summary for the member-facing package.

    Derived through profile_to_config_params — the same translation the build
    job renders device config from — so the summary cannot drift from what was
    pushed. Returns None when the tunnel is missing the objects it needs.
    """
    hub = tunnel.endpoint_z
    spoke = tunnel.endpoint_a
    profile = tunnel.vpn_profile
    if not hub or not profile:
        return None
    try:
        sequence = profile._custom_field_data.get("custom_tunnel_builder_crypto_map_sequence") or 0  # pylint: disable=protected-access
        hub_prefixes = [str(p.prefix) for p in hub.protected_prefixes.all()]
        params = profile_to_config_params(
            vpn_profile=profile,
            remote_peer_ip=str(spoke.source_ipaddress.address.ip) if spoke and spoke.source_ipaddress else "",
            local_network_cidr=hub_prefixes[0] if hub_prefixes else "",
            protected_network_cidrs=[],
            crypto_map_name="",
            sequence=sequence,
        )
    except (ValueError, KeyError):
        logger.exception("Could not derive config summary for tunnel '%s'.", tunnel.name)
        return None

    phase1 = {
        "ike_version": params["ike_version"],
        "dh_group": params["ike_dh_group"],
        "lifetime": params["ike_lifetime"],
    }
    if params["ike_version"] == "ikev2":
        phase1["encryption"] = params["ikev2_encryption"]
        phase1["integrity"] = params["ikev2_integrity"]
    else:
        phase1["encryption"] = params["ikev1_encryption"]
        phase1["integrity"] = params["ikev1_hash"]

    return {
        "hub_peer_ip": str(hub.source_ipaddress.address.ip) if hub.source_ipaddress else None,
        "hub_protected_prefixes": hub_prefixes,
        # Encapsulation as modeled on the tunnel; protocol is always ESP for the
        # IPsec transforms this flow builds. Both are surfaced to the member.
        "encapsulation": tunnel.encapsulation or "IPsec-Tunnel",
        "protocol": "ESP",
        "phase1": phase1,
        "phase2": {
            "encryption": params["ipsec_encryption"],
            "integrity": params["ipsec_integrity"],
            "lifetime": params["ipsec_lifetime"],
        },
    }


class TunnelStatusView(APIView):
    """Return the current status of a portal-created VPN tunnel."""

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, tunnel_id):
        """Return tunnel status; include the PSK exactly once when Active."""
        # Honor Nautobot ObjectPermissions: restrict the lookup to tunnels the
        # caller may view. A token without vpn.view_vpntunnel (or outside its
        # tenant constraint) gets the same 404 as a missing tunnel — no status
        # or PSK leak across the flat token boundary. Superusers see all.
        try:
            tunnel = VPNTunnel.objects.restrict(request.user, "view").get(pk=tunnel_id)
        except VPNTunnel.DoesNotExist:
            return Response(
                {"detail": "Tunnel not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        payload = {
            "tunnel_id": str(tunnel.pk),
            "tunnel_name": tunnel.name,
            "status": tunnel.status.name,
        }

        if tunnel.status.name in ("Provisioned", "Active"):
            summary = _config_summary(tunnel)
            if summary:
                payload["config_summary"] = summary

        profile = tunnel.vpn_profile
        # "Provisioned" is the canonical post-push status; "Active" is the
        # legacy name still carried by tunnels built before the rename.
        if tunnel.status.name in ("Provisioned", "Active") and profile is not None:
            # Guard the one-shot PSK latch with a row lock so two concurrent
            # GETs on a just-activated tunnel can't both read-check-write past
            # the "already retrieved" check and both return the PSK.
            with transaction.atomic():
                locked_profile = VPNProfile.objects.select_for_update().get(pk=profile.pk)
                already_retrieved = locked_profile._custom_field_data.get(  # pylint: disable=protected-access
                    "custom_tunnel_builder_psk_retrieved"
                )
                if not already_retrieved:
                    secret = locked_profile.secrets_group.secrets.first() if locked_profile.secrets_group else None
                    if secret:
                        try:
                            payload["pre_shared_key"] = secret.get_value()
                        except Exception:  # pylint: disable=broad-exception-caught
                            logger.exception("Failed to retrieve PSK for tunnel '%s'.", tunnel.name)
                        else:
                            locked_profile._custom_field_data[  # pylint: disable=protected-access
                                "custom_tunnel_builder_psk_retrieved"
                            ] = True
                            locked_profile.save(update_fields=["_custom_field_data"])

        return Response(payload)
