"""Navigation menu items for the Custom Tunnel Builder app."""

from nautobot.apps.ui import NavMenuButton, NavMenuGroup, NavMenuItem, NavMenuTab

menu_items = (
    NavMenuTab(
        name="Network Tools",
        groups=(
            NavMenuGroup(
                name="VPN",
                items=(
                    NavMenuItem(
                        link="plugins:nautobot_custom_tunnel_builder:ipsec_tunnel_builder",
                        name="Build IPsec Tunnel",
                        permissions=["extras.run_job"],
                        buttons=(
                            NavMenuButton(
                                link="plugins:nautobot_custom_tunnel_builder:ipsec_tunnel_builder",
                                title="Build IPsec Tunnel",
                                icon_class="mdi mdi-vpn",
                                button_class="primary",
                                permissions=["extras.run_job"],
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
)
