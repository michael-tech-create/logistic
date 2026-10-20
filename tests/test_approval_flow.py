"""Approval state contracts; no network, real payouts, or Telegram messages."""

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import api.main as api
import api.store as store
from actions import execute_approved


class ApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="approval-flow-")
        self.addCleanup(folder.cleanup)
        for patcher in (
            patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": "", "RENDER": "", "PAYOUT_URL": "", "CUSTOMS_CLEAR_URL": ""}),
            patch.object(store, "DB_PATH", Path(folder.name) / "reviews.sqlite"),
            patch.object(api, "current_user", return_value={"id": 1}),
            patch.object(api, "ensure_company", return_value={"code": "co-owner"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        provider_patch = patch("actions._post", return_value={"ok": True})
        self.provider = provider_patch.start()
        self.addCleanup(provider_patch.stop)

    def queue(self, kind="pay", company="co-owner"):
        return store.queue_human_review(kind, "Test quote", payload={"commercial": {"total_amount": 150000}}, company_id=company)["id"]

    def approve(self, rid):
        return api.review_decision(rid, api.ReviewBody(status="approved"), None, None)

    def test_missing_providers_save_human_approval_without_submission(self):
        for kind in ("pay", "clear"):
            with self.subTest(kind=kind):
                rid = self.queue(kind)
                result = self.approve(rid)
                self.assertEqual(result["status"], "approved")
                self.assertEqual(store.get_review(rid)["status"], "approved")
                self.assertIn("nothing was sent", result["execution_note"])
                self.assertFalse(result["execution"]["done"])
        self.provider.assert_not_called()

    def test_connecting_provider_allows_explicit_submission_once(self):
        rid = self.queue()
        self.approve(rid)
        with patch.dict(os.environ, {"PAYOUT_URL": "https://provider.invalid/pay"}):
            result = api.review_execute(rid, None, None)
            self.assertEqual(result["status"], "executed")
            with self.assertRaises(HTTPException) as rejected:
                api.review_execute(rid, None, None)
        self.assertEqual(rejected.exception.status_code, 409)
        self.provider.assert_called_once()

    def test_approved_request_does_not_ask_for_approval_again(self):
        rid = self.queue()
        self.approve(rid)
        with self.assertRaises(HTTPException) as rejected:
            self.approve(rid)
        self.assertEqual(rejected.exception.status_code, 409)
        self.provider.assert_not_called()

    def test_provider_timeout_cannot_be_resubmitted(self):
        rid = self.queue()
        self.provider.side_effect = TimeoutError("Provider may already have received it")
        with patch.dict(os.environ, {"PAYOUT_URL": "https://provider.invalid/pay"}):
            result = self.approve(rid)
            self.assertEqual(result["status"], "execution_uncertain")
            self.assertIn("Check with the provider", result["execution_note"])
            with self.assertRaises(HTTPException):
                api.review_execute(rid, None, None)
            with self.assertRaises(HTTPException):
                self.approve(rid)
        self.provider.assert_called_once()

    def test_concurrent_stale_approvals_only_submit_once(self):
        rid = self.queue()
        stale = store.get_review(rid)
        def submit(_):
            try:
                return api._submit_review(stale, "co-owner", "pending")["status"]
            except HTTPException as exc:
                return exc.status_code
        with patch.dict(os.environ, {"PAYOUT_URL": "https://provider.invalid/pay"}), ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(submit, range(4)))
        self.assertEqual(results.count("executed"), 1)
        self.assertEqual(results.count(409), 3)
        self.provider.assert_called_once()

    def test_other_company_cannot_approve_or_send(self):
        rid = self.queue(company="co-other")
        for operation in (self.approve, lambda rid: api.review_execute(rid, None, None)):
            with self.assertRaises(HTTPException) as rejected:
                operation(rid)
            self.assertEqual(rejected.exception.status_code, 404)
        self.provider.assert_not_called()

    def test_rejection_never_submits_to_provider(self):
        rid = self.queue()
        result = api.review_decision(rid, api.ReviewBody(status="rejected"), None, None)
        self.assertEqual(result["status"], "rejected")
        self.provider.assert_not_called()

    def test_cloud_claim_filters_company_and_expected_state(self):
        from api.cloud_store import resolve_review
        with patch("api.cloud_store._patch", return_value=None) as remote:
            self.assertIsNone(resolve_review(7, "processing", company_id="co-owner", expected_status="pending"))
        self.assertIn("company_id=eq.co-owner", remote.call_args.args[0])
        self.assertIn("status=eq.pending", remote.call_args.args[0])

    def test_unreadable_payload_is_not_submitted(self):
        with patch.dict(os.environ, {"PAYOUT_URL": "https://provider.invalid/pay"}):
            for payload in ("broken JSON", "[]", None):
                result = execute_approved({"kind": "pay", "payload": payload})
                self.assertEqual(result["status"], "approved")
                self.assertFalse(result["done"])
        self.provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
