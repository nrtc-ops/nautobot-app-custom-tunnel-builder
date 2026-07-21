"""Tests for the IPsec Tunnel Builder UI view."""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from nautobot.extras.models import Job as JobModel

from ..jobs import BuildIpsecTunnel
from .test_api import _create_test_device

User = get_user_model()

FORM_URL = "/plugins/tunnel-builder/"


def _valid_form_data(device):
    """Minimal valid IKEv2 POST body; clean() auto-generates the naming fields."""
    return {
        "member_name": "acme-corp",
        "device": str(device.pk),
        "ike_version": "ikev2",
        "remote_peer_ip": "203.0.113.1",
        "local_network": "10.100.0.0/24",
        "remote_network": "192.168.1.0/24",
        "crypto_map_name": "VPN",
        "crypto_map_sequence": 2000,
        "ike_dh_group": "19",
        "ike_lifetime": 86400,
        "ikev2_encryption": "aes-cbc-256",
        "ikev2_integrity": "sha256",
        "pre_shared_key": "test-psk-for-view-test",
        "ipsec_encryption": "esp-aes 256",
        "ipsec_integrity": "esp-sha256-hmac",
        "ipsec_lifetime": 3600,
    }


class IpsecTunnelBuilderViewTest(TestCase):
    """The form view must enqueue BuildIpsecTunnel with worker-deserializable kwargs.

    Passing model instances straight into JobResult.enqueue_job breaks kwarg
    deserialization on the worker (uuid.UUID(<Device>) → RunJobTaskFailed),
    which is why core always routes cleaned_data through Job.serialize_data.
    The oracle here is the worker's own deserialize_data: whatever the view
    enqueues must round-trip through it.
    """

    @classmethod
    def setUpTestData(cls):
        cls.device = _create_test_device()
        cls.job_model = JobModel.objects.get(
            module_name="nautobot_custom_tunnel_builder.jobs",
            job_class_name="BuildIpsecTunnel",
        )
        cls.job_model.enabled = True
        cls.job_model.save()

    def setUp(self):
        self.user = User.objects.create_superuser(username="form-tester", password="testpass")
        self.client.force_login(self.user)

    @patch("nautobot_custom_tunnel_builder.views.JobResult.enqueue_job")
    def test_submit_enqueues_worker_deserializable_kwargs(self, mock_enqueue):
        """A valid POST redirects to the JobResult and enqueues kwargs deserialize_data can round-trip."""
        mock_enqueue.return_value = MagicMock(get_absolute_url=lambda: "/extras/job-results/fake-pk/")

        response = self.client.post(FORM_URL, data=_valid_form_data(self.device))

        self.assertEqual(response.status_code, 302, "Expected redirect to the JobResult page.")
        mock_enqueue.assert_called_once()

        enqueued_kwargs = dict(mock_enqueue.call_args.kwargs)
        enqueued_kwargs.pop("job_model")
        enqueued_kwargs.pop("user")

        deserialized = BuildIpsecTunnel().deserialize_data(enqueued_kwargs)
        self.assertEqual(deserialized["device"], self.device)
