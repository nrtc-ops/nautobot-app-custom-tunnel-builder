"""Add the member_connect_request_id custom field to VPNTunnel.

The Member Connect portal's `rake nautobot:bootstrap` creates the same custom
field keyed "member_connect_request_id"; both sides use get_or_create by key,
so whichever runs first wins and the other is a no-op.
"""

from django.db import migrations


def add_member_connect_request_id_cf(apps, schema_editor):
    """Add member_connect_request_id text CF on VPNTunnel (idempotent)."""
    CustomField = apps.get_model("extras", "CustomField")
    ContentType = apps.get_model("contenttypes", "ContentType")

    vpntunnel_ct, _ = ContentType.objects.get_or_create(app_label="vpn", model="vpntunnel")

    cf, _ = CustomField.objects.get_or_create(
        key="member_connect_request_id",
        defaults={
            "label": "Member Connect Request ID",
            "type": "text",
            "description": (
                "Idempotency key: UUID of the Member Connect portal VpnRequest "
                "that created this tunnel."
            ),
            "grouping": "Member Connect",
            "weight": 400,
            "required": False,
        },
    )
    cf.content_types.add(vpntunnel_ct)


class Migration(migrations.Migration):
    dependencies = [
        ("nautobot_custom_tunnel_builder", "0002_add_psk_retrieved_custom_field"),
        ("extras", "__latest__"),
        ("vpn", "__latest__"),
        ("contenttypes", "__latest__"),
    ]

    operations = [
        migrations.RunPython(
            add_member_connect_request_id_cf,
            # Intentionally no reverse delete: the portal bootstrap may co-own this CF.
            migrations.RunPython.noop,
        ),
    ]
