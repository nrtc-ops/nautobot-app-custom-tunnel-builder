# Portal Contract Completion — Tunnel Builder Plugin (feature/portal-api)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the plugin side of the portal ↔ tunnel-builder contract — make the 12 committed-red API tests green, add PSK-once status semantics, `member_connect_request_id` idempotency, dev-bypass/sequence hardening, and an idempotent local E2E seed harness.

**Architecture:** `PortalTunnelRequestView` (DRF `APIView` at `/plugins/tunnel-builder/api/portal-request/`) validates a portal payload, builds the native Nautobot VPN hierarchy (VPN → cloned VPNProfile + Secret/SecretsGroup → VPNTunnel born **Planned** → hub/spoke `VPNTunnelEndpoint`s), and enqueues `PortalBuildIpsecTunnel`, which pushes IOS-XE config via Netmiko and flips the tunnel Active/Decommissioning. `TunnelStatusView` is polled by the Rails portal and releases the PSK exactly once, gated by the `custom_tunnel_builder_psk_retrieved` custom field. The hub's protected prefix now comes from a pre-configured hub `VPNTunnelEndpoint` (device + role "Hub"), never from the request.

**Tech Stack:** Nautobot app (Django 5.2 / DRF), PostgreSQL (dev compose), Celery worker, Netmiko, 1Password SDK (with file-based dev bypass), Docker Compose dev environment driven by `invoke` + poetry, fake-cisco SSH stub container.

## Global Constraints

- Nautobot `>=3.0.0,<4.0.0`; Python `>=3.11,<3.14` (dev containers run 3.12). Nautobot 3.x idioms only: `Location` (no Site), content-type-scoped `Role`/`Status`, `IPAddressToInterface` for IP↔interface.
- All tests run inside the docker dev stack via invoke. Exact command:
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label <dotted.test.path>
  ```
  which executes `nautobot-server test <label> --keepdb --buffer` in the `nautobot` compose service (`run_command` starts a one-off container if the stack is down; `poetry run invoke start` first is faster). Full suite: `poetry run invoke unittest --skip-docs-build --keepdb`.
- The Nautobot test runner excludes `@tag("integration")` tests by default; the fake-cisco SSH test is run explicitly in the final task.
- Strict TDD: failing test first, minimal implementation, re-run, then commit. One commit per task.
- Work directly on branch `feature/portal-api` (already checked out, working tree clean).
- Never log or return the PSK anywhere except the single gated status response; keep the existing `***REDACTED***` conventions.

---

### Task 1: Finish the `PortalTunnelRequestView` / `_create_tunnel_hierarchy` refactor

**Files:**
- Modify: `nautobot_custom_tunnel_builder/api/views.py` — `_get_or_create_member_device` (lines 38–102), `PortalTunnelRequestView.post` (lines 179–279), `_create_tunnel_hierarchy` (lines 281–422)
- Modify: `nautobot_custom_tunnel_builder/tests/test_api.py` — new helper + 3 new tests; amend `test_active_tunnel_returns_psk` (lines 511–534)

**Interfaces:**
- Consumes: `PortalTunnelRequestSerializer.validated_data` — already has `member_protected_prefixes: list[str]` and **no** `hub_protected_prefix` (`api/serializers.py:63-67`); `store_psk_in_1password(psk, member_name, loc_slug, next_seq) -> str`.
- Produces: `_create_tunnel_hierarchy(device, template, member_name, member_display, city, state, loc_slug, display_location, remote_peer_ip, hub_endpoint, member_prefix_cidrs, vpn_name) -> (VPNTunnel, VPN)` — tunnel status **Planned**, `endpoint_z` = pre-existing hub endpoint, spoke gets one protected prefix per list entry, member interface named `peer-<ip-with-dashes>`.

**Steps:**

- [ ] Run the existing failing tests to confirm the red baseline:
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_api
  ```
  Expected: 12 errors, each an unhandled `KeyError: 'hub_protected_prefix'` raised from `api/views.py:192` (`data["hub_protected_prefix"]` — the serializer no longer defines that field). The 12: all 8 `PortalTunnelCreationTest` tests, `TunnelStatusTest.test_active_tunnel_returns_psk`, and all 3 `EndToEndConfigGenerationTest` tests.
- [ ] Add a status helper and three new failing tests to `tests/test_api.py`. Insert the helper after `_create_hub_endpoint` (line 167):
  ```python
  def _ensure_vpntunnel_statuses():
      """Ensure Planned and Decommissioning statuses are mapped to VPNTunnel."""
      from django.contrib.contenttypes.models import ContentType  # pylint: disable=import-outside-toplevel

      vpntunnel_ct = ContentType.objects.get_for_model(VPNTunnel)
      for status_name in ("Planned", "Decommissioning"):
          st, _ = Status.objects.get_or_create(name=status_name)
          st.content_types.add(vpntunnel_ct)
  ```
  Call `_ensure_vpntunnel_statuses()` at the end of `setUpTestData` in **both** `PortalTunnelCreationTest` and `EndToEndConfigGenerationTest`. Then add to `PortalTunnelCreationTest`:
  ```python
      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_tunnel_created_with_planned_status(self, _mock_op):
          """New tunnels are born Planned; the build job flips them Active."""
          payload = _valid_payload(self.device, self.template_profile)
          response = self._post(PORTAL_REQUEST_URL, payload)
          self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
          tunnel = VPNTunnel.objects.get(pk=response.json()["tunnel_id"])
          self.assertEqual(tunnel.status.name, "Planned")

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_missing_hub_endpoint_returns_400(self, _mock_op):
          """A device with no pre-configured hub endpoint yields 400, not 500."""
          bare_device = _create_test_device(name="no-hub-endpoint-router")
          payload = _valid_payload(bare_device, self.template_profile)
          response = self._post(PORTAL_REQUEST_URL, payload)
          self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
          self.assertIn("device", response.json())
          self.assertIn("hub", response.json()["device"][0].lower())

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_hub_endpoint_without_prefix_returns_400(self, _mock_op):
          """A hub endpoint with no protected prefix yields 400, not 500."""
          bare_device = _create_test_device(name="no-prefix-hub-router")
          hub_endpoint = _create_hub_endpoint(bare_device)
          hub_endpoint.protected_prefixes.clear()
          payload = _valid_payload(bare_device, self.template_profile)
          response = self._post(PORTAL_REQUEST_URL, payload)
          self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
          self.assertIn("device", response.json())
          self.assertIn("protected prefix", response.json()["device"][0])
  ```
