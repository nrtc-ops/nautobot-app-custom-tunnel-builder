"""URL configuration for the IPsec Tunnel Builder app."""

from django.urls import path

from .views import IpsecTunnelBuilderView

app_name = "nautobot_ipsec_builder"

urlpatterns = [
    path(
        "",
        IpsecTunnelBuilderView.as_view(),
        name="ipsec_tunnel_builder",
    ),
]
