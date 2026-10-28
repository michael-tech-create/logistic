"""Sourced costs and messaging journeys; all providers and email are mocked."""
import base64
import copy
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pydantic import ValidationError
import api.main as api
from api import store
import automate
import customs
import desk_ops
import email_intake
import market
import media_intake
import operations_store as state
import whatsapp_intake as wa
from api.exports import build_pdf, pdf_to_text
from quote_agent import parse_freight_quote
from shipment_costs import CustomsValue, TariffProfile, ShipmentStorage, customs_cost, storage_cost

QUOTE = "Provider: GIG Logistics\nOrigin: Lagos\nDestination: Houston\nCharges:\n- Freight: NGN 150,000\nTotal Amount Due: NGN 150,000\n"
SOURCE = {"title": "Fixture schedule, not official rates", "url": "https://example.test/rates", "effective_from": "2026-01-01", "effective_to": "2026-12-31", "reviewed": True}
TARIFF = {"hs_code": "85044000", "description": "Fixture commodity", "source": SOURCE, "charges": [
    {"code": "duty", "label": "Fixture duty", "rate_percent": 10, "bases": ["cif"]},
    {"code": "levy", "label": "Fixture levy", "rate_percent": 1, "bases": ["fob"]},
    {"code": "tax", "label": "Fixture tax", "rate_percent": 5, "bases": ["cif", "duty", "levy"]},
]}
VALUE = {"hs_code": "85044000", "assessment_date": "2026-10-28", "currency": "USD", "goods_value": 1000, "freight": 100, "insurance": 10, "adjustments": 0, "ngn_per_unit": 1500, "rate_date": "2026-10-28", "rate_source": "https://example.test/fx", "valuation_reference": "TEST-INVOICE", "confirmed": True}
STORAGE = {"container": "ABCU1234567", "last_free_date": "2026-10-23", "as_of_date": "2026-10-28", "currency": "USD", "quantity": 2, "source": SOURCE, "tiers": [{"through_day": 3, "daily_rate": 10}, {"daily_rate": 20}]}


class CalculationTests(unittest.TestCase):
    def test_currency_is_explicit_and_large_dollar_amount_stays_dollars(self):
        quote = parse_freight_quote("Provider: Test\nOrigin: Lagos\nDestination: Houston\nCharges:\n- Ocean Freight: USD 500\n- Insurance: USD 150000\nTotal Amount Due: USD 150500")
        self.assertEqual(quote.financials.currency, "USD")
        self.assertEqual(len(quote.financials.line_items), 2)
        self.assertTrue(all(item.currency == "USD" for item in quote.financials.line_items))
        mixed = parse_freight_quote("Charges:\n- Ocean Freight: USD 4800\n- Customs: NGN 50000\nTotal Amount Due: NGN 50000")
        self.assertEqual([item.currency for item in mixed.financials.line_items], ["USD", "NGN"])
        self.assertEqual(mixed.financials.total_amount, 50000)
        views = market.quote_views(100, "EUR", {}, {"usd_ngn": 1500, "usd_cny": 7, "rates": {"EUR": .8}})
        self.assertEqual(views["cbn"]["USD"], 125)
        self.assertIsNone(market.quote_views(100, "EUR", {}, {})["cbn"]["USD"])

    def test_explicit_cif_and_compound_tax_bases(self):
        result = customs_cost(CustomsValue(**VALUE), TariffProfile(**TARIFF))
        self.assertEqual(result["cif_ngn"], 1665000)
        self.assertEqual([line["amount_ngn"] for line in result["lines"]], [166500, 15000, 92325])
        self.assertEqual(result["total_ngn"], 273825)
        self.assertEqual(result["tariff"]["source"], SOURCE)
        self.assertEqual(result["inputs"]["valuation_reference"], "TEST-INVOICE")

    def test_no_unreviewed_stale_nonfinite_or_double_counted_inputs(self):
        for update in ({"confirmed": False}, {"ngn_per_unit": "NaN"}, {"ngn_per_unit": "Infinity"}, {"rate_date": "2026-10-27"}, {"currency": "NGN", "ngn_per_unit": 1500}):
            with self.subTest(update=update), self.assertRaises(ValidationError): CustomsValue(**{**VALUE, **update})
        tariff = copy.deepcopy(TARIFF); tariff["charges"][0]["bases"] = ["cif", "fob"]
        with self.assertRaises(ValidationError): TariffProfile(**tariff)
        tariff = copy.deepcopy(TARIFF); tariff["source"]["reviewed"] = False
        with self.assertRaises(ValidationError): TariffProfile(**tariff)
        with self.assertRaises(ValueError): customs_cost(CustomsValue(**{**VALUE, "assessment_date": "2027-01-01", "rate_date": "2027-01-01"}), TariffProfile(**TARIFF))

    def test_last_free_day_is_inclusive_and_tiers_cross_correctly(self):
        result = storage_cost(ShipmentStorage(**STORAGE))
        self.assertEqual(result["chargeable_days"], 5)
        self.assertEqual(result["total"], 140)
        self.assertEqual(result["status"], "overdue")
        result = storage_cost(ShipmentStorage(**{**STORAGE, "as_of_date": "2026-10-23"}))
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["status"], "due_soon")

    def test_weekends_and_contract_holidays(self):
        result = storage_cost(ShipmentStorage(**{**STORAGE, "day_basis": "business", "holidays": ["2026-10-26"]}))
        self.assertEqual(result["chargeable_days"], 2)
        self.assertEqual(result["total"], 40)

    def test_storage_rejects_incomplete_tiers_and_expired_source(self):
        for update in ({"tiers": [{"through_day": 3, "daily_rate": 10}]}, {"as_of_date": "2027-01-01"}, {"tiers": [{"through_day": 3, "daily_rate": 10}, {"through_day": 2, "daily_rate": 20}, {"daily_rate": 30}]}):
            with self.subTest(update=update), self.assertRaises(ValidationError): ShipmentStorage(**{**STORAGE, **update})


class WorkspaceFixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="operations-test-")
        self.addCleanup(folder.cleanup); root = Path(folder.name)
        (root / "businesses.json").write_text('{"businesses": []}')
        for patcher in (
            patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": "", "RENDER": "", "REDIS_URL": "", "GEMINI_API_KEY": "", "GEMINI_API_KEYS": "", "WAAPI_TOKEN": "test-token", "WAAPI_INSTANCE_ID": "123", "WAAPI_WEBHOOK_SECRET": "x" * 40, "WAAPI_CHAT_ID": ""}),
            patch.object(api, "ROOT", root), patch.object(store, "DB_PATH", root / "billing.sqlite"),
            patch.object(desk_ops, "RECORDS", root / "state" / "records"),
            patch.object(customs, "BUSINESSES_PATH", root / "businesses.json"),
            patch.object(market, "RATE_CACHE", root / "rates.json"),
            patch.object(market, "fetch_market_rates", return_value={"source": "fixture", "usd_ngn": 1500, "usd_cny": 7.2}),
            patch.object(api, "parse_quote_smart", side_effect=parse_freight_quote),
            patch.object(automate, "parse_quote_smart", side_effect=parse_freight_quote),
            patch.object(automate, "send_email", return_value=True),
            patch.object(automate, "send_telegram"),
        ):
            patcher.start(); self.addCleanup(patcher.stop)
        self.client = TestClient(api.app)
        self.user = store.register("owner@example.test", "fixture-password", "Fixture Workspace")
        self.company = self.user["company_code"]
        with store.connect() as conn:
            conn.execute("UPDATE companies SET inbound_emails=? WHERE code=?", (json.dumps(["owner@example.test"]), self.company))
        self.headers = {"X-API-Key": self.user["api_key"]}

    def quota(self): return store.user_by_company(self.company)["quota_remaining"]

    def one_parse_left(self):
        with store.connect() as conn: conn.execute("UPDATE users SET quota_remaining=1 WHERE id=?", (self.user["id"],))


