"""URL configuration for the IPsec Tunnel Builder app."""

from django.urls import include, path

from .views import IpsecTunnelBuilderView

app_name = "nautobot_custom_tunnel_builder"

urlpatterns = [
    path(
        "",
        IpsecTunnelBuilderView.as_view(),
        name="ipsec_tunnel_builder",
    ),
    path(
        "api/",
        include("nautobot_custom_tunnel_builder.api.urls"),
    ),
]
