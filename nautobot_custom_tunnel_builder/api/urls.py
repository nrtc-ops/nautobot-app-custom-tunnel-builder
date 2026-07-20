"""URL configuration for the portal REST API."""

from django.urls import path

from .views import PortalTunnelRequestView, TunnelStatusView

app_name = "nautobot_custom_tunnel_builder"

urlpatterns = [
    path(
        "portal-request/",
        PortalTunnelRequestView.as_view(),
        name="portal-request",
    ),
    path(
        "tunnel-status/<uuid:tunnel_id>/",
        TunnelStatusView.as_view(),
        name="tunnel-status",
    ),
]