class OperationsTests(WorkspaceFixture):
    def test_concurrent_receipt_debits_once_and_cas_has_one_winner(self):
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda _: state.charge_once(self.user["id"], "same-receipt"), range(10)))
        self.assertEqual(self.quota(), 4)
        self.assertTrue(state.was_charged(self.user["id"], "same-receipt"))
        with self.assertRaises(PermissionError): state.charge_once(9999, "same-receipt")
        row = state.put("test", "one", {}, self.company, expected=0)
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: state.put("test", "one", {"claimed": True}, self.company, expected=row["revision"]), range(5)))
        self.assertEqual(sum(bool(row) for row in results), 1)

    def test_quote_calculate_recheck_export_and_tenant_boundaries(self):
        record = self.client.post("/v1/quotes/parse", headers=self.headers, json={"text": QUOTE}).json()
        path = f"/v1/quotes/{record['record_id']}"
        self.client.post(path + "/review", headers=self.headers)
        self.assertEqual(self.client.post(path + "/customs", headers=self.headers, json=VALUE).status_code, 400)
        result = self.client.post("/v1/tariffs", headers=self.headers, json=TARIFF)
        self.assertEqual(result.status_code, 200, result.text)
        result = self.client.post(path + "/customs", headers=self.headers, json=VALUE)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotIn("desk_review", result.json())
        self.assertEqual(result.json()["customs_assessment"]["total_ngn"], 273825)
        result = self.client.post(path + "/storage", headers=self.headers, json=STORAGE)
        self.assertEqual(result.status_code, 200, result.text)
        self.client.post(path + "/review", headers=self.headers)
        pdf = self.client.get(path + "/export/pdf", headers=self.headers)
        self.assertIn("273,825.00", pdf_to_text(pdf.content))
        self.assertIn("example.test/rates", pdf_to_text(pdf.content))
        book = load_workbook(BytesIO(self.client.get(path + "/export/xlsx", headers=self.headers).content))
        self.assertIn("Cost calculations", book.sheetnames)
        contents = str(list(book["Cost calculations"].values))
        self.assertIn("TEST-INVOICE", contents); self.assertIn("140.00", contents)
        other = store.register("other@example.test", "fixture-password", "Other Workspace")
        headers = {"X-API-Key": other["api_key"]}
        self.assertEqual(self.client.post(path + "/customs", headers=headers, json=VALUE).status_code, 404)
        self.assertEqual(self.client.post(path + "/storage", headers=headers, json=STORAGE).status_code, 404)
        self.assertEqual(self.client.get("/v1/tariffs", headers=headers).json()["profiles"], [])
        self.assertEqual(self.client.get("/v1/shipments/alerts", headers=headers).json()["alerts"], [])
        from datetime import date
        with patch("api.operations.today_lagos", return_value=date(2026, 10, 28)):
            alerts = self.client.get("/v1/shipments/alerts", headers=self.headers).json()["alerts"]
        self.assertEqual(alerts[0]["total"], 140)
        metrics = self.client.get("/v1/operations/performance", headers=self.headers).json()
        self.assertEqual(metrics["samples"], 1)

    def test_media_upload_uses_reader_and_bad_media_does_not_debit(self):
        with patch("quote_agent.gemini_media_text", return_value=QUOTE):
            result = self.client.post("/v1/quotes/batch", headers=self.headers, files=[("files", ("note.ogg", b"fixture-audio", "audio/ogg"))])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.quota(), 4)
        with patch("quote_agent.gemini_media_text", side_effect=RuntimeError("offline")):
            result = self.client.post("/v1/quotes/batch", headers=self.headers, files=[("files", ("note.ogg", b"fixture-audio", "audio/ogg"))])
        self.assertEqual(result.status_code, 503); self.assertEqual(self.quota(), 4)


