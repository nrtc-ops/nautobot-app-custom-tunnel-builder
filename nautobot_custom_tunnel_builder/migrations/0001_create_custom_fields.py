"""Create custom fields, DeviceType, and Manufacturer for the Custom Tunnel Builder app."""

from django.db import migrations


def create_custom_fields_and_device_type(apps, schema_editor):
    """Create 2 CustomField objects and a 'Member VPN Endpoint' DeviceType."""
    CustomField = apps.get_model("extras", "CustomField")
    ContentType = apps.get_model("contenttypes", "ContentType")
    Manufacturer = apps.get_model("dcim", "Manufacturer")
    DeviceType = apps.get_model("dcim", "DeviceType")

    # ------------------------------------------------------------------
    # DeviceType: "Member VPN Endpoint" with manufacturer "Generic"
    # ------------------------------------------------------------------
    manufacturer, _ = Manufacturer.objects.get_or_create(
        name="Generic",
        defaults={"description": "Generic/virtual manufacturer for placeholder devices."},
    )
    DeviceType.objects.get_or_create(
        model="Member VPN Endpoint",
        manufacturer=manufacturer,
    )

    # ------------------------------------------------------------------
    # Custom Fields
    # ------------------------------------------------------------------
    vpntunnelendpoint_ct, _ = ContentType.objects.get_or_create(app_label="vpn", model="vpntunnelendpoint")
    vpnprofile_ct, _ = ContentType.objects.get_or_create(app_label="vpn", model="vpnprofile")

    # 1. crypto_map_name on VPNTunnelEndpoint
    cf_crypto_map_name, _ = CustomField.objects.get_or_create(
        key="custom_tunnel_builder_crypto_map_name",
        defaults={
            "label": "Crypto Map Name",
            "type": "text",
            "description": "Device-wide crypto map name for the concentrator.",
            "grouping": "Custom Tunnel Builder",
            "weight": 100,
            "required": False,
            "default": "VPN",
        },
    )
    cf_crypto_map_name.content_types.add(vpntunnelendpoint_ct)

    # 2. crypto_map_sequence on VPNProfile
    cf_crypto_map_seq, _ = CustomField.objects.get_or_create(
        key="custom_tunnel_builder_crypto_map_sequence",
        defaults={
            "label": "Crypto Map Sequence",
            "type": "integer",
            "description": "Crypto map sequence number for this tunnel (starts at 3000, step 10).",
            "grouping": "Custom Tunnel Builder",
            "weight": 200,
            "required": False,
        },
    )
    cf_crypto_map_seq.content_types.add(vpnprofile_ct)


def remove_custom_fields_and_device_type(apps, schema_editor):
    """Reverse: delete custom fields and DeviceType. Leave Manufacturer (may be shared)."""
    CustomField = apps.get_model("extras", "CustomField")
    DeviceType = apps.get_model("dcim", "DeviceType")

    CustomField.objects.filter(
        key__in=[
            "custom_tunnel_builder_crypto_map_name",
            "custom_tunnel_builder_crypto_map_sequence",
        ]
    ).delete()

    DeviceType.objects.filter(model="Member VPN Endpoint").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("extras", "__latest__"),
        ("dcim", "__latest__"),
        ("vpn", "__latest__"),
        ("contenttypes", "__latest__"),
    ]

    operations = [
        migrations.RunPython(
            create_custom_fields_and_device_type,
            remove_custom_fields_and_device_type,
        ),
    ]
