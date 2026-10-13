"""Unit checks for each project module. No live Telegram or payment calls."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["QUOTE_DB"] = tempfile.mktemp(suffix=".sqlite")
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)

from fastapi.testclient import TestClient

import api.main as api_main
from actions import attempt, execute_approved
from api.store import get_review
from api.billing import verify_signature
from api.exports import build_pdf, build_xlsx, pdf_to_text
from api.store import PLANS, consume, grant_plan, login, register
from automate import _decide_action, _looks_like_new_quote, _merge_follow_up, _quote_keyboard, _reject_absurd

os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
from customs import customs_lane, format_notice, to_customs_record
from duty import estimate_duty
from market import financing_offer, quote_views, validate_displayed_fx
from quote_agent import SAMPLE_QUOTE, parse_freight_quote
from supabase_sync import sync_quote
from workers import submit

api_main._alert_telegram = lambda *args, **kwargs: None
CLIENT = TestClient(api_main.app)
BIZ = {"id": "demo", "legal_name": "Demo Global Logistics", "home_country": "Nigeria"}


def priced(text: str) -> dict:
    from market import enrich
    with patch("market.fetch_market_rates", return_value={"source": "test", "usd_ngn": 1500, "usd_cny": 7.2, "cny_ngn": 200}):
        return enrich(to_customs_record(parse_freight_quote(text), BIZ), BIZ)


class CustomsTests(unittest.TestCase):
    def test_lanes(self):
        self.assertEqual(customs_lane("Nigeria", "Nigeria", "Nigeria"), "domestic")
        self.assertEqual(customs_lane("Nigeria", "Nigeria", "United States"), "export")
        self.assertEqual(customs_lane("Nigeria", "Thailand", "Nigeria"), "import")
        self.assertEqual(customs_lane("Nigeria", "Thailand", "Germany"), "cross_trade")
        self.assertEqual(customs_lane("Nigeria", None, "Nigeria"), "unknown")


class DutyTests(unittest.TestCase):
    def test_solar_estimate(self):
        duty = estimate_duty("solar inverters", {"fx": {"cbn": {"NGN": 2_000_000}}, "commercial": {"currency": "NGN", "total_amount": 2_000_000}})
        self.assertEqual(duty["hs_code"], "8504.40.00")
        self.assertEqual(duty["import_duty_ngn"], 100_000)
        self.assertEqual(duty["etls_ngn"], 10_000)
        self.assertEqual(duty["ciss_ngn"], 20_000)
        self.assertGreater(duty["vat_ngn"], 0)

    def test_no_commodity(self):
        self.assertIsNone(estimate_duty("general cargo", {"commercial": {"currency": "NGN", "total_amount": 10}}))


class MarketTests(unittest.TestCase):
    def test_naira_quote_is_not_reconverted(self):
        views = quote_views(155_000, "NGN", {"cbn_usd_ngn": 5000, "parallel_usd_ngn": 6000}, {"usd_cny": 7.2})
        self.assertEqual(views["cbn"]["NGN"], 155_000)
        self.assertEqual(views["parallel"]["NGN"], 155_000)

    def test_dollar_quote_converts(self):
        views = quote_views(100, "USD", {"cbn_usd_ngn": 1500, "parallel_usd_ngn": 1600}, {"usd_cny": 7})
        self.assertEqual(views["cbn"]["NGN"], 150_000)
        self.assertEqual(views["parallel"]["NGN"], 160_000)

    def test_inland_haulage_pays_the_trucker(self):
        record = priced(
            "Provider: Fleet\nOrigin: Lagos\nDestination: Makurdi, Benue State\n"
            "Charges:\n- Haulage: NGN 800,000\nTotal Amount Due: NGN 800,000\n"
        )
        self.assertEqual(record["lane"], "domestic")
        self.assertEqual(record["commercial"]["incoterms"], "N/A (Domestic Carriage)")
        shares = {row["party"]: row["share"] for row in record["split"]["rows"]}
        self.assertNotIn("shipping_line", shares)
        self.assertEqual(shares["trucker"], 0.80)
        self.assertEqual(shares["platform_fee"], 0.10)
        self.assertEqual(shares["security_and_permits"], 0.10)
        self.assertNotIn("clearing_agent", shares)
        self.assertGreaterEqual(shares["trucker"], 0.75)

    def test_fx_ratio_outside_band_uses_live_or_withholds(self):
        views = quote_views(100, "USD", {"cbn_usd_ngn": 5000, "parallel_usd_ngn": 6000}, {"usd_ngn": 1500, "usd_cny": 7.2})
        self.assertEqual(views["cbn"]["usd_ngn"], 1500)
        self.assertIsNone(views["parallel"]["usd_ngn"])
        checked = validate_displayed_fx(views, {"usd_ngn": 1500, "usd_cny": 7.2}, "USD")
        self.assertEqual(checked["cbn"]["NGN"], 150_000)
        self.assertNotIn("error", checked)
        blocked = quote_views(100, "USD", {"cbn_usd_ngn": 5000, "parallel_usd_ngn": 6000}, {})
        blocked = validate_displayed_fx(blocked, {}, "USD")
        self.assertEqual(blocked["error"], "Official FX Rate: [Market Rates Pending Verification]")
        self.assertIsNone(blocked["cbn"]["NGN"])

    def test_optional_tarping_stays_out_of_the_total(self):
        record = priced(
            "Provider: Fleet\nOrigin: Lagos\nDestination: Makurdi\n"
            "Charges:\n- Haulage: NGN 800,000\n- Optional tarping: NGN 40,000\n"
            "Total Amount Due: NGN 840,000\n"
            "4 hours free for loading. 2 hours free for offloading. 1 free day at warehouse.\n"
        )
        self.assertEqual(record["commercial"]["total_amount"], 800_000)
        self.assertEqual(record["demurrage"]["buffer_hours"], 30)
        self.assertNotIn("0.", record["demurrage"]["reason"][:1])

    def test_trucking_email_drops_ocean_parties_and_bad_rates(self):
        record = priced(
            "Provider: Fleet\nOrigin: Lagos\nDestination: Makurdi, Benue State\n"
            "Equipment: 30-Ton Dry Box Trailer\n"
            "Charges:\n- Haulage: NGN 800,000\nTotal Amount Due: NGN 800,000\n"
        )
        record["fx"]["cbn"]["usd_ngn"] = 5000
        record["split"]["rows"] = [
            {"party": "shipping_line", "share": 0.70, "ngn": 560000, "usd": 0},
            {"party": "clearing_agent", "share": 0.10, "ngn": 80000, "usd": 0},
            {"party": "trucker", "share": 0.20, "ngn": 160000, "usd": 0},
        ]
        notice = format_notice(record)
        self.assertNotIn("shipping line", notice.lower())
        self.assertNotIn("clearing agent", notice.lower())
        self.assertNotIn("Which carrier", notice)
        self.assertIn("Carrier/Issuer: Freight Desk (Spot Market Platform)", notice)
        self.assertIn("Official Figures: NGN 800,000", notice)
        self.assertNotIn("5000", notice)
        shares = {row["party"]: row["share"] for row in record["split"]["rows"]}
        self.assertNotIn("shipping_line", shares)
        self.assertNotIn("clearing_agent", shares)
        self.assertEqual(shares["trucker"], 1.0)

    def test_missing_carrier_is_the_broker_desk(self):
        record = priced("Origin: Lagos\nDestination: Houston\nCharges:\n- Freight: NGN 150,000\nTotal Amount Due: NGN 150,000\n")
        self.assertEqual(record["commercial"]["carrier_name"], "Issued by: Regional Freight Broker Platform (Spot Market Desk)")
        notice = format_notice(record)
        self.assertIn("Regional Freight Broker Platform", notice)
        self.assertNotIn("Which carrier", notice)

    def test_finance_needs_duty(self):
        offer = financing_offer(0, "NGN", {"cbn": {"usd_ngn": 1500}, "market": {}}, {})
        self.assertFalse(offer["offered"])


class ParserTests(unittest.TestCase):
    def test_maersk_sample(self):
        quote = parse_freight_quote(SAMPLE_QUOTE)
        self.assertEqual(quote.quote_metadata.vendor_name, "Maersk Line")
        self.assertEqual(quote.financials.currency, "USD")
        self.assertEqual(quote.financials.total_amount, 3215)
        self.assertEqual(quote.shipment_details.origin.port_code, "CNSHA")
        self.assertEqual(quote.shipment_details.destination.port_code, "DEHAM")

    def test_gig_naira_quote(self):
        record = priced("Provider: GIG Logistics\nOrigin: Lagos\nDestination: Houston\nCharges:\n- Freight: NGN 150,000.00\n- Customs fee: NGN 5,000.00\nTotal Amount Due: NGN 155,000.00\n")
        notice = format_notice(record)
        self.assertEqual(record["commercial"]["vendor_name"], "GIG Logistics")
        self.assertEqual(record["lane"], "export")
        self.assertEqual(record["commercial"]["customs_and_tax"], 5000)
        self.assertEqual(record["fx"]["cbn"]["NGN"], 155000)
        self.assertNotIn("Demo Global", notice)

    def test_mixed_currency_keeps_dollars(self):
        record = priced("Provider: Line\nOrigin: Bangkok\nDestination: Apapa\nCharges:\n- Ocean Freight: USD 4,800.00\n- Customs: NGN 15,550,000\nTotal Amount Due: NGN 15,550,000\n")
        self.assertIn("USD freight kept separate", " ".join(record["extraction_flags"]))
        self.assertEqual(record["commercial"]["currency"], "NGN")


class ActionTests(unittest.TestCase):
    def test_pay_without_rail_queues_review(self):
        result = attempt("pay", {"commercial": {"vendor_name": "GIG", "quote_reference_id": "Q1"}}, "1")
        self.assertFalse(result["done"])
        self.assertTrue(result["review_id"])

    def test_clear_down_rail_stays_pending(self):
        queued = attempt("clear", {"commercial": {"vendor_name": "GIG"}}, "1")
        with patch.dict(os.environ, {"CUSTOMS_CLEAR_URL": "http://127.0.0.1:9/clear"}):
            result = execute_approved(get_review(queued["review_id"]))
        self.assertFalse(result["done"])
        self.assertIn("refused", result["note"])

    def test_approved_pay_calls_rail(self):
        queued = attempt("pay", {"commercial": {"vendor_name": "GIG", "quote_reference_id": "Q9"}}, "1")
        class Fake:
            status = 200
            def read(self):
                return b'{"ok": true, "note": "paid"}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
        with patch.dict(os.environ, {"PAYOUT_URL": "http://bank.test/pay"}):
            with patch("actions.urllib.request.urlopen", return_value=Fake()):
                result = execute_approved(get_review(queued["review_id"]))
        self.assertTrue(result["done"])
        self.assertEqual(result["note"], "paid")


class AutomateTests(unittest.TestCase):
    def test_follow_up_versus_new_quote(self):
        self.assertFalse(_looks_like_new_quote("Apapa"))
        self.assertTrue(_looks_like_new_quote("NGN 10,000 and USD 20"))
        self.assertIn("Ikeja", _merge_follow_up("Origin Lagos", "Ikeja"))

    def test_decisions(self):
        ready = {"agent_ready": True}
        self.assertEqual(_decide_action("hello", {"agent_ready": False}, None), "ask")
        self.assertEqual(_decide_action("pay the trucker", ready, None), "pay")
        self.assertEqual(_decide_action("clear the cargo", ready, None), "clear")
        self.assertEqual(_decide_action("quote", ready, "hold"), "ask")
        self.assertEqual(_decide_action("quote", ready, None), "publish")

    def test_absurd_hold(self):
        held = _reject_absurd({"commercial": {"currency": "USD", "total_amount": 200_000}, "fx": {}})
        self.assertTrue(held)
        fine = _reject_absurd({"commercial": {"currency": "NGN", "total_amount": 155_000}, "fx": {"cbn": {"NGN": 155_000}}})
        self.assertIsNone(fine)

    def test_keyboard(self):
        labels = [button["text"] for row in _quote_keyboard("tg-1")["inline_keyboard"] for button in row]
        self.assertIn("Download Client PDF", labels)
        self.assertIn("Compare quotes", labels)


class StoreTests(unittest.TestCase):
    def test_register_login_and_plan_cap(self):
        created = register("unit@example.com", "secret-pass", "Unit Co")
        self.assertTrue(created["company_code"].startswith("co-"))
        session = login("unit@example.com", "secret-pass")
        self.assertTrue(session["token"])
        user = consume(created["id"], 1)
        self.assertEqual(user["quota_remaining"], 4)
        granted = grant_plan("unit@example.com", "ref-unit-200", "quote-200")
        self.assertEqual(granted["quota_remaining"], PLANS["quote-200"]["parses"])
        again = grant_plan("unit@example.com", "ref-unit-200", "quote-200")
        self.assertEqual(again["quota_remaining"], 200)


class BillingTests(unittest.TestCase):
    def test_signature(self):
        os.environ["PAYSTACK_SECRET_KEY"] = "unit-secret"
        import hashlib
        import hmac
        body = b'{"event":"charge.success"}'
        good = hmac.new(b"unit-secret", body, hashlib.sha512).hexdigest()
        self.assertTrue(verify_signature(body, good))
        self.assertFalse(verify_signature(body, "nope"))


class ExportTests(unittest.TestCase):
    def test_xlsx_pdf_round_trip(self):
        record = priced("Provider: Maersk\nPOL: Shanghai (CNSHA) -> POD: Hamburg (DEHAM)\nCharges:\n- Ocean Freight: USD 100\nTotal Amount Due: USD 100\n")
        xlsx = build_xlsx([record], "Unit Co")
        pdf = build_pdf([record], "Unit Co")
        self.assertTrue(xlsx.startswith(b"PK"))
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn("Ocean", pdf_to_text(pdf))


class WorkerAndSyncTests(unittest.TestCase):
    def test_worker_runs(self):
        self.assertEqual(submit(lambda: 2 + 2).result(timeout=5), 4)

    def test_sync_skips_without_supabase(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}):
            self.assertIsNone(sync_quote({"commercial": {}, "line_items": [], "split": {}}, "local"))


class ApiTests(unittest.TestCase):
    def test_health_and_webhook(self):
        health = CLIENT.get("/health")
        self.assertEqual(health.status_code, 200)
        hook = CLIENT.post("/telegram/webhook", json={"update_id": 0})
        self.assertEqual(hook.status_code, 200)

    def test_auth_parse_and_terminal(self):
        email = "api-unit@example.com"
        reg = CLIENT.post("/v1/auth/register", json={"email": email, "password": "secret-pass", "business_name": "API Co"})
        self.assertEqual(reg.status_code, 200, reg.text)
        token = reg.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        parsed = CLIENT.post("/v1/quotes/parse", headers=headers, json={"text": "Provider: GIG Logistics\nOrigin: Lagos\nDestination: Houston\nCharges:\n- Freight: NGN 150,000\nTotal Amount Due: NGN 150,000\n"})
        self.assertEqual(parsed.status_code, 200, parsed.text)
        self.assertEqual(parsed.json()["lane"], "export")
        me = CLIENT.get("/v1/me", headers=headers)
        self.assertEqual(me.json()["quota_remaining"], 4)
        blocked = CLIENT.post("/v1/billing/checkout", headers=headers, json={"plan": "nope", "callback_url": "http://127.0.0.1:3000/billing"})
        self.assertEqual(blocked.status_code, 400)
        secret = os.environ.get("TERMINAL_WEBHOOK_SECRET")
        term_headers = {"X-Terminal-Token": secret} if secret else {}
        down = CLIENT.post("/v1/terminal/status", headers=term_headers, json={"feed_down": True, "gate_out": "unread", "source": "unit"})
        self.assertEqual(down.status_code, 200, down.text)
        self.assertTrue(down.json()["feed_down"])
        listed = CLIENT.get("/v1/reviews", headers=headers)
        self.assertTrue(any(row["kind"] == "terminal" for row in listed.json()["reviews"]))


class DeskOpsTests(unittest.TestCase):
    def test_cap_recalculates_and_matrix_indexes_lane(self):
        from desk_ops import comparison_matrix, detect_operational_flags, lane_benchmark, resolve_flag, save_market_rate
        from terminal_scrape import free_time, parse_container_page
        from datetime import datetime, timedelta, timezone

        record = {
            "company_id": "co-test",
            "commercial": {"vendor_name": "Maersk", "currency": "NGN", "total_amount": 200000, "valid_until": "48 hours", "payment_terms": "70% gate-in"},
            "movement": {"origin": {"location_name": "Ningbo"}, "destination": {"location_name": "Apapa"}, "est_transit_days": 32},
            "line_items": [
                {"description": "Ocean freight", "amount": 100000},
                {"description": "Local access bridge", "amount": 80000},
                {"description": "Gate-in", "amount": 20000},
            ],
            "fx": {"cbn": {"NGN": 200000}},
            "demurrage": {"free_days": 5, "daily_rate_ngn": 15000},
            "extraction_flags": [],
        }
        self.assertEqual({item["flag_id"] for item in detect_operational_flags(record)}, {"validity_48h", "uncapped_local_access", "gate_in_70"})
        result = resolve_flag(record, "uncapped_local_access", "cap_50000")
        self.assertTrue(result["recalculated"])
        self.assertEqual(record["commercial"]["total_amount"], 170000)
        resolve_flag(record, "gate_in_70", "split_50_50")
        self.assertEqual(record["line_items"][2]["amount"], round(20000 / 0.70 * 0.50, 2))
        matrix = comparison_matrix([record])
        self.assertEqual(matrix["lane"], "Ningbo -> Apapa")
        save_market_rate("Apapa -> Makurdi", 1_850_000, "40ft Flatbed", "road")
        bench = lane_benchmark("Apapa -> Makurdi", "40ft Flatbed")
        self.assertEqual(bench["average_ngn"], 1_850_000)
        self.assertIn("1,850,000", bench["headline"])

        past = datetime.now(timezone.utc) - timedelta(days=9)
        clock = free_time(past, 7)
        self.assertLess(clock["free_hours_remaining"], 0)
        self.assertGreater(clock["demurrage_liability_ngn"], 0)
        html = "Container MSKU1234567 vessel: GRANDE LAGOS discharge: 2026-10-01 yard: Block C4 free days: 5"
        status = parse_container_page("ptml", "MSKU1234567", html, "fixture")
        self.assertTrue(status.found)
        self.assertEqual(status.vessel_name, "GRANDE LAGOS")
        missing = parse_container_page("ptml", "MSKU1234567", "<p>no boxes</p>", "fixture")
        self.assertFalse(missing.found)

    def test_resolve_endpoint_regenerates_pdf(self):
        reg = CLIENT.post("/v1/auth/register", json={"email": "flags@example.com", "password": "secret-pass", "business_name": "Flag Co"})
        self.assertEqual(reg.status_code, 200, reg.text)
        code = reg.json()["company_code"]
        token = reg.json()["token"]
        record = {
            "company_id": code,
            "business": {"id": code, "legal_name": "Flag Co"},
            "lane": "import",
            "commercial": {"vendor_name": "MSC", "currency": "NGN", "total_amount": 80000, "valid_until": "48 hours", "payment_terms": "70% before gate-in", "incoterms": "CIF"},
            "movement": {"mode": "Ocean", "origin": {"location_name": "Ningbo"}, "destination": {"location_name": "Apapa"}, "est_transit_days": 30},
            "line_items": [{"description": "Local access", "category": "destination", "amount": 80000}],
            "fx": {"cbn": {"NGN": 80000}},
            "disclaimer": "Desk estimate.",
        }
        path = os.path.join(os.path.dirname(__file__), "..", "state", "records", "unit-flag.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        try:
            response = CLIENT.post(
                "/v1/quotes/unit-flag/resolve-flag",
                headers={"Authorization": f"Bearer {token}"},
                json={"flag_id": "uncapped_local_access", "option": "cap_50000"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["total_amount"], 50000)
            self.assertTrue(body["pdf_base64"])
            scrape = CLIENT.post(
                "/v1/terminal/scrape",
                headers={"Authorization": f"Bearer {token}"},
                json={"terminal": "not-a-terminal", "container": "BAD"},
            )
            self.assertEqual(scrape.status_code, 400)
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
