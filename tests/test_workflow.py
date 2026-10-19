"""Workflow contracts: persistence, ownership, validation, and export freshness."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import api.main as api
import api.store as store
import desk_ops
import market
from quote_agent import parse_freight_quote
from supabase_sync import get_quote

QUOTE = "Provider: GIG Logistics\nOrigin: Lagos\nDestination: Houston\nCharges:\n- Freight: NGN 150,000\nTotal Amount Due: NGN 150,000\n"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="quote-workflow-")
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        for patcher in (
            patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": "", "RENDER": ""}),
            patch.object(api, "ROOT", root),
            patch.object(store, "DB_PATH", root / "billing.sqlite"),
            patch.object(desk_ops, "RECORDS", root / "state" / "records"),
            patch.object(market, "RATE_CACHE", root / "rates.json"),
            patch.object(market, "fetch_market_rates", return_value={"source": "test", "usd_ngn": 1500, "usd_cny": 7.2}),
            patch.object(api, "parse_quote_smart", side_effect=parse_freight_quote),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(api.app)
        self.headers = self.account("owner@example.test")

    def account(self, email):
        response = self.client.post("/v1/auth/register", json={"email": email, "password": "test-password", "business_name": "Workflow Co"})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": "Bearer " + response.json()["token"]}

    def parse(self, text=QUOTE):
        response = self.client.post("/v1/quotes/parse", headers=self.headers, json={"text": text})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_paste_check_refresh_and_export(self):
        record = self.parse()
        rid = record["record_id"]
        self.assertEqual(record["source_text"], QUOTE)
        checked = self.client.post(f"/v1/quotes/{rid}/review", headers=self.headers)
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertEqual(checked.json()["desk_review"]["reviewed_by"], "owner@example.test")
        inbox = self.client.get("/v1/inbox", headers=self.headers).json()["records"]
        self.assertEqual(inbox[0]["desk_review"]["status"], "reviewed")
        self.assertEqual(self.client.get("/v1/me", headers=self.headers).json()["quota_remaining"], 4)
        for kind, prefix in (("pdf", b"%PDF"), ("xlsx", b"PK")):
            exported = self.client.get(f"/v1/quotes/{rid}/export/{kind}", headers=self.headers)
            self.assertEqual(exported.status_code, 200, exported.text[:100])
            self.assertTrue(exported.content.startswith(prefix))
        self.assertEqual(self.client.get("/v1/reviews", headers=self.headers).json()["reviews"], [])

    def test_incomplete_quote_cannot_be_checked(self):
        record = self.parse("Provider: GIG\nCharges:\n- Freight: NGN 100\nTotal Amount Due: NGN 100\n")
        response = self.client.post(f"/v1/quotes/{record['record_id']}/review", headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("origin", response.json()["detail"])
        self.assertIn("destination", response.json()["detail"])

    def test_cross_company_review_and_export_are_denied(self):
        record = self.parse()
        stranger = self.account("stranger@example.test")
        self.assertEqual(self.client.post(f"/v1/quotes/{record['record_id']}/review", headers=stranger).status_code, 404)
        self.assertEqual(self.client.get(f"/v1/quotes/{record['record_id']}/export/pdf", headers=stranger).status_code, 404)
        self.assertEqual(self.client.get("/v1/inbox", headers=stranger).json()["records"], [])

    def test_invalid_later_file_consumes_no_quota(self):
        result = self.client.post("/v1/quotes/batch", headers=self.headers, files=[("files", ("good.txt", QUOTE.encode(), "text/plain")), ("files", ("bad.csv", b"invalid", "text/csv"))])
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get("/v1/me", headers=self.headers).json()["quota_remaining"], 5)
        self.assertEqual(self.client.get("/v1/inbox", headers=self.headers).json()["records"], [])

    def test_corrupt_pdf_returns_actionable_error_before_parsing(self):
        result = self.client.post("/v1/quotes/batch", headers=self.headers, files=[("files", ("broken.pdf", b"not a PDF", "application/pdf"))])
        self.assertEqual(result.status_code, 400)
        self.assertIn("paste", result.json()["detail"])
        self.assertEqual(self.client.get("/v1/me", headers=self.headers).json()["quota_remaining"], 5)

    def test_batch_reopens_with_latest_quote_check(self):
        result = self.client.post("/v1/quotes/batch", headers=self.headers, files=[("files", ("quote.txt", QUOTE.encode(), "text/plain"))])
        self.assertEqual(result.status_code, 200, result.text)
        batch = result.json()
        record = batch["records"][0]
        self.client.post(f"/v1/quotes/{record['record_id']}/review", headers=self.headers)
        restored = self.client.get(f"/v1/quotes/batch/{batch['batch_id']}", headers=self.headers)
        self.assertEqual(restored.json()["records"][0]["desk_review"]["status"], "reviewed")
        stranger = self.account("stranger@example.test")
        self.assertEqual(self.client.get(f"/v1/quotes/batch/{batch['batch_id']}", headers=stranger).status_code, 404)
        for kind in ("pdf", "xlsx"):
            self.assertEqual(self.client.get(f"/v1/quotes/batch/{batch['batch_id']}.{kind}", headers=self.headers).status_code, 200)

    def test_cloud_quota_does_not_query_sqlite(self):
        with patch("api.store.using_cloud", return_value=True), patch("api.store.connect", side_effect=AssertionError("Cloud quota must not query SQLite")):
            api.enforce_plan_quota({"id": 123, "quota_remaining": 5, "plan_parses": 5})
            with self.assertRaises(api.HTTPException) as result:
                api.enforce_plan_quota({"id": 123, "quota_remaining": 0, "plan_parses": 5})
            self.assertEqual(result.exception.status_code, 402)

    def test_cloud_read_checks_record_and_company(self):
        with patch("supabase_sync._request", return_value=[{"payload": {"commercial": {"vendor_name": "GIG"}}}]) as remote:
            record = get_quote("desk-test", "co-owner")
        self.assertEqual(record["company_id"], "co-owner")
        self.assertIn("record_id=eq.desk-test&company_id=eq.co-owner", remote.call_args.args[1])

    def test_record_changes_require_a_new_check(self):
        record = self.parse()
        rid = record["record_id"]
        self.client.post(f"/v1/quotes/{rid}/review", headers=self.headers)
        response = self.client.post(f"/v1/quotes/{rid}/resolve-flag", headers=self.headers, json={"flag_id": "validity_48h", "option": "extend_72h"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("desk_review", response.json()["record"])
        self.assertNotIn("desk_review", self.client.get("/v1/inbox", headers=self.headers).json()["records"][0])

    def test_completed_payment_review_cannot_be_approved_again(self):
        user = store.user_by_token(self.headers["Authorization"].split(" ", 1)[1])
        queued = store.queue_human_review("pay", "Fixture", payload={"commercial": {}}, company_id=user["company_code"])
        store.resolve_review(queued["id"], "executed", company_id=user["company_code"])
        with patch("actions.execute_approved") as execute:
            response = self.client.post(f"/v1/reviews/{queued['id']}", headers=self.headers, json={"status": "approved"})
        self.assertEqual(response.status_code, 409)
        execute.assert_not_called()

    def test_cloud_review_payload_accepts_a_json_object(self):
        from actions import execute_approved

        with patch.dict(os.environ, {"PAYOUT_URL": "https://fixture.invalid/pay"}), patch("actions._post", return_value={"ok": True}) as provider:
            result = execute_approved({"kind": "pay", "payload": {"commercial": {"total_amount": 150000}}})
        self.assertTrue(result["done"])
        provider.assert_called_once()


if __name__ == "__main__":
    unittest.main()
