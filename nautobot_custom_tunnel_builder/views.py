"""Views for the Custom Tunnel Builder app."""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import redirect, render
from django.views import View
from nautobot.extras.models import Job as JobModel
from nautobot.extras.models import JobResult

from .forms import IpsecTunnelForm

logger = logging.getLogger(__name__)

# Form sequence range: 2000-2999
_FORM_SEQ_MIN = 2000
_FORM_SEQ_MAX = 2999
_FORM_SEQ_STEP = 5


def _next_form_sequence():
    """Compute the next available crypto map sequence in the form range (2000-2999).

    Scans VPNProfiles for existing sequences in range, returns highest + 5.
    Falls back to 2000 if none exist.
    """
    try:
        from nautobot.vpn.models import VPNProfile  # pylint: disable=import-outside-toplevel

        profiles = VPNProfile.objects.all()
        sequences = [
            p._custom_field_data.get("custom_tunnel_builder_crypto_map_sequence", 0)  # pylint: disable=protected-access
            for p in profiles
        ]
        form_sequences = [s for s in sequences if isinstance(s, int) and _FORM_SEQ_MIN <= s <= _FORM_SEQ_MAX]
        if form_sequences:
            next_seq = max(form_sequences) + _FORM_SEQ_STEP
            return min(next_seq, _FORM_SEQ_MAX)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    return _FORM_SEQ_MIN


# Full dotted class-path Nautobot uses to look up the registered job.
JOB_CLASS_PATH = "nautobot_custom_tunnel_builder.jobs.BuildIpsecTunnel"


class IpsecTunnelBuilderView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """View to render the IPsec Tunnel Builder form and handle form submission."""

    permission_required = "extras.run_job"
    template_name = "nautobot_custom_tunnel_builder/ipsec_tunnel_form.html"

    # ------------------------------------------------------------------
    # GET – render empty form
    # ------------------------------------------------------------------

    def get(self, request):
        """Render the IPsec Tunnel Builder form with auto-computed sequence."""
        next_seq = _next_form_sequence()
        form = IpsecTunnelForm(initial={"crypto_map_sequence": next_seq})
        return render(request, self.template_name, self._ctx(form))

    # ------------------------------------------------------------------
    # POST – validate, enqueue job, redirect to job result
    # ------------------------------------------------------------------

    def post(self, request):
        """Validate form input, enqueue Job, redirect to JobResult. On error, re-render form with error message."""
        form = IpsecTunnelForm(request.POST)

        if not form.is_valid():
            messages.error(request, "Please correct the errors below.")
            return render(request, self.template_name, self._ctx(form))

        data = form.cleaned_data

        # Locate the registered job model in the database.
        try:
            job_model = JobModel.objects.get(
                module_name="nautobot_custom_tunnel_builder.jobs",
                job_class_name="BuildIpsecTunnel",
            )
        except JobModel.DoesNotExist:
            messages.error(
                request,
                "Job 'BuildIpsecTunnel' is not registered. "
                "Run 'nautobot-server migrate' and ensure the job is enabled under Jobs in the UI.",
            )
            return render(request, self.template_name, self._ctx(form))

        # Build the kwargs the Job.run() method expects.
        job_kwargs = {
            "device": data["device"],
            "ike_version": data["ike_version"],
            "remote_peer_ip": data["remote_peer_ip"],
            "local_network": data["local_network"],
            "remote_network": data["remote_network"],
            "crypto_acl_name": data["crypto_acl_name"],
            "crypto_map_name": data["crypto_map_name"],
            "crypto_map_sequence": data["crypto_map_sequence"],
            "ike_dh_group": data["ike_dh_group"],
            "ike_lifetime": data["ike_lifetime"],
            "isakmp_policy_priority": data.get("isakmp_policy_priority"),
            "ikev1_encryption": data.get("ikev1_encryption", ""),
            "ikev1_hash": data.get("ikev1_hash", ""),
            "ikev2_proposal_name": data.get("ikev2_proposal_name", ""),
            "ikev2_policy_name": data.get("ikev2_policy_name", ""),
            "ikev2_keyring_name": data.get("ikev2_keyring_name", ""),
            "ikev2_profile_name": data.get("ikev2_profile_name", ""),
            "ikev2_encryption": data.get("ikev2_encryption", ""),
            "ikev2_integrity": data.get("ikev2_integrity", ""),
            "pre_shared_key": data["pre_shared_key"],
            "ipsec_transform_set_name": data["ipsec_transform_set_name"],
            "ipsec_encryption": data["ipsec_encryption"],
            "ipsec_integrity": data["ipsec_integrity"],
            "ipsec_lifetime": data["ipsec_lifetime"],
        }

        try:
            job_result = JobResult.enqueue_job(
                job_model=job_model,
                user=request.user,
                **job_kwargs,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.exception("Failed to enqueue BuildIpsecTunnel job: %s", exc)
            messages.error(request, f"Failed to enqueue job: {exc}")
            return render(request, self.template_name, self._ctx(form))

        messages.success(
            request,
            f"{data['ike_version'].upper()} IPsec tunnel job queued for {data['device']}. "
            "Track progress in the job result below.",
        )
        return redirect(job_result.get_absolute_url())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ctx(form):
        return {
            "form": form,
            "title": "Build IPsec Tunnel",
            "active_tab": "ipsec_builder",
        }
