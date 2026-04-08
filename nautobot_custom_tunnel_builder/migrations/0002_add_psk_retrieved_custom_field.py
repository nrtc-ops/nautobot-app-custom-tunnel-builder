"""Add psk_retrieved boolean custom field to VPNProfile."""

from django.db import migrations


def add_psk_retrieved_cf(apps, schema_editor):
    """Add custom_tunnel_builder_psk_retrieved boolean CF on VPNProfile."""
    CustomField = apps.get_model("extras", "CustomField")
    ContentType = apps.get_model("contenttypes", "ContentType")

    vpnprofile_ct, _ = ContentType.objects.get_or_create(app_label="vpn", model="vpnprofile")

    cf, _ = CustomField.objects.get_or_create(
        key="custom_tunnel_builder_psk_retrieved",
        defaults={
            "label": "PSK Retrieved",
            "type": "boolean",
            "description": (
                "Set to True after the pre-shared key has been returned to the portal caller. "
                "Once set, the status endpoint will not re-expose the PSK."
            ),
            "grouping": "Custom Tunnel Builder",
            "weight": 300,
            "required": False,
            "default": False,
        },
    )
    cf.content_types.add(vpnprofile_ct)


def remove_psk_retrieved_cf(apps, schema_editor):
    """Reverse: delete the custom_tunnel_builder_psk_retrieved CF."""
    CustomField = apps.get_model("extras", "CustomField")
    CustomField.objects.filter(key="custom_tunnel_builder_psk_retrieved").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("nautobot_custom_tunnel_builder", "0001_create_custom_fields"),
        ("extras", "__latest__"),
        ("vpn", "__latest__"),
        ("contenttypes", "__latest__"),
    ]

    operations = [
        migrations.RunPython(
            add_psk_retrieved_cf,
            remove_psk_retrieved_cf,
        ),
    ]