class WhatsAppTests(WorkspaceFixture):
    chat = "2348000000000@c.us"

    def test_missing_schema_reports_setup_and_blocks_linking(self):
        message = "WhatsApp setup is incomplete. Apply supabase/operations.sql."
        with patch.object(state, "require_intake_storage", side_effect=state.StorageSetupError(message)), patch.object(wa, "link_code") as create:
            result = self.client.get("/v1/channels/whatsapp", headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertFalse(result.json()["configured"])
            self.assertTrue(result.json()["setup_required"])
            self.assertIn("operations.sql", result.json()["detail"])
            result = self.client.post("/v1/channels/whatsapp/link", headers=self.headers)
            self.assertEqual(result.status_code, 409)
            create.assert_not_called()

    def test_missing_provider_settings_and_temporary_outage_are_distinct(self):
        with patch.dict(os.environ, {"WAAPI_WEBHOOK_SECRET": ""}):
            result = self.client.get("/v1/channels/whatsapp", headers=self.headers)
            self.assertFalse(result.json()["configured"])
            self.assertIn("webhook", result.json()["detail"])
        with patch.object(state, "require_intake_storage", side_effect=RuntimeError("private database error")):
            result = self.client.get("/v1/channels/whatsapp", headers=self.headers)
            self.assertEqual(result.status_code, 503)
            self.assertIn("WhatsApp connections", result.json()["detail"])
            self.assertNotIn("private", result.text)

    def test_supabase_missing_table_is_classified_without_exposing_response(self):
        from urllib.error import HTTPError
        error = HTTPError("https://fixture.invalid", 404, "missing", {}, BytesIO(b'{"code":"PGRST205","message":"private internals"}'))
        with patch.object(store, "using_cloud", return_value=True), patch("supabase_sync._request", side_effect=error):
            with self.assertRaises(state.StorageSetupError) as result:
                state.require_intake_storage()
        self.assertIn("operations.sql", str(result.exception))
        self.assertNotIn("private", str(result.exception))

    def event(self, index=1, chat=None):
        chat = chat or self.chat
        return {"event": "message", "instanceId": "123", "data": {"message": {"from": chat, "id": {"_serialized": f"false_{chat}_{index}"}, "type": "chat", "body": QUOTE}}}

    def linked(self):
        command = wa.link_code(self.company)["command"]
        self.assertIn("Connected", wa.link_chat(self.chat, command.split()[1]))

    def process(self, text, index=1):
        key = wa.enqueue(self.event(index))
        job = {**state.get("wa_jobs", key)["payload"], "key": key}
        with patch.object(wa, "action", return_value={"from": self.chat, "body": text}): return wa.process_message(job)

    def test_link_single_use_expiry_and_cross_workspace(self):
        code = wa.link_code(self.company)["command"].split()[1]
        self.assertIn("Connected", wa.link_chat(self.chat, code))
        self.assertIn("invalid or expired", wa.link_chat("2348111111111@c.us", code))
        other = wa.link_code("other-workspace")["command"].split()[1]
        self.assertIn("another workspace", wa.link_chat(self.chat, other))
        expiring = wa.link_code(self.company)["command"].split()[1]
        import time
        with patch.object(wa.time, "time", return_value=time.time() + 601):
            self.assertIn("expired", wa.link_chat(self.chat, expiring))

    def test_webhook_auth_tamper_and_duplicate(self):
        with patch.object(wa, "schedule_pending"):
            self.assertEqual(self.client.post("/whatsapp/webhook/wrong", json=self.event()).status_code, 401)
            url = "/whatsapp/webhook/" + "x" * 40
            self.assertEqual(self.client.post(url, json={**self.event(), "instanceId": "999"}).status_code, 400)
            self.assertEqual(self.client.post(url, json=self.event()).status_code, 200)
            self.assertEqual(self.client.post(url, json=self.event()).status_code, 200)
        self.assertEqual(len(state.listing("wa_jobs")), 1)
        self.assertIsNone(wa.enqueue(self.event(2, "123@g.us")))
        event = self.event(3); event["data"]["message"]["fromMe"] = True
        self.assertIsNone(wa.enqueue(event))

    def test_quote_check_and_download_charges_only_once(self):
        self.linked()
        self.assertIn("/check", self.process(QUOTE)["text"])
        self.assertEqual(self.quota(), 4)
        self.assertNotIn("mediaBase64", self.process("/pdf", 2))
        self.assertIn("checked", self.process("/check", 3)["text"])
        result = self.process("/pdf", 4)
        self.assertTrue(base64.b64decode(result["mediaBase64"]).startswith(b"%PDF"))
        self.assertEqual(self.quota(), 4)

    def test_storage_failure_after_charge_recovers_with_zero_quota(self):
        self.linked(); self.one_parse_left()
        with patch.object(wa, "_save", side_effect=RuntimeError("storage unavailable")):
            with self.assertRaises(RuntimeError): self.process(QUOTE)
        self.assertEqual(self.quota(), 0)
        self.assertIn("/check", self.process(QUOTE)["text"])
        self.assertEqual(self.quota(), 0)

    def test_missing_route_follow_up_does_not_charge_twice(self):
        self.linked()
        self.assertIn("destination", self.process(QUOTE.replace("Destination: Houston\n", ""))["text"])
        self.assertIn("/check", self.process("Houston", 2)["text"])
        self.assertEqual(self.quota(), 4)
        self.assertIn("/help", self.process("/unknown", 3)["text"])
        self.assertEqual(self.quota(), 4)

    def test_verified_sender_and_media_allowlist(self):
        self.linked()
        with patch.object(wa, "action", return_value={"from": "2348999999999@c.us", "body": QUOTE}):
            with self.assertRaises(ValueError): wa.process_message({"chat": self.chat, "message_id": "fixture", "key": "fixture"})
        for target in ("http://media.waapi.app/file", "https://localhost/private", "https://media.waapi.app.evil.test/file", "https://user@media.waapi.app/file"):
            with patch.object(wa, "action", return_value={"media": {"url": target}}):
                with self.assertRaises(ValueError): wa.media_text("fixture")

    def test_later_message_waits_and_uncertain_delivery_is_not_retried(self):
        self.linked(); first = wa.enqueue(self.event(1)); second = wa.enqueue(self.event(2))
        with patch.object(wa, "process_message", return_value={"text": "fixture reply"}) as process, patch.object(wa, "action", side_effect=TimeoutError):
            wa.run_job(second); process.assert_not_called()
            wa.run_job(first); wa.run_job(first)
            process.assert_called_once()
        self.assertEqual(state.get("wa_jobs", first)["payload"]["status"], "delivery_uncertain")
        self.assertEqual(state.get("wa_jobs", second)["payload"]["status"], "pending")

    def test_trial_recipient_never_receives_another_chat_quote(self):
        self.linked(); key = wa.enqueue(self.event())
        with patch.dict(os.environ, {"WAAPI_CHAT_ID": "2348111111111@c.us"}), patch.object(wa, "process_message", return_value={"text": "private quote"}), patch.object(wa, "action") as action:
            wa.run_job(key); action.assert_not_called()
        self.assertEqual(state.get("wa_jobs", key)["payload"]["status"], "delivery_uncertain")


class EmailTests(WorkspaceFixture):
    def message(self, attachments=True):
        message = EmailMessage(); message["From"] = "owner@example.test"; message["To"] = "intake@example.test"
        message.set_content(QUOTE)
        if attachments:
            message.add_attachment(QUOTE.encode(), maintype="text", subtype="plain", filename="one.txt")
            message.add_attachment(QUOTE.replace("150,000", "250,000").encode(), maintype="text", subtype="plain", filename="two.txt")
        return message

    def test_attachments_remain_separate_and_redelivery_does_not_charge(self):
        message = self.message(); raw = message.as_bytes()
        result = email_intake.ingest_email(message, raw)
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual([row["commercial"]["total_amount"] for row in result["records"]], [150000, 250000])
        self.assertEqual(self.quota(), 3)
        self.assertTrue(email_intake.ingest_email(message, raw)["duplicate"])
        self.assertEqual(self.quota(), 3)

    def test_body_html_and_unknown_sender(self):
        message = self.message(False)
        message.set_content("<p>Freight: NGN 100</p><script>bad text</script>", subtype="html")
        self.assertNotIn("bad text", media_intake.email_sources(message)[0]["text"])
        message.replace_header("From", "stranger@example.test")
        self.assertTrue(email_intake.ingest_email(message, message.as_bytes())["ignored"])
        self.assertEqual(self.quota(), 5)

    def test_email_storage_failure_retries_paid_receipt_at_zero_quota(self):
        self.one_parse_left(); message = self.message(False); raw = message.as_bytes()
        with patch.object(desk_ops, "save_record", side_effect=RuntimeError("storage unavailable")):
            with self.assertRaises(RuntimeError): email_intake.ingest_email(message, raw)
        self.assertEqual(self.quota(), 0)
        self.assertEqual(len(email_intake.ingest_email(message, raw)["records"]), 1)
        self.assertTrue(email_intake.ingest_email(message, raw)["duplicate"])
        self.assertEqual(self.quota(), 0)

    def test_scanned_pdf_uses_media_reader_and_unsupported_attachment_fails_before_debit(self):
        with patch("api.exports.pdf_to_text", return_value=""), patch("quote_agent.gemini_media_text", return_value=QUOTE) as reader:
            self.assertEqual(media_intake.read_document(b"scanned-fixture", "scan.pdf"), QUOTE.strip())
            self.assertEqual(reader.call_args.args[1], "application/pdf")
        message = self.message()
        message.add_attachment(b"binary", maintype="application", subtype="zip", filename="bad.zip")
        with self.assertRaises(ValueError): email_intake.ingest_email(message, message.as_bytes())
        self.assertEqual(self.quota(), 5)


if __name__ == "__main__": unittest.main()
