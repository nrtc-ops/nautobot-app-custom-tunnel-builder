"""Portal API views for self-service IPsec tunnel provisioning."""

import logging
import secrets

from django.db import transaction
from django.db.models import Max
from nautobot.extras.models import Job as JobModel
from nautobot.extras.models import JobResult, Status
from nautobot.vpn.models import VPNTunnel, VPNTunnelEndpoint
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.reverse import reverse
from rest_framework.views import APIView

from .serializers import PortalTunnelRequestSerializer

logger = logging.getLogger(__name__)


class PortalTunnelRequestView(APIView):
    """Accept a portal tunnel provisioning request and enqueue the build job."""

    permission_classes = [IsAuthenticated]

    def post(self, request):  # pylint: disable=too-many-locals
        """Validate, create VPNTunnel, enqueue build job, return 202."""
        serializer = PortalTunnelRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        device = data["device"]
        vpn_profile = data["vpn_profile"]
        remote_peer_ip = str(data["remote_peer_ip"])
        local_network_cidr = data["local_network_cidr"]
        protected_network_cidr = data["protected_network_cidr"]

        # -------------------------------------------------------------- #
        # Duplicate check                                                   #
        # -------------------------------------------------------------- #
        duplicates = VPNTunnel.objects.filter(
            _custom_field_data__remote_peer_ip=remote_peer_ip,
            _custom_field_data__local_network_cidr=local_network_cidr,
            _custom_field_data__protected_network_cidr=protected_network_cidr,
            vpntunnelendpoint__source_ip_address=device.primary_ip,
        )
        if duplicates.exists():
            dup = duplicates.first()
            return Response(
                {
                    "detail": "A tunnel with these parameters already exists.",
                    "tunnel_id": str(dup.pk),
                },
                status=status.HTTP_409_CONFLICT,
            )

        # -------------------------------------------------------------- #
        # Create tunnel inside a transaction                               #
        # -------------------------------------------------------------- #
        with transaction.atomic():
            # Calculate next crypto map sequence for this device
            existing_tunnels = VPNTunnel.objects.select_for_update().filter(
                vpntunnelendpoint__source_ip_address=device.primary_ip,
            )
            max_seq = existing_tunnels.aggregate(
                max_seq=Max("_custom_field_data__crypto_map_sequence"),
            )["max_seq"]
            next_seq = (max_seq + 10) if max_seq else 10

            # Generate PSK and retrieval token
            psk = secrets.token_urlsafe(32)
            psk_token = secrets.token_urlsafe(48)

            # Create VPNTunnel
            planned_status = Status.objects.get_for_model(VPNTunnel).get(name="Planned")
            tunnel_name = f"PORTAL-{device.name}-{remote_peer_ip}-seq{next_seq}"

            tunnel = VPNTunnel.objects.create(
                name=tunnel_name,
                status=planned_status,
                vpn_profile=vpn_profile,
                _custom_field_data={
                    "crypto_map_sequence": next_seq,
                    "remote_peer_ip": remote_peer_ip,
                    "local_network_cidr": local_network_cidr,
                    "protected_network_cidr": protected_network_cidr,
                    "psk_retrieval_token": psk_token,
                    "psk_retrieved": False,
                    "psk_encrypted": psk,
                },
            )

            # Create endpoints: hub (with source IP) and spoke (no source)
            VPNTunnelEndpoint.objects.create(
                vpn_tunnel=tunnel,
                role="hub",
                source_ip_address=device.primary_ip,
            )
            VPNTunnelEndpoint.objects.create(
                vpn_tunnel=tunnel,
                role="spoke",
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
            pre_shared_key=psk,
        )

        # Build response URLs
        status_url = reverse(
            "plugins-api:nautobot_custom_tunnel_builder-api:tunnel-status",
            kwargs={"tunnel_id": tunnel.pk},
            request=request,
        )
        psk_url = reverse(
            "plugins-api:nautobot_custom_tunnel_builder-api:psk-retrieval",
            kwargs={"token": psk_token},
            request=request,
        )

        return Response(
            {
                "tunnel_id": str(tunnel.pk),
                "tunnel_name": tunnel.name,
                "job_id": str(job_result.pk),
                "status_url": status_url,
                "psk_url": psk_url,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class TunnelStatusView(APIView):
    """Return the current status of a portal-created VPN tunnel."""

    permission_classes = [IsAuthenticated]

    def get(self, request, tunnel_id):
        """Return tunnel status, name, and conditional PSK URL."""
        try:
            tunnel = VPNTunnel.objects.get(pk=tunnel_id)
        except VPNTunnel.DoesNotExist:
            return Response(
                {"detail": "Tunnel not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        cf = tunnel._custom_field_data  # pylint: disable=protected-access
        response_data = {
            "tunnel_id": str(tunnel.pk),
            "tunnel_name": tunnel.name,
            "status": tunnel.status.name,
        }

        # Include PSK URL only when active and not yet retrieved
        psk_token = cf.get("psk_retrieval_token")
        if tunnel.status.name == "Active" and psk_token and not cf.get("psk_retrieved", False):
            response_data["psk_url"] = reverse(
                "plugins-api:nautobot_custom_tunnel_builder-api:psk-retrieval",
                kwargs={"token": psk_token},
                request=request,
            )

        return Response(response_data)


class PSKRetrievalView(APIView):
    """One-time PSK retrieval by token. Returns 410 Gone if already retrieved."""

    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        """Return the PSK and mark as retrieved (one-time use)."""
        try:
            tunnel = VPNTunnel.objects.get(_custom_field_data__psk_retrieval_token=token)
        except VPNTunnel.DoesNotExist:
            return Response(
                {"detail": "Invalid or expired PSK token."},
                status=status.HTTP_404_NOT_FOUND,
            )

        cf = tunnel._custom_field_data  # pylint: disable=protected-access

        if cf.get("psk_retrieved", False):
            return Response(
                {"detail": "PSK has already been retrieved. This token is no longer valid."},
                status=status.HTTP_410_GONE,
            )

        # Retrieve the PSK
        psk = cf.get("psk_encrypted", "")

        # Mark as retrieved and clear sensitive data
        tunnel._custom_field_data["psk_retrieved"] = True  # pylint: disable=protected-access
        tunnel._custom_field_data["psk_encrypted"] = ""  # pylint: disable=protected-access
        tunnel._custom_field_data["psk_retrieval_token"] = ""  # pylint: disable=protected-access
        tunnel.save()

        return Response(
            {
                "tunnel_id": str(tunnel.pk),
                "tunnel_name": tunnel.name,
                "pre_shared_key": psk,
            }
        )