- [ ] Amend `TunnelStatusTest.test_active_tunnel_returns_psk` (lines 511–534) for born-Planned tunnels: after the 202 assertion, insert (before the `GET`):
  ```python
          tunnel_id = post_response.json()["tunnel_id"]
          # Simulate a successful PortalBuildIpsecTunnel run: the job flips Planned → Active.
          tunnel = VPNTunnel.objects.get(pk=tunnel_id)
          tunnel.status = Status.objects.get_for_model(VPNTunnel).get(name="Active")
          tunnel.save()
  ```
  and add `_ensure_vpntunnel_statuses()` right after `_create_hub_endpoint(device)` in that test. (This test stays red until Task 2 — it is Task 2's driver.)
- [ ] Run again — expected: still red, `KeyError: 'hub_protected_prefix'` on all creation paths plus the 3 new failures:
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_api
  ```
- [ ] Implement the view refactor. In `api/views.py`, change the interface name in `_get_or_create_member_device` (replaces the `dummy0` block at lines 63–68):
  ```python
      intf_status = Status.objects.get_for_model(Interface).get(name="Active")
      interface_name = f"peer-{remote_peer_ip.replace('.', '-')}"
      interface, _ = Interface.objects.get_or_create(
          device=device,
          name=interface_name,
          defaults={"type": "virtual", "status": intf_status},
      )
  ```
  Replace `PortalTunnelRequestView.post` (lines 179–240 through the hierarchy call) with:
  ```python
      def post(self, request):  # pylint: disable=too-many-locals,too-many-return-statements
          """Validate, create VPN object hierarchy, enqueue build job, return 202."""
          serializer = PortalTunnelRequestSerializer(data=request.data)
          serializer.is_valid(raise_exception=True)

          data = serializer.validated_data
          device = data["device"]
          template = data["template_vpn_profile"]
          remote_peer_ip = str(data["remote_peer_ip"])
          member_name = data["member_name"]
          member_display = data["member_display_name"]
          city = data["location_city"]
          state = data["location_state"]
          member_prefix_cidrs = data["member_protected_prefixes"]

          loc_slug = _location_slug(city, state)
          display_location = f"{city}, {state.upper()}"

          # -------------------------------------------------------------- #
          # Hub endpoint pre-check. The hub protected prefix comes from the  #
          # pre-configured hub VPNTunnelEndpoint, never from the request.    #
          # -------------------------------------------------------------- #
          hub_endpoint = VPNTunnelEndpoint.objects.filter(device=device, role__name="Hub").first()
          if hub_endpoint is None:
              return Response(
                  {
                      "device": [
                          f"Device '{device.name}' has no pre-configured hub VPN tunnel endpoint "
                          "(role 'Hub'). An administrator must create one with a protected prefix "
                          "before tunnels can be requested."
                      ]
                  },
                  status=status.HTTP_400_BAD_REQUEST,
              )
          if not hub_endpoint.protected_prefixes.exists():
              return Response(
                  {
                      "device": [
                          f"The hub endpoint on device '{device.name}' has no protected prefix. "
                          "An administrator must add one before tunnels can be requested."
                      ]
                  },
                  status=status.HTTP_400_BAD_REQUEST,
              )

          # -------------------------------------------------------------- #
          # Duplicate check (same member+location VPN, same remote peer)     #
          # -------------------------------------------------------------- #
          vpn_name = f"vpn-nrtc-ms-{member_name}-{loc_slug}-001"
          existing_vpn = VPN.objects.filter(vpn_id=vpn_name).first()
          if existing_vpn:
              for tun in existing_vpn.vpn_tunnels.all():
                  spoke = tun.endpoint_a
                  if spoke and spoke.source_ipaddress and str(spoke.source_ipaddress.address.ip) == remote_peer_ip:
                      return Response(
                          {
                              "detail": "A tunnel with these parameters already exists.",
                              "tunnel_id": str(tun.pk),
                          },
                          status=status.HTTP_409_CONFLICT,
                      )

          # -------------------------------------------------------------- #
          # Create full object hierarchy inside a transaction                #
          # -------------------------------------------------------------- #
          try:
              tunnel, vpn = self._create_tunnel_hierarchy(
                  device,
                  template,
                  member_name,
                  member_display,
                  city,
                  state,
                  loc_slug,
                  display_location,
                  remote_peer_ip,
                  hub_endpoint,
                  member_prefix_cidrs,
                  vpn_name,
              )
          except Exception:  # pylint: disable=broad-exception-caught
              logger.exception("Failed to create tunnel for member '%s'.", member_name)
              return Response(
                  {"detail": "Failed to create tunnel. Contact an administrator."},
                  status=status.HTTP_500_INTERNAL_SERVER_ERROR,
              )
  ```
  (the job-enqueue and 202-response blocks at lines 242–279 are unchanged). Replace `_create_tunnel_hierarchy` (lines 281–422) with:
  ```python
      @staticmethod
      def _create_tunnel_hierarchy(  # pylint: disable=too-many-locals,too-many-arguments
          device,
          template,
          member_name,
          member_display,
          city,
          state,
          loc_slug,
          display_location,
          remote_peer_ip,
          hub_endpoint,
          member_prefix_cidrs,
          vpn_name,
      ):
          """Create the full VPN object hierarchy inside an atomic transaction.

          The tunnel is created with status "Planned"; PortalBuildIpsecTunnel flips
          it to Active on a successful push, Decommissioning on failure.

          Returns:
              Tuple of (tunnel, vpn).

          Raises:
              Exception: If any step fails (1Password, DB, etc.), the transaction rolls back.
          """
          with transaction.atomic():
              # 1. Location
              location_obj = _get_or_create_location(city, state)

              # 2. Member Device + per-peer interface + IP
              member_device, member_ip = _get_or_create_member_device(
                  member_name,
                  loc_slug,
                  remote_peer_ip,
                  location_obj,
              )

              # 3. VPN (get_or_create by member+location)
              vpn, _ = VPN.objects.get_or_create(
                  vpn_id=vpn_name,
                  defaults={
                      "name": f"{member_display} - {display_location}",
                  },
              )

              # 4. Calculate next crypto map sequence for this device.
              existing_tunnels = VPNTunnel.objects.select_for_update(of=("self",)).filter(
                  endpoint_z__device=device,
              ).select_related("vpn_profile")
              sequences = [
                  t.vpn_profile._custom_field_data.get(  # pylint: disable=protected-access
                      "custom_tunnel_builder_crypto_map_sequence", 0
                  )
                  for t in existing_tunnels
                  if t.vpn_profile
              ]
              max_seq = max(sequences) if sequences else None
              next_seq = (max_seq + 10) if max_seq is not None else 3000

              # 5. Generate PSK
              psk = secrets.token_urlsafe(32)

              # 6. Store PSK in 1Password.
              # NOTE: external call inside transaction.atomic() — orphaned items are
              # identifiable by name pattern vpn-psk-nrtc-ms-{member}-{loc_slug}-{seq}.
              # TODO: two-phase commit (logged fast-follow).
              op_item_id = store_psk_in_1password(psk, member_name, loc_slug, next_seq)

              # 7. Nautobot Secret + SecretsGroup for this tunnel's PSK
              _secret_provider, _secret_params = get_secret_provider_params(op_item_id)
              tunnel_secret = Secret.objects.create(
                  name=f"vpn-psk-nrtc-ms-{member_name}-{loc_slug}-{next_seq}",
                  provider=_secret_provider,
                  parameters=_secret_params,
              )
              tunnel_sg = SecretsGroup.objects.create(
                  name=f"vpn-sg-nrtc-ms-{member_name}-{loc_slug}-{next_seq}",
              )
              tunnel_sg.secrets.add(tunnel_secret)

              # 8. Clone template VPNProfile
              profile_name = f"vpnprofile-nrtc-ms-{member_name}-{loc_slug}-{next_seq}"
              profile = _clone_vpn_profile(template, profile_name, next_seq)
              profile.secrets_group = tunnel_sg
              profile.save()

              # 9. Create VPNTunnel — born Planned.
              tunnel_name = f"{member_display} - {display_location} - {next_seq}"
              tunnel_id_str = f"vpn-tunnel-nrtc-ms-{member_name}-{loc_slug}-{next_seq}"
              tunnel_status = Status.objects.get_for_model(VPNTunnel).get(name="Planned")
              tunnel = VPNTunnel.objects.create(
                  name=tunnel_name,
                  tunnel_id=tunnel_id_str,
                  status=tunnel_status,
                  vpn=vpn,
                  vpn_profile=profile,
              )

              # 10. Attach the pre-configured hub endpoint (endpoint_z).
              tunnel.endpoint_z = hub_endpoint

              # 11. Spoke VPNTunnelEndpoint (endpoint_a) — one protected prefix
              # association per entry in member_protected_prefixes.
              spoke_role, _ = Role.objects.get_or_create(name="Spoke")
              spoke_endpoint = VPNTunnelEndpoint.objects.create(
                  name=f"{member_name}-{loc_slug}",
                  role=spoke_role,
                  device=member_device,
                  source_ipaddress=member_ip,
              )
              for cidr in member_prefix_cidrs:
                  spoke_endpoint.protected_prefixes.add(_get_or_create_prefix(cidr))
              tunnel.endpoint_a = spoke_endpoint
              tunnel.save()

          return tunnel, vpn
  ```
- [ ] Run the API tests:
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_api
  ```
  Expected: everything green **except** `TunnelStatusTest.test_active_tunnel_returns_psk` (fails on `self.assertIn("pre_shared_key", data)` — that is Task 2). Also confirm no regression in the job/config suites:
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_portal_job
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_config_generation
  ```
- [ ] Commit:
  ```bash
  git add nautobot_custom_tunnel_builder/api/views.py nautobot_custom_tunnel_builder/tests/test_api.py
  git commit -m "feat(api): hub prefix from pre-configured hub endpoint, per-peer interface, multi-prefix spoke, tunnels born Planned"
  ```

---

### Task 2: Status endpoint returns the PSK exactly once

**Files:**
- Modify: `nautobot_custom_tunnel_builder/api/views.py` — `TunnelStatusView.get` (lines 431–447 pre-task)
- Modify: `nautobot_custom_tunnel_builder/tests/test_api.py` — rewrite `TunnelStatusTest` (lines 497–534 pre-task)

**Interfaces:**
- Consumes: `custom_tunnel_builder_psk_retrieved` boolean CF on `VPNProfile` (migration `0002_add_psk_retrieved_custom_field.py`, currently unused); `Secret.get_value() -> str` via `tunnel.vpn_profile.secrets_group.secrets.first()` (same path `PortalBuildIpsecTunnel` uses at `jobs.py:679-689`).
- Produces: `GET /plugins/tunnel-builder/api/tunnel-status/<uuid>/` → `{"tunnel_id", "tunnel_name", "status"}` always; plus `"pre_shared_key"` iff status is Active and the CF is falsy, after which the CF is set true and persisted.

**Steps:**

- [ ] Replace `TunnelStatusTest` in `tests/test_api.py` with this class (the amended `test_active_tunnel_returns_psk` from Task 1 folds into the new helpers; three tests are new and red):
  ```python
  class TunnelStatusTest(APITestCase):  # pylint: disable=too-many-ancestors
      """Test the tunnel-status endpoint, including PSK-once semantics."""

      def _get(self, url):
          return self.client.get(url, **self.header)

      def _post_tunnel(self, member_name, peer_ip):
          """Provision a tunnel via the portal API; returns its tunnel_id (status Planned)."""
          device = _create_test_device(name=f"{member_name}-router")
          template = _create_template_vpn_profile()
          manufacturer, _ = Manufacturer.objects.get_or_create(name="Generic")
          DeviceType.objects.get_or_create(model="Member VPN Endpoint", manufacturer=manufacturer)
          LocationType.objects.get_or_create(name="Site")
          _create_hub_endpoint(device)
          _ensure_vpntunnel_statuses()
          payload = _valid_payload(device, template)
          payload["member_name"] = member_name
          payload["remote_peer_ip"] = peer_ip
          response = self.client.post(PORTAL_REQUEST_URL, data=payload, format="json", **self.header)
          self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
          return response.json()["tunnel_id"]

      @staticmethod
      def _activate(tunnel_id):
          """Simulate a successful PortalBuildIpsecTunnel run: flip Planned → Active."""
          tunnel = VPNTunnel.objects.get(pk=tunnel_id)
          tunnel.status = Status.objects.get_for_model(VPNTunnel).get(name="Active")
          tunnel.save()

      def test_non_existent_tunnel_returns_404(self):
          """GET with a UUID that doesn't match any VPNTunnel returns 404."""
          fake_uuid = uuid.uuid4()
          response = self._get(TUNNEL_STATUS_URL_TEMPLATE.format(fake_uuid))
          self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
          data = response.json()
          self.assertTrue("error" in data or "detail" in data)

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-psk-test")
      @patch("nautobot.extras.models.Secret.get_value", return_value="TestPSKReturnedOnce!")
      def test_active_tunnel_returns_psk(self, _mock_get_value, _mock_op):
          """Status endpoint returns pre_shared_key when tunnel is Active."""
          tunnel_id = self._post_tunnel("psk-test-member", "203.0.113.77")
          self._activate(tunnel_id)
          response = self._get(TUNNEL_STATUS_URL_TEMPLATE.format(tunnel_id))
          self.assertEqual(response.status_code, status.HTTP_200_OK)
          data = response.json()
          self.assertEqual(data["status"], "Active")
          self.assertIn("pre_shared_key", data)
          self.assertEqual(data["pre_shared_key"], "TestPSKReturnedOnce!")

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-psk-test")
      @patch("nautobot.extras.models.Secret.get_value", return_value="TestPSKReturnedOnce!")
      def test_planned_tunnel_does_not_include_psk(self, _mock_get_value, _mock_op):
          """A Planned (not yet built) tunnel never exposes the PSK."""
          tunnel_id = self._post_tunnel("psk-planned-member", "203.0.113.78")
          response = self._get(TUNNEL_STATUS_URL_TEMPLATE.format(tunnel_id))
          self.assertEqual(response.status_code, status.HTTP_200_OK)
          data = response.json()
          self.assertEqual(data["status"], "Planned")
          self.assertNotIn("pre_shared_key", data)

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-psk-test")
      @patch("nautobot.extras.models.Secret.get_value", return_value="TestPSKReturnedOnce!")
      def test_first_active_poll_flips_psk_retrieved_flag(self, _mock_get_value, _mock_op):
          """The first Active poll sets custom_tunnel_builder_psk_retrieved on the profile."""
          tunnel_id = self._post_tunnel("psk-flip-member", "203.0.113.79")
          self._activate(tunnel_id)
          response = self._get(TUNNEL_STATUS_URL_TEMPLATE.format(tunnel_id))
          self.assertIn("pre_shared_key", response.json())
          tunnel = VPNTunnel.objects.get(pk=tunnel_id)
          tunnel.vpn_profile.refresh_from_db()
          self.assertTrue(
              tunnel.vpn_profile._custom_field_data["custom_tunnel_builder_psk_retrieved"]  # pylint: disable=protected-access
          )

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-psk-test")
      @patch("nautobot.extras.models.Secret.get_value", return_value="TestPSKReturnedOnce!")
      def test_second_poll_omits_psk(self, _mock_get_value, _mock_op):
          """The PSK is offered exactly once; the second Active poll omits it."""
          tunnel_id = self._post_tunnel("psk-once-member", "203.0.113.80")
          self._activate(tunnel_id)
          first = self._get(TUNNEL_STATUS_URL_TEMPLATE.format(tunnel_id))
          self.assertIn("pre_shared_key", first.json())
          second = self._get(TUNNEL_STATUS_URL_TEMPLATE.format(tunnel_id))
          self.assertEqual(second.status_code, status.HTTP_200_OK)
          data = second.json()
          self.assertEqual(data["status"], "Active")
          self.assertNotIn("pre_shared_key", data)
  ```
- [ ] Run — expected: `test_active_tunnel_returns_psk`, `test_first_active_poll_flips_psk_retrieved_flag`, and `test_second_poll_omits_psk` fail (`'pre_shared_key' not found`, `KeyError: 'custom_tunnel_builder_psk_retrieved'`); the Planned test passes already:
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_api.TunnelStatusTest
  ```
- [ ] Implement — replace `TunnelStatusView.get` in `api/views.py`:
  ```python
      def get(self, request, tunnel_id):
          """Return tunnel status; include the PSK exactly once when Active."""
          try:
              tunnel = VPNTunnel.objects.get(pk=tunnel_id)
          except VPNTunnel.DoesNotExist:
              return Response(
                  {"detail": "Tunnel not found."},
                  status=status.HTTP_404_NOT_FOUND,
              )

          payload = {
              "tunnel_id": str(tunnel.pk),
              "tunnel_name": tunnel.name,
              "status": tunnel.status.name,
          }

          profile = tunnel.vpn_profile
          if tunnel.status.name == "Active" and profile is not None:
              already_retrieved = profile._custom_field_data.get(  # pylint: disable=protected-access
                  "custom_tunnel_builder_psk_retrieved"
              )
              if not already_retrieved:
                  secret = profile.secrets_group.secrets.first() if profile.secrets_group else None
                  if secret:
                      try:
                          payload["pre_shared_key"] = secret.get_value()
                      except Exception:  # pylint: disable=broad-exception-caught
                          logger.exception("Failed to retrieve PSK for tunnel '%s'.", tunnel.name)
                      else:
                          profile._custom_field_data["custom_tunnel_builder_psk_retrieved"] = True  # pylint: disable=protected-access
                          profile.save()

          return Response(payload)
  ```
- [ ] Run again — expected: all of `test_api` green (the last of the original 12 included):
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_api
  ```
- [ ] Commit:
  ```bash
  git add nautobot_custom_tunnel_builder/api/views.py nautobot_custom_tunnel_builder/tests/test_api.py
  git commit -m "feat(api): tunnel-status returns PSK exactly once when Active, gated by psk_retrieved custom field"
  ```

---

### Task 3: Idempotency via `member_connect_request_id`

**Files:**
- Create: `nautobot_custom_tunnel_builder/migrations/0003_add_member_connect_request_id_custom_field.py`
- Modify: `nautobot_custom_tunnel_builder/api/serializers.py` — add field after `member_protected_prefixes` (line 67)
- Modify: `nautobot_custom_tunnel_builder/api/views.py` — dedupe in `post`, stamp in `_create_tunnel_hierarchy`
- Modify: `nautobot_custom_tunnel_builder/tests/test_api.py` — `REQUIRED_FIELDS` (lines 43–52), `_valid_payload` (lines 170–181), 4 new tests

**Interfaces:**
- Consumes: the Rails portal sends `member_connect_request_id: req.id.to_s` (`member-connect-portal/app/jobs/nautobot_provision_job.rb:57`) and its bootstrap defines `{key: "member_connect_request_id", type: "text", content_types: ["vpn.tunnel"]}` (`lib/tasks/nautobot_bootstrap.rb:14`). Both sides find-or-create **by key**, so no conflict whichever runs first. (Note for the portal repo: the actual ContentType string is `vpn.vpntunnel` — the model class is `VPNTunnel`; the bootstrap's `"vpn.tunnel"` will 400 against the CF API and should be fixed portal-side. This migration makes the plugin authoritative either way.)
- Produces: required serializer field `member_connect_request_id: CharField(max_length=64)`; `409 {"detail", "tunnel_id"}` on replay, checked **before** the name+peer duplicate check; CF stamped on every created tunnel; `_create_tunnel_hierarchy` gains a trailing `request_id` parameter.

**Steps:**

- [ ] Make the tests demand the field. In `tests/test_api.py` update:
  ```python
  REQUIRED_FIELDS = (
      "member_name",
      "member_display_name",
      "location_city",
      "location_state",
      "device",
      "template_vpn_profile",
      "remote_peer_ip",
      "member_protected_prefixes",
      "member_connect_request_id",
  )
  ```
  ```python
  def _valid_payload(device, template_profile, request_id=None):
      """Return a valid portal request payload with a fresh idempotency key."""
      return {
          "member_name": "acme-corp",
          "member_display_name": "Acme Corp",
          "location_city": "Jackson",
          "location_state": "MS",
          "device": str(device.pk),
          "template_vpn_profile": str(template_profile.pk),
          "remote_peer_ip": "203.0.113.50",
          "member_protected_prefixes": ["192.168.1.0/24"],
          "member_connect_request_id": request_id or str(uuid.uuid4()),
      }
  ```
  and add these to `PortalTunnelCreationTest`:
  ```python
      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_missing_request_id_returns_400(self, _mock_op):
          """member_connect_request_id is required."""
          payload = _valid_payload(self.device, self.template_profile)
          del payload["member_connect_request_id"]
          response = self._post(PORTAL_REQUEST_URL, payload)
          self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
          self.assertIn("member_connect_request_id", response.json())

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_request_id_stamped_on_tunnel(self, _mock_op):
          """The idempotency key is stored as a custom field on the created tunnel."""
          payload = _valid_payload(self.device, self.template_profile)
          response = self._post(PORTAL_REQUEST_URL, payload)
          self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
          tunnel = VPNTunnel.objects.get(pk=response.json()["tunnel_id"])
          self.assertEqual(
              tunnel._custom_field_data["member_connect_request_id"],  # pylint: disable=protected-access
              payload["member_connect_request_id"],
          )

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_duplicate_request_id_returns_409_with_original_tunnel(self, _mock_op):
          """A replay with the same request id returns 409 + the original tunnel_id,
          even when other parameters differ."""
          payload = _valid_payload(self.device, self.template_profile)
          resp1 = self._post(PORTAL_REQUEST_URL, payload)
          self.assertEqual(resp1.status_code, status.HTTP_202_ACCEPTED)
          payload2 = dict(payload, remote_peer_ip="203.0.113.51")
          resp2 = self._post(PORTAL_REQUEST_URL, payload2)
          self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
          body = resp2.json()
          self.assertIn("detail", body)
          self.assertEqual(body["tunnel_id"], resp1.json()["tunnel_id"])

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_same_params_different_request_id_still_409(self, _mock_op):
          """The name+peer duplicate check still fires for distinct request ids."""
          resp1 = self._post(PORTAL_REQUEST_URL, _valid_payload(self.device, self.template_profile))
          self.assertEqual(resp1.status_code, status.HTTP_202_ACCEPTED)
          resp2 = self._post(PORTAL_REQUEST_URL, _valid_payload(self.device, self.template_profile))
          self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
          self.assertIn("tunnel_id", resp2.json())
  ```
- [ ] Run — expected: `test_empty_body_returns_400` (now expects the new key in errors), `test_missing_request_id_returns_400`, `test_request_id_stamped_on_tunnel` (KeyError), and `test_duplicate_request_id_returns_409_with_original_tunnel` (202 ≠ 409) all fail:
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_api
  ```
- [ ] Add the serializer field in `api/serializers.py` after `member_protected_prefixes`:
  ```python
      member_connect_request_id = serializers.CharField(
          max_length=64,
          help_text="Member Connect portal VpnRequest UUID — cross-system idempotency key stamped on the tunnel.",
      )
  ```
- [ ] Create `nautobot_custom_tunnel_builder/migrations/0003_add_member_connect_request_id_custom_field.py`:
  ```python
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
  ```
- [ ] Wire the view. In `PortalTunnelRequestView.post`, add to the unpack block:
  ```python
          request_id = data["member_connect_request_id"]
  ```
  and immediately after the unpack (before the hub endpoint pre-check) insert:
  ```python
          # -------------------------------------------------------------- #
          # Idempotency: a replayed portal request returns the original     #
          # tunnel. Checked before every other gate.                        #
          # -------------------------------------------------------------- #
          existing_tunnel = VPNTunnel.objects.filter(
              _custom_field_data__member_connect_request_id=request_id
          ).first()
          if existing_tunnel:
              return Response(
                  {
                      "detail": "A tunnel for this member_connect_request_id already exists.",
                      "tunnel_id": str(existing_tunnel.pk),
                  },
                  status=status.HTTP_409_CONFLICT,
              )
  ```
  Pass it through: `self._create_tunnel_hierarchy(..., vpn_name, request_id)`; add `request_id` as the final parameter of `_create_tunnel_hierarchy`, and stamp it right after `VPNTunnel.objects.create(...)` (persisted by the existing trailing `tunnel.save()`):
  ```python
              tunnel._custom_field_data["member_connect_request_id"] = request_id  # pylint: disable=protected-access
  ```
- [ ] Run — expected all green (`test_duplicate_detection_returns_409` reposts the identical payload, so the new request-id dedupe now answers it — still 409, still contains `tunnel_id`):
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_api
  ```
- [ ] Commit:
  ```bash
  git add nautobot_custom_tunnel_builder/api/serializers.py nautobot_custom_tunnel_builder/api/views.py \
      nautobot_custom_tunnel_builder/migrations/0003_add_member_connect_request_id_custom_field.py \
      nautobot_custom_tunnel_builder/tests/test_api.py
  git commit -m "feat(api): member_connect_request_id idempotency key — required field, CF migration, stamp + 409 dedupe"
  ```

---

### Task 4: Hardening riders — OP_DEV_BYPASS gate, sequence floor + advisory lock

**Files:**
- Modify: `nautobot_custom_tunnel_builder/onepassword_utils.py` — `_dev_bypass_enabled` (lines 19–20)
- Modify: `nautobot_custom_tunnel_builder/api/views.py` — extract sequence block (step 4 in `_create_tunnel_hierarchy`) into module-level `_allocate_crypto_map_sequence`
- Create: `nautobot_custom_tunnel_builder/tests/test_onepassword_utils.py`
- Modify: `nautobot_custom_tunnel_builder/tests/test_api.py` — 2 new tests + imports

**Interfaces:**
- Consumes: `django.conf.settings.DEBUG` (dev compose sets `NAUTOBOT_DEBUG=True` in `development/development.env`; tests run with `DEBUG=False`); `django.db.connection` (dev/CI DB is PostgreSQL via `docker-compose.postgres.yml`).
- Produces: `_dev_bypass_enabled() -> bool` requiring env var AND `settings.DEBUG`, with WARNING logs both when active and when refused; `_allocate_crypto_map_sequence(device) -> int` — floor 3000, step 10, ignores sub-3000 legacy sequences, serialized by `pg_advisory_xact_lock` keyed on the device pk (transaction-scoped, so it releases with the surrounding `transaction.atomic()`); module constants `SEQUENCE_FLOOR = 3000`, `SEQUENCE_STEP = 10`.

**Steps:**

- [ ] Create `nautobot_custom_tunnel_builder/tests/test_onepassword_utils.py`:
  ```python
  """Tests for OP_DEV_BYPASS gating in onepassword_utils."""

  import os
  from unittest.mock import patch

  from django.test import TestCase, override_settings

  from nautobot_custom_tunnel_builder.onepassword_utils import _dev_bypass_enabled

  LOGGER_NAME = "nautobot_custom_tunnel_builder.onepassword_utils"


  class DevBypassGateTest(TestCase):
      """OP_DEV_BYPASS must require settings.DEBUG in addition to the env var."""

      @override_settings(DEBUG=True)
      @patch.dict(os.environ, {"OP_DEV_BYPASS": "true"})
      def test_bypass_enabled_with_env_and_debug_logs_loudly(self):
          with self.assertLogs(LOGGER_NAME, level="WARNING") as ctx:
              self.assertTrue(_dev_bypass_enabled())
          self.assertIn("OP_DEV_BYPASS ACTIVE", "\n".join(ctx.output))

      @override_settings(DEBUG=False)
      @patch.dict(os.environ, {"OP_DEV_BYPASS": "true"})
      def test_bypass_disabled_without_debug(self):
          with self.assertLogs(LOGGER_NAME, level="WARNING") as ctx:
              self.assertFalse(_dev_bypass_enabled())
          self.assertIn("DISABLED", "\n".join(ctx.output))

      @override_settings(DEBUG=True)
      @patch.dict(os.environ, {"OP_DEV_BYPASS": ""})
      def test_bypass_disabled_without_env_var(self):
          self.assertFalse(_dev_bypass_enabled())
  ```
- [ ] Add the two sequence tests to `PortalTunnelCreationTest` in `tests/test_api.py` (new imports at top of file: `from django.db import connection` and `from django.test.utils import CaptureQueriesContext`):
  ```python
      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_legacy_sub_3000_sequences_ignored(self, _mock_op):
          """Manual tunnels with sequences below 3000 must not drag allocation below the floor."""
          hub_endpoint = VPNTunnelEndpoint.objects.get(device=self.device, role__name="Hub")
          legacy_profile = VPNProfile.objects.create(name="legacy-manual-profile")
          legacy_profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"] = 20  # pylint: disable=protected-access
          legacy_profile.save()
          legacy_vpn = VPN.objects.create(vpn_id="vpn-legacy-001", name="Legacy VPN")
          planned = Status.objects.get_for_model(VPNTunnel).get(name="Planned")
          legacy_tunnel = VPNTunnel.objects.create(
              name="Legacy Tunnel - 20",
              tunnel_id="vpn-tunnel-legacy-20",
              status=planned,
              vpn=legacy_vpn,
              vpn_profile=legacy_profile,
          )
          legacy_tunnel.endpoint_z = hub_endpoint
          legacy_tunnel.save()

          payload = _valid_payload(self.device, self.template_profile)
          response = self._post(PORTAL_REQUEST_URL, payload)
          self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
          tunnel = VPNTunnel.objects.get(pk=response.json()["tunnel_id"])
          seq = tunnel.vpn_profile._custom_field_data["custom_tunnel_builder_crypto_map_sequence"]  # pylint: disable=protected-access
          self.assertEqual(seq, 3000)

      @patch(OP_MOCK_PATH, return_value="fake-op-item-id-12345")
      def test_sequence_allocation_takes_advisory_lock(self, _mock_op):
          """Allocation serializes on a Postgres advisory lock keyed on the device pk."""
          payload = _valid_payload(self.device, self.template_profile)
          with CaptureQueriesContext(connection) as ctx:
              response = self._post(PORTAL_REQUEST_URL, payload)
          self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
          self.assertTrue(
              any("pg_advisory_xact_lock" in q["sql"] for q in ctx.captured_queries),
              "Expected a pg_advisory_xact_lock query during sequence allocation",
          )
  ```
- [ ] Run — expected: the two new API tests fail (legacy test gets sequence `30`, lock test finds no advisory-lock query) and `test_bypass_disabled_without_debug` fails (`_dev_bypass_enabled()` returns True today):
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_onepassword_utils
  poetry run invoke unittest --skip-docs-build --keepdb --label nautobot_custom_tunnel_builder.tests.test_api.PortalTunnelCreationTest
  ```
- [ ] Implement the bypass gate in `onepassword_utils.py` — add `from django.conf import settings` to the imports and replace `_dev_bypass_enabled` (lines 19–20):
  ```python
  def _dev_bypass_enabled():
      """Dev bypass requires BOTH the OP_DEV_BYPASS env var and settings.DEBUG."""
      if os.environ.get("OP_DEV_BYPASS", "").lower() not in ("true", "1", "yes"):
          return False
      if not settings.DEBUG:
          logger.warning(
              "OP_DEV_BYPASS is set but settings.DEBUG is False — bypass DISABLED; "
              "PSKs will be stored in 1Password."
          )
          return False
      logger.warning(
          "OP_DEV_BYPASS ACTIVE: PSKs are written to %s instead of 1Password. "
          "Never enable this in production.",
          _DEV_PSK_DIR,
      )
      return True
  ```
- [ ] Implement sequence allocation in `api/views.py`. Change the db import to `from django.db import connection, transaction`, add module constants and function above `PortalTunnelRequestView`:
  ```python
  SEQUENCE_FLOOR = 3000
  SEQUENCE_STEP = 10


  def _allocate_crypto_map_sequence(device):
      """Return the next crypto map sequence (>= 3000, step 10) for a hub device.

      Must be called inside transaction.atomic(). On PostgreSQL a
      transaction-scoped advisory lock keyed on the device pk serializes
      concurrent allocations so two first-tunnel requests cannot both compute
      3000. Sequences below the floor (legacy manual crypto map entries) are
      ignored so they cannot drag next_seq down into colliding values.
      """
      if connection.vendor == "postgresql":
          with connection.cursor() as cursor:
              cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [str(device.pk)])
      existing_tunnels = VPNTunnel.objects.filter(endpoint_z__device=device).select_related("vpn_profile")
      sequences = [
          t.vpn_profile._custom_field_data.get("custom_tunnel_builder_crypto_map_sequence")  # pylint: disable=protected-access
          for t in existing_tunnels
          if t.vpn_profile
      ]
      portal_sequences = [s for s in sequences if isinstance(s, int) and s >= SEQUENCE_FLOOR]
      if portal_sequences:
          return max(portal_sequences) + SEQUENCE_STEP
      return SEQUENCE_FLOOR
  ```
  and replace step 4 of `_create_tunnel_hierarchy` (the whole `existing_tunnels`/`sequences`/`max_seq`/`next_seq` block) with:
  ```python
              # 4. Allocate the next crypto map sequence (advisory-locked, floor 3000).
              next_seq = _allocate_crypto_map_sequence(device)
  ```
- [ ] Run both labels again — expected green — then the full suite for regressions:
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb
  ```
- [ ] Commit:
  ```bash
  git add nautobot_custom_tunnel_builder/onepassword_utils.py nautobot_custom_tunnel_builder/api/views.py \
      nautobot_custom_tunnel_builder/tests/test_onepassword_utils.py nautobot_custom_tunnel_builder/tests/test_api.py
  git commit -m "feat(hardening): OP_DEV_BYPASS requires DEBUG with loud logging; sequence allocation floor 3000 + pg advisory lock"
  ```

---

### Task 5: Local E2E harness — script payload, `seed_e2e.py`, `invoke seed-e2e`

**Files:**
- Modify: `development/test-portal-api.sh` — env vars (lines 28–31) and POST payload (lines 137–146)
- Create: `development/seed_e2e.py`
- Modify: `tasks.py` — new `seed_e2e` task after `nbshell` (line 431)

**Interfaces:**
- Consumes: `docker-compose.fake-cisco.yml` pins fake-cisco at `172.18.0.100` on subnet `172.18.0.0/16` and injects `OP_DEV_BYPASS=true`; `nbshell(context, file=..., plain=True)` pipes a file into `nautobot-server nbshell --plain` inside the container (same pattern as `generate_app_config_schema`, tasks.py:1009-1021); the ORM shapes proven by `tests/test_api.py::_create_test_device` / `_create_template_vpn_profile` / `_create_hub_endpoint`.
- Produces: idempotent seed objects + a printed-once portal API token; `poetry run invoke seed-e2e`.

**Steps:**

- [ ] Update `development/test-portal-api.sh`. Add after line 31 (`TEMPLATE_PROFILE_UUID=...`):
  ```bash
  # Idempotency key — override to test replay/409 behavior.
  REQUEST_ID="${REQUEST_ID:-$(uuidgen | tr '[:upper:]' '[:lower:]')}"
  ```
  and add the field to the POST payload (after `member_protected_prefixes`, keeping valid JSON):
  ```bash
      -d "{
          \"member_name\": \"test-member\",
          \"member_display_name\": \"Test Member Corp\",
          \"location_city\": \"Jackson\",
          \"location_state\": \"MS\",
          \"device\": \"${HUB_DEVICE_UUID}\",
          \"template_vpn_profile\": \"${TEMPLATE_PROFILE_UUID}\",
          \"remote_peer_ip\": \"203.0.113.100\",
          \"member_protected_prefixes\": [\"192.168.200.0/24\"],
          \"member_connect_request_id\": \"${REQUEST_ID}\"
      }")
  ```
  Verify syntax: `bash -n development/test-portal-api.sh` (expect no output).
- [ ] Create `development/seed_e2e.py` (executed top-to-bottom by nbshell; `_main()` is called at the bottom, matching `app_config_schema.py`):
  ```python
  """Idempotent seed data for the local portal E2E harness.

  Run inside the nautobot container:
      poetry run invoke seed-e2e
  (pipes this file into `nautobot-server nbshell --plain`).

  Creates (get_or_create throughout — safe to re-run):
    - Hub Device "fake-cisco" (Cisco IOS-XE, primary IPv4 172.18.0.100/32 — the
      pinned address of the fake-cisco container in docker-compose.fake-cisco.yml)
    - Template VPNProfile "Standard-IKEv2-AES256" + Phase 1/2 policies + assignments
    - Hub VPNTunnelEndpoint (device + role "Hub") with protected prefix + crypto map CF
    - "Planned" and "Decommissioning" statuses mapped to VPNTunnel
    - Portal service account "portal-svc" + API token (printed on first run only)
  """

  from django.contrib.auth import get_user_model
  from django.contrib.contenttypes.models import ContentType
  from nautobot.dcim.models import Device, DeviceType, Interface, Location, LocationType, Manufacturer, Platform
  from nautobot.extras.models import Role, Status
  from nautobot.ipam.models import IPAddress, IPAddressToInterface, Namespace, Prefix
  from nautobot.users.models import Token
  from nautobot.vpn.models import (
      VPNPhase1Policy,
      VPNPhase2Policy,
      VPNProfile,
      VPNProfilePhase1PolicyAssignment,
      VPNProfilePhase2PolicyAssignment,
      VPNTunnel,
      VPNTunnelEndpoint,
  )

  HUB_DEVICE_NAME = "fake-cisco"
  HUB_IP = "172.18.0.100/32"  # pinned in docker-compose.fake-cisco.yml
  HUB_PARENT_PREFIX = "172.18.0.0/16"  # the compose overlay's docker subnet
  HUB_PROTECTED_PREFIX = "10.100.0.0/24"
  TEMPLATE_PROFILE_NAME = "Standard-IKEv2-AES256"
  SERVICE_ACCOUNT = "portal-svc"


  def _status(model, name="Active"):
      return Status.objects.get_for_model(model).get(name=name)


  def _seed_hub_device():
      manufacturer, _ = Manufacturer.objects.get_or_create(name="Cisco")
      device_type, _ = DeviceType.objects.get_or_create(model="CSR1000v", manufacturer=manufacturer)
      platform, _ = Platform.objects.get_or_create(
          name="Cisco IOS-XE",
          defaults={"network_driver": "cisco_xe"},
      )
      role, _ = Role.objects.get_or_create(name="Router")
      role.content_types.add(ContentType.objects.get_for_model(Device))
      location_type, _ = LocationType.objects.get_or_create(name="Site")
      location_type.content_types.add(ContentType.objects.get_for_model(Device))
      location, _ = Location.objects.get_or_create(
          name="NRTC Lab",
          location_type=location_type,
          defaults={"status": _status(Location)},
      )
      device, _ = Device.objects.get_or_create(
          name=HUB_DEVICE_NAME,
          defaults={
              "device_type": device_type,
              "platform": platform,
              "role": role,
              "location": location,
              "status": _status(Device),
          },
      )
      interface, _ = Interface.objects.get_or_create(
          device=device,
          name="GigabitEthernet1",
          defaults={"type": "1000base-t", "status": _status(Interface)},
      )
      global_ns, _ = Namespace.objects.get_or_create(name="Global")
      Prefix.objects.get_or_create(
          prefix=HUB_PARENT_PREFIX,
          namespace=global_ns,
          defaults={"status": _status(Prefix)},
      )
      ip, _ = IPAddress.objects.get_or_create(
          address=HUB_IP,
          namespace=global_ns,
          defaults={"status": _status(IPAddress)},
      )
      IPAddressToInterface.objects.get_or_create(ip_address=ip, interface=interface)
      if device.primary_ip4_id != ip.pk:
          device.primary_ip4 = ip
          device.save()
      return device, global_ns


  def _seed_template_profile():
      phase1, _ = VPNPhase1Policy.objects.get_or_create(
          name="Standard-IKEv2-Phase1",
          defaults={
              "ike_version": "IKEv2",
              "encryption_algorithm": ["AES-256-CBC"],
              "integrity_algorithm": ["SHA256"],
              "dh_group": ["19"],
              "lifetime_seconds": 86400,
          },
      )
      phase2, _ = VPNPhase2Policy.objects.get_or_create(
          name="Standard-AES256-Phase2",
          defaults={
              "encryption_algorithm": ["AES-256-CBC"],
              "integrity_algorithm": ["SHA256"],
              "lifetime": 3600,
          },
      )
      profile, _ = VPNProfile.objects.get_or_create(
          name=TEMPLATE_PROFILE_NAME,
          defaults={"description": "Template profile cloned per portal tunnel."},
      )
      VPNProfilePhase1PolicyAssignment.objects.get_or_create(
          vpn_profile=profile,
          vpn_phase1_policy=phase1,
          defaults={"weight": 100},
      )
      VPNProfilePhase2PolicyAssignment.objects.get_or_create(
          vpn_profile=profile,
          vpn_phase2_policy=phase2,
          defaults={"weight": 100},
      )
      return profile


  def _seed_hub_endpoint(device, namespace):
      hub_role, _ = Role.objects.get_or_create(name="Hub")
      hub_role.content_types.add(ContentType.objects.get_for_model(VPNTunnelEndpoint))
      endpoint, created = VPNTunnelEndpoint.objects.get_or_create(
          device=device,
          role=hub_role,
          defaults={"source_ipaddress": device.primary_ip},
      )
      if created or not endpoint._custom_field_data.get("custom_tunnel_builder_crypto_map_name"):
          endpoint._custom_field_data["custom_tunnel_builder_crypto_map_name"] = "VPN"
          endpoint.save()
      prefix, _ = Prefix.objects.get_or_create(
          prefix=HUB_PROTECTED_PREFIX,
          namespace=namespace,
          defaults={"status": _status(Prefix)},
      )
      endpoint.protected_prefixes.add(prefix)
      return endpoint


  def _seed_tunnel_statuses():
      vpntunnel_ct = ContentType.objects.get_for_model(VPNTunnel)
      for status_name in ("Planned", "Decommissioning"):
          st, _ = Status.objects.get_or_create(name=status_name)
          st.content_types.add(vpntunnel_ct)


  def _seed_service_account():
      user_model = get_user_model()
      user, _ = user_model.objects.get_or_create(
          username=SERVICE_ACCOUNT,
          defaults={"is_active": True},
      )
      token = Token.objects.filter(user=user).first()
      if token is None:
          token = Token.objects.create(user=user, description="member-connect-portal service token")
          print(f"  portal token (printed ONCE — save it now): {token.key}")
      else:
          print("  portal token already exists — not re-printed (delete it in the UI to rotate).")
      return user


  def _main():
      print("Seeding E2E harness objects (idempotent)...")
      device, global_ns = _seed_hub_device()
      print(f"  hub device:       {device.name}  {device.pk}")
      profile = _seed_template_profile()
      print(f"  template profile: {profile.name}  {profile.pk}")
      _seed_hub_endpoint(device, global_ns)
      print(f"  hub endpoint:     device={device.name} role=Hub prefix={HUB_PROTECTED_PREFIX}")
      _seed_tunnel_statuses()
      print("  statuses:         Planned + Decommissioning mapped to VPNTunnel")
      _seed_service_account()
      print("Done. Use the UUIDs above as HUB_DEVICE_UUID / TEMPLATE_PROFILE_UUID for")
      print("development/test-portal-api.sh and as the portal's nautobot.hub_device_id /")
      print("nautobot.template_vpn_profile_id credentials.")


  _main()
  ```
- [ ] Add the invoke task in `tasks.py`, directly after the `nbshell` task (line 431):
  ```python
  @task
  def seed_e2e(context):
      """Seed idempotent E2E harness data (hub device, template profile, portal token) in the nautobot container."""
      nbshell(context, plain=True, file="development/seed_e2e.py")
  ```
- [ ] Verify end-to-end (this is the harness's red/green cycle):
  ```bash
  poetry run invoke start --fake-cisco
  poetry run invoke migrate
  poetry run invoke seed-e2e          # first run: prints UUIDs + token
  poetry run invoke seed-e2e          # second run: same UUIDs, "token already exists" — idempotent
  NAUTOBOT_TOKEN=<printed-token> HUB_DEVICE_UUID=<printed-uuid> TEMPLATE_PROFILE_UUID=<printed-uuid> \
      ./development/test-portal-api.sh
  ```
  Expected: `HTTP 202` → status polls `Planned` → `Active` → Step 3 dumps IOS-XE crypto config from `docker exec fake-cisco cat /output/commands.txt`. (If Token creation misbehaves — `Token.save()` should auto-generate `key` — fall back to `Token.objects.create(user=user, key=Token.generate_key(), ...)` and note it in the commit.)
- [ ] Commit:
  ```bash
  git add development/test-portal-api.sh development/seed_e2e.py tasks.py
  git commit -m "feat(dev): idempotent seed_e2e harness + invoke seed-e2e; test script sends member_connect_request_id"
  ```

---

### Task 6: Ship gate — full suite, lint, integration SSH test, push

**Files:** none (verification only).

**Interfaces:** Consumes everything above; produces the pushed `feature/portal-api` branch ready for the portal-side plan.

**Steps:**

- [ ] Full unit suite (integration-tagged tests auto-excluded):
  ```bash
  poetry run invoke unittest --skip-docs-build --keepdb
  ```
  Expected: OK, 0 failures/errors (112+ tests: original 100 + Tasks 1–4 additions).
- [ ] Lint:
  ```bash
  poetry run invoke ruff
  poetry run invoke pylint
  ```
  Expected: clean (fix any nits before committing further).
- [ ] Integration SSH test against the live fake-cisco container (stack from Task 5 still up; otherwise `poetry run invoke start --fake-cisco`):
  ```bash
  poetry run invoke exec --command "nautobot-server test --tag integration --keepdb nautobot_custom_tunnel_builder.tests.test_integration_ssh"
  ```
  Expected: 4 tests OK (Netmiko negotiates real SSH to `fake-cisco:22`, commands land in `/output/commands.txt`, PSK redacted from logs).
- [ ] Re-run the manual contract check once more for the final state (replay the same `REQUEST_ID` to see the 409 path):
  ```bash
  REQUEST_ID=<uuid-from-task-5-run> NAUTOBOT_TOKEN=... HUB_DEVICE_UUID=... TEMPLATE_PROFILE_UUID=... \
      ./development/test-portal-api.sh
  ```
  Expected: `HTTP 409` with `detail` + `tunnel_id` (script exits non-zero on non-202 — that exit is the correct observed behavior for a replay).
- [ ] Verify clean tree and push:
  ```bash
  git status --short   # expect empty
  git log --oneline -6 # expect the five task commits on top of b13f596
  git push -u origin feature/portal-api
  ```

---

### Critical Files for Implementation

- /Users/mdean/Desktop/devsecops/github/nrtc-ops/nautobot-app-custom-tunnel-builder/nautobot_custom_tunnel_builder/api/views.py
- /Users/mdean/Desktop/devsecops/github/nrtc-ops/nautobot-app-custom-tunnel-builder/nautobot_custom_tunnel_builder/tests/test_api.py
- /Users/mdean/Desktop/devsecops/github/nrtc-ops/nautobot-app-custom-tunnel-builder/nautobot_custom_tunnel_builder/api/serializers.py
- /Users/mdean/Desktop/devsecops/github/nrtc-ops/nautobot-app-custom-tunnel-builder/nautobot_custom_tunnel_builder/onepassword_utils.py
- /Users/mdean/Desktop/devsecops/github/nrtc-ops/nautobot-app-custom-tunnel-builder/tasks.py
