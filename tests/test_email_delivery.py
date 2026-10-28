"""Provider contracts and real recovery logic; all network calls are mocked."""

import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import api.main  # Load the same environment and adapters as the deployed API.
from api import password_reset, store
import automate
from email_delivery import delivery_method


class EmailDeliveryTests(unittest.TestCase):
    def setUp(self):
        settings = patch.dict(os.environ, {
            "RESEND_API_KEY": "re_test_secret", "RESEND_FROM": "Clearing Desk <desk@example.test>",
            "SMTP_HOST": "smtp.invalid", "SMTP_FROM": "smtp@example.test", "SMTP_PORT": "587",
            "SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": "", "RENDER": "",
            "PASSWORD_RESET_URL": "https://desk.example.test/reset-password",
        })
        settings.start(); self.addCleanup(settings.stop)
        self.response = MagicMock()
        self.response.__enter__.return_value.read.return_value = b'{"id":"email-123"}'
        request = patch("email_delivery.urllib.request.urlopen", return_value=self.response)
        self.request = request.start(); self.addCleanup(request.stop)
        smtp = patch("automate.smtplib.SMTP_SSL")
        self.smtp = smtp.start(); self.addCleanup(smtp.stop)

    def test_https_is_selected_with_existing_smtp_settings(self):
        self.assertEqual(delivery_method(), "resend")
        self.assertTrue(automate.send_email("owner@example.test", "Reset password", "private reset link"))
        request = self.request.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer re_test_secret")
        self.assertEqual(json.loads(request.data), {"from": "Clearing Desk <desk@example.test>", "to": ["owner@example.test"], "subject": "Reset password", "text": "private reset link"})
        self.smtp.assert_not_called()

    def test_partial_https_configuration_does_not_fall_back_to_blocked_smtp(self):
        for missing in ("RESEND_API_KEY", "RESEND_FROM"):
            with self.subTest(missing=missing), patch.dict(os.environ, {missing: ""}):
                with self.assertRaisesRegex(RuntimeError, "both"):
                    delivery_method()
                self.assertFalse(automate.send_email("owner@example.test", "Reset", "link"))
                with self.assertRaisesRegex(RuntimeError, "administrator"):
                    password_reset.ensure_email_ready()
        self.request.assert_not_called(); self.smtp.assert_not_called()

    def test_provider_rejections_are_redacted_and_not_retried(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                self.request.reset_mock()
                self.request.side_effect = urllib.error.HTTPError("https://api.resend.com/emails", status, "re_test_secret owner@example.test #token=private", {}, io.BytesIO(b'private response body'))
                with self.assertLogs("email_delivery", level="WARNING") as logs:
                    self.assertFalse(automate.send_email("owner@example.test", "Reset", "#token=private"))
                text = " ".join(logs.output)
                self.assertIn(str(status), text)
                for secret in ("re_test_secret", "owner@example.test", "#token=private", "private response body"):
                    self.assertNotIn(secret, text)
                self.request.assert_called_once()
        self.smtp.assert_not_called()

    def test_unconfirmed_response_and_timeout_are_not_reported_as_sent(self):
        for response in (b'{}', b'{"id":null}', b'[]', b'invalid JSON'):
            with self.subTest(response=response), self.assertLogs("email_delivery", level="WARNING"):
                self.response.__enter__.return_value.read.return_value = response
                self.assertFalse(automate.send_email("owner@example.test", "Reset", "link"))
        self.request.side_effect = TimeoutError("private details")
        with self.assertLogs("email_delivery", level="WARNING") as logs:
            self.assertFalse(automate.send_email("owner@example.test", "Reset", "link"))
        self.assertNotIn("private details", " ".join(logs.output))

    def test_existing_smtp_still_works_when_https_is_unconfigured(self):
        with patch.dict(os.environ, {"RESEND_API_KEY": "", "RESEND_FROM": "", "SMTP_PORT": "465"}):
            self.assertEqual(delivery_method(), "smtp")
            self.assertTrue(automate.send_email("owner@example.test", "Reset", "link"))
        self.smtp.assert_called_once_with("smtp.invalid", 465, timeout=8)
        self.smtp.return_value.send_message.assert_called_once()
        self.request.assert_not_called()

    def test_reset_link_sent_over_https_changes_password_and_revokes_session(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(store, "DB_PATH", Path(folder) / "reset.sqlite"):
            store.register("owner@example.test", "old-password-123", "Test Desk")
            session = store.login("owner@example.test", "old-password-123")
            page = password_reset.ensure_email_ready()
            password_reset.send_reset_link("owner@example.test", page)
            body = json.loads(self.request.call_args.args[0].data)["text"]
            token = re.search(r'https://desk.example.test/reset-password#token=([A-Za-z0-9_-]+)', body).group(1)
            password_reset.reset_password(token, "new-password-456")
            self.assertTrue(store.login("owner@example.test", "new-password-456"))
            self.assertIsNone(store.user_by_token(session["token"]))
            with self.assertRaises(ValueError):
                password_reset.reset_password(token, "another-password-789")


if __name__ == "__main__":
    unittest.main()
