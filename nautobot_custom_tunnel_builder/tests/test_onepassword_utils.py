"""Tests for OP_DEV_BYPASS gating in onepassword_utils."""

import os
from unittest.mock import patch

from django.test import TestCase, override_settings

from nautobot_custom_tunnel_builder.onepassword_utils import (
    _dev_bypass_enabled,
    _psk_item_note,
    get_secret_provider_params,
)

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


class SecretProviderParamsTest(TestCase):
    """get_secret_provider_params must emit params the NTC one-password provider
    reads: {vault, item, field}. The text-file bypass shape is unchanged."""

    @override_settings(DEBUG=False)
    @patch.dict(os.environ, {"OP_DEV_BYPASS": "", "OP_VAULT_UUID": "vault-abc"})
    def test_one_password_params_match_ntc_contract(self):
        provider, params = get_secret_provider_params("item-xyz")
        self.assertEqual(provider, "one-password")
        self.assertEqual(params, {"vault": "vault-abc", "item": "item-xyz", "field": "password"})

    @override_settings(DEBUG=True)
    @patch.dict(os.environ, {"OP_DEV_BYPASS": "true"})
    def test_dev_bypass_still_uses_text_file(self):
        provider, params = get_secret_provider_params("dev-item")
        self.assertEqual(provider, "text-file")
        self.assertIn("path", params)


class PskItemNoteTest(TestCase):
    """The 1Password item note carries operator context: who/where the PSK is
    for, the member peer IP, the hub device, crypto sequence, and the request
    id — so an engineer finding the item does not need to open Nautobot."""

    def test_note_includes_operator_context(self):
        note = _psk_item_note(
            member="Fox Islands Electric (fox-islands)",
            location="North Haven, ME",
            remote_peer_ip="203.0.113.71",
            hub_device="fake-cisco",
            sequence=3090,
            request_id="mc-req-abc123",
        )
        assert "Nautobot Custom Tunnel Builder" in note
        assert "Fox Islands Electric (fox-islands)" in note
        assert "North Haven, ME" in note
        assert "Member peer IP: 203.0.113.71" in note
        assert "fake-cisco" in note
        assert "3090" in note
        assert "mc-req-abc123" in note

    def test_note_omits_blank_fields(self):
        note = _psk_item_note(member="X (x)", remote_peer_ip="", hub_device=None, sequence=3000)
        assert "Member peer IP" not in note  # blank omitted
        assert "NRTC hub device" not in note  # None omitted
        assert "3000" in note
