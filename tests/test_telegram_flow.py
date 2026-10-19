"""Telegram journeys without live Telegram, Gemini, email, or payment calls."""

import asyncio
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import automate as bot
import api.store as store
import cache
import customs
import desk_ops
import market
import telegram_jobs as jobs
from api.exports import build_pdf, pdf_to_text

REAL_SEND_TELEGRAM = bot.send_telegram

QUOTE = "Provider: GIG Logistics\nOrigin: Lagos\nDestination: Houston\nCharges:\n- Freight: NGN 150,000\nTotal Amount Due: NGN 150,000\n"


class TelegramFlowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="telegram-flow-")
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        (root / "businesses.json").write_text('{"businesses": []}')
        self.root = root
        for patcher in (
            patch.dict(os.environ, {key: "" for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "GEMINI_API_KEYS", "GEMINI_API_KEY", "REDIS_URL", "SMTP_HOST", "RENDER", "DASHBOARD_URL")}),
            patch.object(bot, "ROOT", root), patch.object(bot, "STATE_DIR", root / "state"),
            patch.object(bot, "OFFSET_PATH", root / "state" / "telegram_offset.txt"),
            patch.object(customs, "BUSINESSES_PATH", root / "businesses.json"),
            patch.object(store, "DB_PATH", root / "billing.sqlite"),
            patch.object(cache, "STATE", root / "state"), patch.object(cache, "redis_client", return_value=None),
            patch.object(desk_ops, "RECORDS", root / "state" / "records"),
            patch.object(market, "RATE_CACHE", root / "rates.json"),
            patch.object(jobs, "QUEUE_PATH", root / "state" / "jobs.sqlite"),
            patch.object(jobs, "_RUNNING", set()), patch.object(jobs, "_CHATS", set()),
            patch.object(market, "fetch_market_rates", return_value={"source": "test", "usd_ngn": 1500, "usd_cny": 7.2}),
        ):
            patcher.start(); self.addCleanup(patcher.stop)
        self.mocks = {}
        for name, options in (("send_telegram", {}), ("telegram_api", {"return_value": {"ok": True, "result": {}}}), ("_send_file", {}), ("send_email", {"return_value": False})):
            patcher = patch.object(bot, name, **options)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.send = self.mocks["send_telegram"]
        self.api = self.mocks["telegram_api"]
        self.files = self.mocks["_send_file"]
        self.email = self.mocks["send_email"]
        self.user = store.register("bot@example.test", "fixture-password", "Bot Co")
        store.link_telegram(self.user["company_code"], "111")
        self.sequence = 0

    def message(self, text=None, chat=111, message_id=None, **fields):
        self.sequence += 1
        message = {"chat": {"id": chat, "type": "private"}, "from": {"id": chat}, "message_id": message_id or self.sequence, **fields}
        if text is not None: message["text"] = text
        bot.handle_telegram_message(message)
        return message

    def callback(self, action, record=None, chat=111):
        data = f"{action}:{record['record_id']}" if record else action
        bot._handle_callback({"id": "callback-fixture", "data": data, "from": {"id": chat}, "message": {"chat": {"id": chat, "type": "private"}}})

    def latest(self, chat="111"):
        return bot._latest_record(chat)

    def text(self):
        return self.send.call_args.args[1]

    def quota(self):
        return store.user_by_company(self.user["company_code"])["quota_remaining"]

    def test_unlinked_chat_is_never_auto_attached_or_parsed(self):
        (self.root / "businesses.json").write_text(json.dumps({"businesses": [{"id": "legacy", "legal_name": "Legacy", "telegram_chat_ids": []}]}))
        with patch.object(bot, "ingest_text") as parse:
            self.message(QUOTE, chat=222)
        parse.assert_not_called()
        self.assertIn("Connections", self.text())
        self.assertEqual(json.loads((self.root / "businesses.json").read_text())["businesses"][0]["telegram_chat_ids"], [])

    def test_explicit_workspace_link_wins_over_legacy_single_company(self):
        (self.root / "businesses.json").write_text(json.dumps({"businesses": [{"id": "legacy", "telegram_chat_ids": [111]}]}))
        self.assertEqual(bot._bind_chat("111"), self.user["company_code"])
        self.message("/start")
        self.assertIn("Linked to Bot Co", self.text())
        self.assertEqual(self.quota(), 5)

    def test_group_qualified_command_and_deep_link_work(self):
        self.message(f"/link@freight_bot {self.user['company_code']}", chat=222)
        self.assertEqual(bot._bind_chat("222"), self.user["company_code"])
        self.message(f"/start {self.user['company_code']}", chat=333)
        self.assertEqual(bot._bind_chat("333"), self.user["company_code"])

    def test_non_admin_cannot_link_group(self):
        bot.handle_telegram_message({"chat": {"id": -123, "type": "group"}, "from": {"id": 9}, "text": f"/link {self.user['company_code']}"})
        self.assertIn("administrator", self.text())
        self.assertIsNone(bot._bind_chat("-123"))

    def test_bare_link_unknown_command_and_greeting_do_not_consume_quota(self):
        for text in ("/link", "/unsupported", "hello", "/help@freight_bot"):
            with self.subTest(text=text): self.message(text)
        self.assertEqual(self.quota(), 5)
        self.assertIsNone(bot._load_dialog("111"))

    def test_quote_is_saved_before_buttons_and_checked_before_export(self):
        saved_at_send = []
        def observe(chat, text, markup=None):
            if text.startswith("Quote saved"):
                saved_at_send.append(bool(bot._latest_record(chat)))
        self.send.side_effect = observe
        self.message(QUOTE)
        record = self.latest()
        self.assertEqual(saved_at_send, [True])
        self.callback("pdf", record)
        self.files.assert_not_called()
        self.assertIn("Check this quote", self.text())
        self.callback("checked", record)
        self.assertEqual(self.latest()["desk_review"]["status"], "reviewed")
        self.callback("pdf", record)
        self.assertTrue(self.files.call_args.args[2].startswith(b"%PDF"))
        self.callback("xlsx", record)
        self.assertTrue(self.files.call_args.args[2].startswith(b"PK"))
        self.assertEqual(self.quota(), 4)
        self.email.assert_not_called()

    def test_same_message_id_in_two_chats_does_not_overwrite(self):
        store.link_telegram(self.user["company_code"], "222")
        self.message(QUOTE, message_id=77)
        self.message(QUOTE.replace("GIG Logistics", "Other Vendor"), chat=222, message_id=77)
        self.assertEqual(self.latest()["record_id"], "tg-111-77")
        self.assertEqual(self.latest("222")["record_id"], "tg-222-77")
        self.assertEqual(self.latest()["commercial"]["vendor_name"], "GIG Logistics")

    def test_foreign_chat_callbacks_are_rejected_even_in_same_company(self):
        store.link_telegram(self.user["company_code"], "222")
        self.message(QUOTE)
        self.callback("checked", self.latest(), chat=222)
        self.assertIn("unavailable in this chat", self.text())
        self.assertNotIn("desk_review", self.latest())
        self.files.assert_not_called()

    def test_company_prefix_cannot_override_chat_link(self):
        self.message("business:another-company\n" + QUOTE)
        self.assertIn("different company", self.text())
        self.assertEqual(self.quota(), 5)

    def test_missing_destination_follow_up_is_guided_and_not_charged_twice(self):
        self.message(QUOTE.replace("Destination: Houston\n", ""))
        self.assertIn("destination", self.text())
        self.assertEqual(self.quota(), 4)
        self.message("Houston")
        self.assertEqual(self.latest()["movement"]["destination"]["location_name"], "Houston")
        self.assertEqual(self.quota(), 4)
        self.assertIsNone(bot._load_dialog("111"))

    def test_exhausted_account_can_complete_already_charged_draft(self):
        self.message(QUOTE.replace("Destination: Houston\n", ""))
        store.consume(self.user["id"], 4)
        self.message("Houston")
        self.assertIsNotNone(self.latest())
        self.assertEqual(self.quota(), 0)
        self.message(QUOTE)
        self.assertIn("allowance is used up", self.text())

    def test_cancel_clears_draft_and_new_does_not_reuse_previous_source(self):
        self.message(QUOTE.replace("Destination: Houston\n", ""))
        self.message("/cancel")
        self.assertIsNone(bot._load_dialog("111"))
        self.message("/new")
        self.assertIsNone(self.latest())
        self.assertEqual(self.quota(), 4)

    def test_correction_uses_latest_explicit_route_and_requires_new_check(self):
        self.message(QUOTE)
        old = self.latest()
        self.callback("checked", old)
        self.callback("correct", old)
        self.message("Destination: Accra")
        self.assertEqual(self.latest()["movement"]["destination"]["location_name"], "Accra")
        self.assertNotIn("desk_review", self.latest())
        self.assertEqual(self.quota(), 4)
        self.assertNotEqual(self.latest()["record_id"], old["record_id"])

    def test_telegram_redelivery_replays_without_charging_again(self):
        self.message(QUOTE, message_id=42)
        self.message(QUOTE, message_id=42)
        self.assertEqual(self.quota(), 4)
        self.assertEqual(len(list((self.root / "state" / "records").glob("*.json"))), 1)

    def test_retry_after_send_failure_does_not_charge_again(self):
        def failing(chat, text, markup=None):
            if text.startswith("Quote saved"): raise OSError("fixture send failure")
        self.send.side_effect = failing
        with self.assertRaises(OSError): self.message(QUOTE, message_id=42)
        self.send.side_effect = None
        self.message(QUOTE, message_id=42)
        self.assertEqual(self.quota(), 4)
        self.assertIn("Quote saved", self.text())

    def test_payment_request_is_explicit_visible_and_deduplicated(self):
        self.message(QUOTE)
        record = self.latest()
        self.message("pay the trucker")
        self.assertIn("Check this quote first", self.text())
        self.callback("checked", record)
        self.message("pay the trucker")
        self.assertIn("Request payment", self.text())
        self.assertEqual(store.list_reviews(self.user["company_code"]), [])
        self.callback("confirm_pay", record)
        self.assertIn("Review #", self.text())
        self.assertIn("Approvals", self.text())
        self.callback("confirm_pay", record)
        self.assertIn("already exists", self.text())
        self.assertEqual(len(store.list_reviews(self.user["company_code"])), 1)
        self.assertEqual(self.quota(), 4)

    def test_quote_payment_terms_do_not_trigger_payment_request(self):
        self.message(QUOTE + "Terms: pay the trucker after delivery.\n")
        self.assertEqual(store.list_reviews(self.user["company_code"]), [])

    def test_txt_document_is_read_and_unsupported_file_is_recoverable(self):
        with patch.object(bot, "_download_telegram_file", return_value=QUOTE.encode()):
            self.message(document={"file_id": "fixture", "file_name": "quote.txt", "mime_type": "text/plain"})
        self.assertIsNotNone(self.latest())
        with patch.object(bot, "_download_telegram_file") as download:
            self.message(document={"file_id": "fixture", "file_name": "quote.zip", "mime_type": "application/zip"})
        download.assert_not_called()
        self.assertIn("not read that attachment", self.text())
        self.assertEqual(self.quota(), 4)

    def test_audio_document_is_transcribed_and_media_failure_does_not_charge(self):
        with patch.object(bot, "_transcribe_audio", return_value=QUOTE) as transcribe:
            self.message(document={"file_id": "fixture", "file_name": "quote.mp3", "mime_type": "audio/mpeg"})
        transcribe.assert_called_once()
        with patch.object(bot, "_media_text", side_effect=RuntimeError("fixture unavailable")):
            self.message(voice={"file_id": "bad-audio"})
        self.assertIn("No parse was charged", self.text())
        self.assertEqual(self.quota(), 4)

    def test_compare_keeps_same_route_and_requires_two_quotes(self):
        self.message(QUOTE)
        self.assertIn("at least two", bot._compare_text("111"))
        self.message(QUOTE.replace("GIG Logistics", "Vendor Two"))
        self.assertIn("Same-route", bot._compare_text("111"))
        self.message(QUOTE.replace("Houston", "Accra"))
        self.assertEqual(len(bot._compare_ids("111")), 1)

    def test_unlink_confirmation_blocks_stale_quote_buttons(self):
        self.message(QUOTE)
        record = self.latest()
        self.message("/unlink")
        self.assertIsNotNone(bot._bind_chat("111"))
        self.callback("unlink:" + self.user["company_code"])
        self.assertIsNone(bot._bind_chat("111"))
        self.callback("pdf", record)
        self.files.assert_not_called()

    def test_callback_payloads_fit_telegram_limit(self):
        rid = "tg--1001234567890123-2147483647"
        for reviewed in (False, True):
            for row in bot._quote_keyboard(rid, reviewed)["inline_keyboard"]:
                for button in row:
                    self.assertLessEqual(len(button.get("callback_data", "").encode()), 64)

    def test_full_check_contains_all_charge_lines_and_notes(self):
        self.message(QUOTE)
        record = self.latest()
        record["line_items"] = [{"description": f"Charge {i}", "amount": 100} for i in range(15)]
        record["extraction_flags"] = [f"Note {i}" for i in range(10)]
        bot._store_record(record, record["record_id"], chat_id="111")
        self.callback("review", record)
        self.assertIn("Charge 14", self.text())
        self.assertIn("Note 9", self.text())

    def test_unicode_naira_pdf_round_trip(self):
        self.message(QUOTE)
        record = self.latest()
        record["commercial"]["payment_terms"] = "₦150,000 — payable on delivery"
        content = build_pdf([record], "Ọmọ Logistics")
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertIn("₦150,000", pdf_to_text(content))
        self.assertIn("Ọmọ", pdf_to_text(content))

    def test_file_cache_expiry_and_legacy_expiry(self):
        with patch("cache.time.time", return_value=1000): cache.set_json("dialog:111", {"raw": "old"}, 60)
        with patch("cache.time.time", return_value=1061): self.assertIsNone(cache.get_json("dialog:111"))
        path = self.root / "state" / "cache" / "fx_market"
        path.write_text('{"usd_ngn": 1500}')
        os.utime(path, (1000, 1000))
        with patch("cache.time.time", return_value=1601): self.assertIsNone(cache.get_json("fx:market"))

    def test_long_reply_keeps_all_text_and_buttons_on_last_part(self):
        text = "Line with naira ₦\n" * 600
        REAL_SEND_TELEGRAM("111", text, {"inline_keyboard": []})
        calls = [call.args[1] for call in self.api.call_args_list]
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(len(call["text"]) <= 3900 for call in calls))
        self.assertNotIn("reply_markup", calls[0])
        self.assertIn("reply_markup", calls[-1])
        self.assertEqual("\n".join(call["text"] for call in calls).strip(), text.strip())

    def test_durable_queue_deduplicates_and_orders_same_chat(self):
        first = {"update_id": 100, "message": {"chat": {"id": 111}, "text": "one"}}
        second = {"update_id": 101, "message": {"chat": {"id": 111}, "text": "two"}}
        jobs.enqueue(first); jobs.enqueue(first); jobs.enqueue(second)
        with patch.object(bot, "process_telegram_update", return_value=True) as process:
            jobs.run_job(101)
            process.assert_not_called()
            jobs.run_job(100); jobs.run_job(100); jobs.run_job(101)
            self.assertEqual(process.call_count, 2)
        with jobs._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM telegram_jobs").fetchone()[0], 2)
            self.assertTrue(all(row[0] == "{}" for row in conn.execute("SELECT payload FROM telegram_jobs")))

    def test_poll_does_not_advance_offset_when_queue_persistence_fails(self):
        self.api.return_value = {"ok": True, "result": [{"update_id": 55, "message": {"chat": {"id": 111}, "text": "quote"}}]}
        with patch("telegram_jobs.schedule_pending"), patch("telegram_jobs.enqueue", side_effect=OSError("fixture disk full")):
            with self.assertRaises(OSError): bot.poll_telegram_once()
        self.assertIsNone(cache.get_text("tg:offset"))

    def test_webhook_requires_mode_and_secret_and_persists_before_ack(self):
        import api.main as api
        from fastapi import BackgroundTasks
        class Request:
            headers = {"x-telegram-bot-api-secret-token": "fixture-secret"}
            async def json(self): return {"update_id": 77}
        with patch.dict(os.environ, {"TELEGRAM_DELIVERY_MODE": "polling"}):
            with self.assertRaises(api.HTTPException) as result: asyncio.run(api.telegram_webhook(Request(), BackgroundTasks()))
            self.assertEqual(result.exception.status_code, 409)
        with patch.dict(os.environ, {"TELEGRAM_DELIVERY_MODE": "webhook", "TELEGRAM_WEBHOOK_SECRET": ""}):
            with self.assertRaises(api.HTTPException) as result: asyncio.run(api.telegram_webhook(Request(), BackgroundTasks()))
            self.assertEqual(result.exception.status_code, 503)
        with patch.dict(os.environ, {"TELEGRAM_DELIVERY_MODE": "webhook", "TELEGRAM_WEBHOOK_SECRET": "fixture-secret"}):
            background = BackgroundTasks()
            result = asyncio.run(api.telegram_webhook(Request(), background))
            self.assertEqual(result, {"ok": True})
            with jobs._connect() as conn: self.assertIsNotNone(conn.execute("SELECT 1 FROM telegram_jobs WHERE update_id=77").fetchone())
            self.assertEqual(len(background.tasks), 1)

    def test_group_admin_can_link_and_non_admin_cannot_confirm_unlink(self):
        self.api.return_value = {"ok": True, "result": {"status": "administrator"}}
        bot.handle_telegram_message({"chat": {"id": -123, "type": "group"}, "from": {"id": 9}, "text": f"/link {self.user['company_code']}"})
        self.assertEqual(bot._bind_chat("-123"), self.user["company_code"])
        self.api.return_value = {"ok": True, "result": {"status": "member"}}
        bot._handle_callback({"id": "fixture", "from": {"id": 10}, "data": "unlink:" + self.user["company_code"], "message": {"chat": {"id": -123, "type": "group"}}})
        self.assertEqual(bot._bind_chat("-123"), self.user["company_code"])

    def test_price_correction_does_not_add_new_prices_to_old_charges(self):
        self.message(QUOTE)
        original = self.latest()
        self.callback("correct", original)
        self.message("Freight: NGN 200,000")
        self.assertIn("won’t append new prices", self.text())
        self.assertEqual(self.latest()["commercial"]["total_amount"], 150000)
        self.assertEqual(self.quota(), 4)

    def test_queue_recovers_an_interrupted_job_and_deduplicates_real_processing(self):
        message = {"chat": {"id": 111, "type": "private"}, "from": {"id": 111}, "message_id": 55, "text": QUOTE}
        jobs.enqueue({"update_id": 55, "message": message})
        now = time.time()
        with patch("telegram_jobs.time.time", return_value=now):
            self.assertIsNotNone(jobs._claim(55))
        with patch("telegram_jobs.time.time", return_value=now + 901):
            jobs.run_job(55)
        jobs.run_job(55)
        self.assertEqual(self.quota(), 4)
        self.assertEqual(self.latest()["record_id"], "tg-111-55")

    def test_scheduler_does_not_fill_all_workers_with_one_chat(self):
        for update_id, chat in ((1, 111), (2, 111), (3, 222)):
            jobs.enqueue({"update_id": update_id, "message": {"chat": {"id": chat}, "text": "fixture"}})
        with patch("workers.submit") as submit:
            jobs.schedule_pending()
        self.assertEqual([call.args[1] for call in submit.call_args_list], [1, 3])

    def test_expired_callback_spinner_does_not_discard_valid_download(self):
        self.message(QUOTE)
        record = self.latest()
        self.callback("checked", record)
        self.api.side_effect = RuntimeError("fixture spinner expired")
        self.callback("pdf", record)
        self.files.assert_called_once()

    def test_download_failure_gives_recovery_instructions(self):
        self.message(QUOTE)
        record = self.latest()
        self.callback("checked", record)
        self.files.side_effect = OSError("fixture send failure")
        self.callback("pdf", record)
        self.assertIn("saved quote is still on the desk", self.text())

    def test_action_reply_keeps_review_number_without_email(self):
        self.message(QUOTE)
        reply = bot._act("111", {"record": self.latest(), "business": bot._chat_business("111")}, "pay", None)
        self.assertIn("Review #", reply)
        self.assertIn("Approvals", reply)

    def test_service_messages_do_not_trigger_quote_intake(self):
        with patch.object(bot, "handle_telegram_message") as handle:
            self.assertTrue(bot.process_telegram_update({"message": {"chat": {"id": 111}, "new_chat_members": [{"id": 222}]}}))
        handle.assert_not_called()

    def test_delivery_conflict_does_not_delete_live_webhook(self):
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fixture", "TELEGRAM_DELIVERY_MODE": "polling"}), patch.object(bot, "_lock_intake"), patch.object(bot, "configure_telegram_commands"), patch.object(bot, "poll_telegram_once", side_effect=RuntimeError("409 Conflict")), patch.object(bot, "poll_email_once") as email, patch("workers.submit"), patch("telegram_jobs.schedule_pending"), patch("automate.time.sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): bot.main()
        email.assert_called_once()
        self.assertNotIn("deleteWebhook", [call.args[0] for call in self.api.call_args_list])

    def test_storage_sync_failure_keeps_local_quote_and_is_retried(self):
        self.message(QUOTE)
        record = self.latest()
        path = self.root / "state" / "records" / f"{record['record_id']}.json"
        with patch.dict(os.environ, {"SUPABASE_URL": "https://fixture.invalid", "SUPABASE_SERVICE_ROLE_KEY": "fixture"}):
            with patch("supabase_sync.sync_quote", side_effect=OSError("fixture offline")):
                bot._store_record(record, record["record_id"], chat_id="111")
            self.assertTrue(json.loads(path.read_text())["sync_pending"])
            with patch("supabase_sync.sync_quote", return_value="fixture-remote-id"):
                bot._retry_pending_record()
        self.assertFalse(json.loads(path.read_text())["sync_pending"])

    def test_webhook_rejects_wrong_secret_and_malformed_json(self):
        import api.main as api
        from fastapi import BackgroundTasks
        class Request:
            headers = {"x-telegram-bot-api-secret-token": "wrong"}
            async def json(self): raise ValueError("fixture invalid JSON")
        with patch.dict(os.environ, {"TELEGRAM_DELIVERY_MODE": "webhook", "TELEGRAM_WEBHOOK_SECRET": "fixture-secret"}):
            with self.assertRaises(api.HTTPException) as result: asyncio.run(api.telegram_webhook(Request(), BackgroundTasks()))
            self.assertEqual(result.exception.status_code, 401)
            Request.headers = {"x-telegram-bot-api-secret-token": "fixture-secret"}
            with self.assertRaises(api.HTTPException) as result: asyncio.run(api.telegram_webhook(Request(), BackgroundTasks()))
            self.assertEqual(result.exception.status_code, 400)

    def test_settings_uses_public_desk_link_but_never_guesses_localhost(self):
        with patch.dict(os.environ, {"DASHBOARD_URL": "", "PAYSTACK_CALLBACK_URL": "http://127.0.0.1:3000/billing"}):
            self.assertIsNone(bot._dashboard_url())
        with patch.dict(os.environ, {"DASHBOARD_URL": "", "PAYSTACK_CALLBACK_URL": "https://desk.example.test/billing"}):
            self.message("/settings")
        markup = self.send.call_args.args[2]
        self.assertEqual(markup["inline_keyboard"][0][0]["url"], "https://desk.example.test/#settings")

    def test_unrecognized_conversation_is_not_billed_as_a_quote(self):
        self.message("What can this service do for my business?")
        self.assertIn("No parse was charged", self.text())
        self.assertEqual(self.quota(), 5)
        self.assertIsNone(bot._load_dialog("111"))

    def test_unpriced_draft_is_only_charged_when_priced_charges_arrive(self):
        self.message("Provider: GIG Logistics\nOrigin: Lagos\nDestination: Houston\n")
        self.assertEqual(self.quota(), 5)
        self.message("Charges:\n- Freight: NGN 150,000\nTotal Amount Due: NGN 150,000")
        self.assertIsNotNone(self.latest())
        self.assertEqual(self.quota(), 4)


if __name__ == "__main__":
    unittest.main()
