"""Portal API views for self-service IPsec tunnel provisioning."""

import logging
import secrets

from django.db import transaction
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

from ..onepassword_utils import get_secret_provider_params, store_psk_in_1password
from .serializers import PortalTunnelRequestSerializer

logger = logging.getLogger(__name__)


def _location_slug(city, state):
    """Compose a location slug from city and state."""
    return f"{city.lower().replace(' ', '-')}-{state.lower()}"


def _get_or_create_member_device(member_name, location_slug, remote_peer_ip, location_obj):  # pylint: disable=too-many-locals
    """Create or retrieve the member placeholder Device with dummy0 interface and IP."""
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
        },
    )

    intf_status = Status.objects.get_for_model(Interface).get(name="Active")
    interface, _ = Interface.objects.get_or_create(
        device=device,
        name="dummy0",
        defaults={"type": "virtual", "status": intf_status},
    )

    # Get or create the IP address and assign to the interface
    # Nautobot 3.x requires a parent Prefix for every IPAddress
    members_ns, _ = Namespace.objects.get_or_create(
        name="Members",
        defaults={"description": "Namespace for member VPN endpoint addresses."},
    )
    prefix_status = Status.objects.get_for_model(Prefix).get(name="Active")
    # Create a /24 parent prefix for the member's IP
    import ipaddress as ipaddresslib  # pylint: disable=import-outside-toplevel

    ip_obj = ipaddresslib.ip_address(remote_peer_ip)
    parent_network = ipaddresslib.ip_network(f"{ip_obj}/24", strict=False)
    Prefix.objects.get_or_create(
        prefix=str(parent_network),
        namespace=members_ns,
        defaults={"status": prefix_status},
    )
    ip_str = f"{remote_peer_ip}/32"
    ip_address, _ = IPAddress.objects.get_or_create(
        address=ip_str,
        namespace=members_ns,
        defaults={
            "status": Status.objects.get_for_model(IPAddress).get(name="Active"),
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


def _clone_vpn_profile(template, name, sequence):
    """Clone a template VPNProfile into a per-tunnel profile with custom fields."""
    profile = VPNProfile.objects.create(
        name=name,
        description=f"Cloned from template '{template.name}' for portal tunnel.",
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


def _get_or_create_prefix(cidr):
    """Get or create a Prefix in the Members namespace."""
    members_ns, _ = Namespace.objects.get_or_create(
        name="Members",
        defaults={"description": "Namespace for member VPN protected prefixes."},
    )
    prefix, _ = Prefix.objects.get_or_create(
        prefix=cidr,
        namespace=members_ns,
        defaults={
            "status": Status.objects.get_for_model(Prefix).get(name="Active"),
        },
    )
    return prefix


class PortalTunnelRequestView(APIView):
    """Accept a portal tunnel provisioning request and enqueue the build job."""

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):  # pylint: disable=too-many-locals
        """Validate, create VPN object hierarchy, enqueue build job, return 202."""
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
        hub_prefix_cidr = data["hub_protected_prefix"]
        member_prefix_cidr = data["member_protected_prefix"]

        loc_slug = _location_slug(city, state)
        display_location = f"{city}, {state.upper()}"

        # -------------------------------------------------------------- #
        # Duplicate check                                                   #
        # -------------------------------------------------------------- #
        vpn_name = f"vpn-nrtc-ms-{member_name}-{loc_slug}-001"
        existing_vpn = VPN.objects.filter(vpn_id=vpn_name).first()
        if existing_vpn:
            # Check for duplicate: any tunnel under this VPN with a spoke endpoint
            # matching the remote peer IP
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

        # -------------------------------------------------------------- #
        # Create full object hierarchy inside a transaction                 #
        # -------------------------------------------------------------- #
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
                hub_prefix_cidr,
                member_prefix_cidr,
                vpn_name,
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
        hub_prefix_cidr,
        member_prefix_cidr,
        vpn_name,
    ):
        """Create the full VPN object hierarchy inside an atomic transaction.

        Returns:
            Tuple of (tunnel, vpn).

        Raises:
            Exception: If any step fails (1Password, DB, etc.), the transaction rolls back.
        """
        with transaction.atomic():
            # 1. Location
            location_obj = _get_or_create_location(city, state)

            # 2. Member Device + dummy0 + IP
            _member_device, member_ip = _get_or_create_member_device(
                member_name,
                loc_slug,
                remote_peer_ip,
                location_obj,
            )

            # 3. VPN (get_or_create by member+location)
            vpn, _ = VPN.objects.get_or_create(
                vpn_id=vpn_name,
                defaults={
                    "name": f"{member_display} - {display_location}",
                },
            )

            # 4. Calculate next crypto map sequence for this device.
            # select_for_update() locks matching rows to prevent concurrent requests
            # from computing the same sequence number.
            existing_tunnels = VPNTunnel.objects.select_for_update(of=("self",)).filter(
                endpoint_z__source_ipaddress=device.primary_ip,
            ).select_related("vpn_profile")
            sequences = [
                t.vpn_profile._custom_field_data.get(  # pylint: disable=protected-access
                    "custom_tunnel_builder_crypto_map_sequence", 0
                )
                for t in existing_tunnels
                if t.vpn_profile
            ]
            max_seq = max(sequences) if sequences else None
            next_seq = (max_seq + 10) if max_seq is not None else 3000

            # 5. Generate PSK
            psk = secrets.token_urlsafe(32)

            # 6. Store PSK in 1Password.
            # NOTE: This external call is inside transaction.atomic(). If a DB step after
            # this line raises, the transaction rolls back but the 1Password item is already
            # created (orphaned). Orphaned items can be identified by name pattern:
            # vpn-psk-nrtc-ms-{member}-{loc_slug}-{seq}
            # TODO: Move 1Password call outside the transaction (two-phase: commit DB first,
            # then create 1Password item and update Secret.parameters in a second transaction).
            op_item_id = store_psk_in_1password(psk, member_name, loc_slug, next_seq)

            # 7. Create Nautobot Secret + SecretsGroup for this tunnel's PSK
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
            profile = _clone_vpn_profile(template, profile_name, next_seq)
            profile.secrets_group = tunnel_sg
            profile.save()

            # 9. Create VPNTunnel
            tunnel_name = f"{member_display} - {display_location} - {next_seq}"
            tunnel_id_str = f"vpn-tunnel-nrtc-ms-{member_name}-{loc_slug}-{next_seq}"
            tunnel_status = Status.objects.get_for_model(VPNTunnel).get(name="Active")

            tunnel = VPNTunnel.objects.create(
                name=tunnel_name,
                tunnel_id=tunnel_id_str,
                status=tunnel_status,
                vpn=vpn,
                vpn_profile=profile,
            )

            # 10. Create Prefix objects
            hub_prefix = _get_or_create_prefix(hub_prefix_cidr)
            member_prefix = _get_or_create_prefix(member_prefix_cidr)

            # 11. Hub VPNTunnelEndpoint (concentrator) — endpoint_z.
            # get_or_create so multiple portal tunnels share the same hub endpoint
            # rather than creating a duplicate record per tunnel.
            hub_role, _ = Role.objects.get_or_create(name="Hub")
            hub_endpoint, hub_created = VPNTunnelEndpoint.objects.get_or_create(
                role=hub_role,
                source_ipaddress=device.primary_ip,
            )
            hub_endpoint.protected_prefixes.add(hub_prefix)
            if hub_created:
                hub_endpoint._custom_field_data["custom_tunnel_builder_crypto_map_name"] = "VPN"  # pylint: disable=protected-access
                hub_endpoint.save()
            tunnel.endpoint_z = hub_endpoint
            tunnel.save()

            # 12. Spoke VPNTunnelEndpoint (member) — endpoint_a
            spoke_role, _ = Role.objects.get_or_create(name="Spoke")
            spoke_endpoint = VPNTunnelEndpoint.objects.create(
                role=spoke_role,
                source_ipaddress=member_ip,
            )
            spoke_endpoint.protected_prefixes.add(member_prefix)
            tunnel.endpoint_a = spoke_endpoint
            tunnel.save()

        return tunnel, vpn


class TunnelStatusView(APIView):
    """Return the current status of a portal-created VPN tunnel."""

    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, tunnel_id):
        """Return tunnel status and name."""
        try:
            tunnel = VPNTunnel.objects.get(pk=tunnel_id)
        except VPNTunnel.DoesNotExist:
            return Response(
                {"detail": "Tunnel not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "tunnel_id": str(tunnel.pk),
                "tunnel_name": tunnel.name,
                "status": tunnel.status.name,
            }
        )


