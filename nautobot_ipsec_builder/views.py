"""Views for the IPsec Tunnel Builder app."""

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import redirect, render
from django.views import View

from nautobot.extras.models import Job as JobModel, JobResult

from .forms import IpsecTunnelForm

logger = logging.getLogger(__name__)

# Full dotted class-path Nautobot uses to look up the registered job.
JOB_CLASS_PATH = "nautobot_ipsec_builder.jobs.BuildIpsecTunnel"


class IpsecTunnelBuilderView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Custom view that renders the IPsec Tunnel Builder form and, on a valid
    POST, enqueues the ``BuildIpsecTunnel`` Nautobot Job.

    Permission required: ``extras.run_job``
    """

    permission_required = "extras.run_job"
    template_name = "nautobot_ipsec_builder/ipsec_tunnel_form.html"

    # ------------------------------------------------------------------
    # GET – render empty form
    # ------------------------------------------------------------------

    def get(self, request):
        form = IpsecTunnelForm()
        return render(request, self.template_name, self._ctx(form))

    # ------------------------------------------------------------------
    # POST – validate, enqueue job, redirect to job result
    # ------------------------------------------------------------------

    def post(self, request):
        form = IpsecTunnelForm(request.POST)

        if not form.is_valid():
            messages.error(request, "Please correct the errors below.")
            return render(request, self.template_name, self._ctx(form))

        data = form.cleaned_data

        # Locate the registered job model in the database.
        try:
            job_model = JobModel.objects.get(job_class_name="BuildIpsecTunnel")
        except JobModel.DoesNotExist:
            messages.error(
                request,
                "Job 'BuildIpsecTunnel' is not registered. "
                "Make sure the app is installed and 'nautobot-server migrate' has been run.",
            )
            return render(request, self.template_name, self._ctx(form))

        # Build the kwargs the Job.run() method expects.
        job_kwargs = {
            "device": data["device"],
            "tunnel_number": data["tunnel_number"],
            "tunnel_source_interface": data["tunnel_source_interface"],
            "tunnel_ip_address": data["tunnel_ip_address"],
            "remote_peer_ip": data["remote_peer_ip"],
            "ikev2_proposal_name": data["ikev2_proposal_name"],
            "ikev2_policy_name": data["ikev2_policy_name"],
            "ikev2_keyring_name": data["ikev2_keyring_name"],
            "ikev2_profile_name": data["ikev2_profile_name"],
            "ike_encryption": data["ike_encryption"],
            "ike_integrity": data["ike_integrity"],
            "ike_dh_group": data["ike_dh_group"],
            "ike_lifetime": data["ike_lifetime"],
            "ipsec_transform_set_name": data["ipsec_transform_set_name"],
            "ipsec_profile_name": data["ipsec_profile_name"],
            "ipsec_encryption": data["ipsec_encryption"],
            "ipsec_integrity": data["ipsec_integrity"],
            "ipsec_lifetime": data["ipsec_lifetime"],
            "pre_shared_key": data["pre_shared_key"],
        }

        try:
            job_result = JobResult.enqueue_job(
                job_model=job_model,
                user=request.user,
                **job_kwargs,
            )
        except Exception as exc:
            logger.exception("Failed to enqueue BuildIpsecTunnel job: %s", exc)
            messages.error(request, f"Failed to enqueue job: {exc}")
            return render(request, self.template_name, self._ctx(form))

        messages.success(
            request,
            f"IPsec tunnel job queued for {data['device']}. "
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
