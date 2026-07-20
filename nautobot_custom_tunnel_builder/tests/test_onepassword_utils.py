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
