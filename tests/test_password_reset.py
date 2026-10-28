"""Recovery contracts using an isolated database and captured email, never SMTP."""

import hashlib
import os
import re
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException

import api.main as api
import api.store as store
from api import password_reset as recovery


class PasswordResetTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="password-reset-")
        self.addCleanup(folder.cleanup)
        for patcher in (
            patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": "", "RENDER": "", "RESEND_API_KEY": "", "RESEND_FROM": "", "SMTP_PORT": "587", "SMTP_HOST": "smtp.invalid", "SMTP_FROM": "desk@example.test", "PASSWORD_RESET_URL": "https://desk.example.test/reset-password"}),
            patch.object(store, "DB_PATH", Path(folder.name) / "accounts.sqlite"),
        ):
            patcher.start(); self.addCleanup(patcher.stop)
        mail = patch("automate.send_email", return_value=True)
        self.mail = mail.start(); self.addCleanup(mail.stop)
        self.user = store.register("owner@example.test", "old-password-123", "Reset Co")

    def issue(self):
        recovery.send_reset_link("owner@example.test", "https://desk.example.test/reset-password")
        return re.search(r"#token=([A-Za-z0-9_-]+)", self.mail.call_args.args[2]).group(1)

    def test_link_changes_password_revokes_sessions_and_is_single_use(self):
        session = store.login("owner@example.test", "old-password-123")
        token = self.issue()
        row = store.connect().execute("SELECT * FROM users WHERE id = ?", (self.user["id"],)).fetchone()
        self.assertNotEqual(row["reset_token_hash"], token)
        self.assertEqual(row["reset_token_hash"], hashlib.sha256(token.encode()).hexdigest())
        recovery.reset_password(token, "new-password-456")
        self.assertIsNone(store.user_by_token(session["token"]))
        with self.assertRaises(ValueError): store.login("owner@example.test", "old-password-123")
        self.assertEqual(store.login("owner@example.test", "new-password-456")["email"], "owner@example.test")
        with self.assertRaisesRegex(ValueError, "already used"): recovery.reset_password(token, "another-password-789")

    def test_expired_link_does_not_change_password(self):
        token = self.issue()
        with store.connect() as conn:
            conn.execute("UPDATE users SET reset_expires_at = ?", (int(time.time()) - 1,))
        with self.assertRaisesRegex(ValueError, "expired"): recovery.reset_password(token, "new-password-456")
        self.assertTrue(store.login("owner@example.test", "old-password-123"))

    def test_invalid_token_and_weak_password_do_not_consume_valid_link(self):
        token = self.issue()
        with self.assertRaisesRegex(ValueError, "invalid"): recovery.reset_password("invalid", "new-password-456")
        with self.assertRaisesRegex(ValueError, "12 and 128"): recovery.reset_password(token, "short")
        recovery.reset_password(token, "new-password-456")

    def test_cooldown_limits_email_without_invalidating_previous_link(self):
        token = self.issue()
        recovery.send_reset_link("owner@example.test", "https://desk.example.test/reset-password")
        self.mail.assert_called_once()
        recovery.reset_password(token, "new-password-456")

    def test_newer_link_replaces_previous_one(self):
        old = self.issue()
        with store.connect() as conn: conn.execute("UPDATE users SET reset_requested_at = 0")
        new = self.issue()
        with self.assertRaises(ValueError): recovery.reset_password(old, "new-password-456")
        recovery.reset_password(new, "new-password-456")

    def test_unknown_email_is_not_sent_an_email(self):
        recovery.send_reset_link("unknown@example.test", "https://desk.example.test/reset-password")
        self.mail.assert_not_called()

    def test_endpoint_returns_same_message_and_no_token_for_every_email(self):
        results = []
        for email in ("owner@example.test", "unknown@example.test"):
            tasks = BackgroundTasks()
            results.append(api.auth_forgot_password(api.ForgotPasswordBody(email=email), tasks))
            self.assertEqual(len(tasks.tasks), 1)
        self.assertEqual(results[0], results[1])
        self.assertEqual(list(results[0]), ["message"])
        self.mail.assert_not_called()

    def test_missing_email_configuration_is_actionable(self):
        with patch.dict(os.environ, {"SMTP_HOST": ""}), self.assertRaises(HTTPException) as result:
            api.auth_forgot_password(api.ForgotPasswordBody(email="owner@example.test"), BackgroundTasks())
        self.assertEqual(result.exception.status_code, 503)
        self.assertIn("administrator", result.exception.detail)

    def test_reset_urls_come_only_from_trusted_configuration(self):
        for url in ("http://attacker.test/reset", "https://user:pass@desk.test/reset", "https://desk.test/reset?next=evil", "javascript:bad"):
            with self.subTest(url=url), patch.dict(os.environ, {"PASSWORD_RESET_URL": url}), self.assertRaises(RuntimeError): recovery.reset_page_url()
        with patch.dict(os.environ, {"PASSWORD_RESET_URL": "", "DASHBOARD_URL": "https://desk.test/desk", "PAYSTACK_CALLBACK_URL": ""}):
            self.assertEqual(recovery.reset_page_url(), "https://desk.test/reset-password")

    def test_concurrent_consumers_only_change_password_once(self):
        token = self.issue()
        def consume(index):
            try: recovery.reset_password(token, f"new-password-{index:03}"); return True
            except ValueError: return False
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(consume, range(4)))
        self.assertEqual(sum(results), 1)

    def test_cloud_issue_uses_account_cooldown_and_completion_is_atomic(self):
        from api import cloud_store
        with patch("api.cloud_store._patch", return_value={"id": 1}) as update:
            self.assertTrue(cloud_store.issue_password_reset("Owner@Example.test", "digest", 2800, 1000))
        self.assertIn("email=eq.owner%40example.test", update.call_args.args[0])
        self.assertIn("reset_requested_at.lte.940", update.call_args.args[0])
        with patch("api.cloud_store._request", return_value=True) as remote:
            self.assertTrue(cloud_store.complete_password_reset("digest", "password-hash", 1000))
        self.assertEqual(remote.call_args.args, ("POST", "rpc/complete_password_reset", {"p_token_hash": "digest", "p_password_hash": "password-hash"}))

    def test_missing_cloud_migration_reports_recovery_unavailable(self):
        from api.cloud_store import ensure_password_reset_ready
        with patch("api.cloud_store._request", side_effect=RuntimeError("Missing schema")), self.assertRaisesRegex(RuntimeError, "administrator"):
            ensure_password_reset_ready()


if __name__ == "__main__": unittest.main()
