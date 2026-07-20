"""Tests for the extracted SSH push function."""

import logging
from unittest.mock import MagicMock, patch

from django.test import TestCase

from nautobot_custom_tunnel_builder.jobs import IosXeConfigError, push_config_to_device


class PushConfigToDeviceTest(TestCase):
    """Test the extracted SSH push function."""

    def setUp(self):
        self.logger = logging.getLogger("test")
        self.device_params = {
            "device_type": "cisco_xe",
            "host": "10.1.1.1",
            "username": "admin",
            "password": "pass",
            "secret": "enable",
            "port": 22,
            "timeout": 30,
            "session_log": None,
        }
        self.commands = ["interface GigabitEthernet1", " description TEST"]

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_successful_push(self, mock_connect):
        """SSH push succeeds, config saved."""
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = "config output"

        output = push_config_to_device(self.device_params, self.commands, self.logger)

        mock_conn.send_config_set.assert_called_once_with(self.commands, cmd_verify=False)
        mock_conn.save_config.assert_called_once()
        self.assertEqual(output, "config output")

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_enable_secret_called_when_present(self, mock_connect):
        """Enable mode entered when secret is provided."""
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = "ok"

        push_config_to_device(self.device_params, self.commands, self.logger)
        mock_conn.enable.assert_called_once()

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_enable_not_called_without_secret(self, mock_connect):
        """Enable mode skipped when no secret."""
        self.device_params["secret"] = ""
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = "ok"

        push_config_to_device(self.device_params, self.commands, self.logger)
        mock_conn.enable.assert_not_called()

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_iosxe_error_detected(self, mock_connect):
        """IOS-XE error patterns in output raise IosXeConfigError."""
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = (
            "crypto ipsec transform-set BAD\n% Invalid input detected at '^' marker."
        )

        with self.assertRaises(IosXeConfigError) as ctx:
            push_config_to_device(self.device_params, self.commands, self.logger)

        self.assertIn("Invalid input", str(ctx.exception))
        mock_conn.save_config.assert_not_called()

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_connection_failure_propagates(self, mock_connect):
        """Connection failure raises original exception."""
        mock_connect.side_effect = Exception("Connection refused")

        with self.assertRaises(Exception) as ctx:
            push_config_to_device(self.device_params, self.commands, self.logger)

        self.assertIn("Connection refused", str(ctx.exception))

    @patch("nautobot_custom_tunnel_builder.jobs.ConnectHandler")
    def test_psk_redacted_in_output_log(self, mock_connect):
        """PSK is replaced with ***REDACTED*** in the logged device output."""
        psk = "SuperSecretPSK123!"
        mock_conn = MagicMock()
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.send_config_set.return_value = (
            f"crypto isakmp key {psk} address 203.0.113.1\n"
            f"  pre-shared-key local {psk}\n"
            "crypto map VPN 3000 ipsec-isakmp\n"
        )

        with self.assertLogs("test", level="INFO") as log_ctx:
            push_config_to_device(self.device_params, self.commands, self.logger, psk=psk)

        full_log = "\n".join(log_ctx.output)
        self.assertNotIn(psk, full_log, "PSK must not appear in any log output")
        self.assertIn("***REDACTED***", full_log)
