# Telegram bot workflow and repairs

## User journey

1. Send `/start`. An unlinked chat receives setup instructions, without being attached to a default company.
2. Copy `/link CODE` from **Connections** on the clearing desk. Send it to the bot. Group linking and disconnection require a group administrator.
3. Send a carrier quote as text, readable PDF/TXT, photo, voice note, or audio document. Attachments are limited to 20 MB. Images, audio, and scanned PDFs need Gemini; text and readable PDFs do not.
4. Reply to the bot's question if the origin, destination, or priced charges are missing. A bare city name answers the specific port/city question. `/cancel` discards a draft; `/new` starts another quote.
5. The bot saves the quote before presenting its buttons. Open **Check details** to read all charges, terms, and extraction notes, then choose **Mark checked**.
6. Download PDF or Excel, open a WhatsApp sharing link, compare same-route quotes, or request a payment/clearance review. A quote check does not authorize a transfer or release.
7. Payment and clearance requests show the selected quote and ask for confirmation. The bot returns the human review number. A second tap does not create a duplicate active review. Approvals happen separately on the desk.

A newly priced quote uses one account parse. Completing its missing details or correcting its route uses no additional parse. Failed attachment reads, unrecognized conversation, and commands do not consume parses. To change prices, use `/new` and send the complete corrected quote; amounts are never appended as a silent replacement for existing charges. Legacy file-configured businesses without a registered account retain their existing intake behavior.

## Commands

| Command | Action |
| --- | --- |
| `/start`, `/help` | Setup, capabilities, and next steps |
| `/link CODE` | Explicit company linking |
| `/new` | Start a quote without reusing the previous draft |
| `/cancel` | Discard the current draft; saved quotes remain |
| `/status` | Company, allowance, latest quote, and current buttons |
| `/settings` | Open desk settings when a public desk URL is available |
| `/compare` | Compare up to three recent quotes on the same route |
| `/pay`, `/clear` | Request review for the latest checked quote |
| `/unlink` | Confirm disconnection from the current company |

Commands addressed as `/help@bot_username` and company-code `/start` deep links are supported. The process configures the command menu on startup.

## Problems repaired

- A single legacy business automatically captured new chats, and could override explicit workspace links. New chats now require a link; existing workspace links take precedence.
- Message IDs repeat across chats. Stored IDs now include both chat and message IDs.
- Download buttons were sent before background storage completed. Storage now precedes the buttons, with atomic local file replacement.
- File and flag callbacks lacked ownership checks. Actions now verify both the linked company and originating chat, including callbacks from older keyboards.
- A standalone “pay the trucker” was parsed as an unrelated new quote. It now refers explicitly to the latest checked quote and opens a review confirmation. Payment wording inside carrier terms does not trigger payment requests.
- Human review numbers disappeared when SMTP was absent. Every queued request is acknowledged in Telegram with its review number, independently of email.
- TXT files were not read. TXT intake now decodes file contents, unsupported files get recovery instructions, and failed media reads do not use quota.
- A slow voice note could block polling and mail. Polling now durably queues updates; a guarded worker path handles all message types. Jobs stay ordered within a chat, while other chats can run independently.
- Previously queued work could be lost when the process restarted. Polling advances its offset only after the job is persisted. Webhooks persist before returning 200. Interrupted jobs can be reclaimed after their 15-minute lease; transient failures retry up to three times.
- Draft and FX file caches ignored TTL. File-backed entries now expire, including legacy draft/FX entries, and cache writes are atomic.
- A route correction could leave the original route in place. The latest explicit `Origin:`/`Destination:` label now takes precedence.
- Long review messages were silently truncated. Replies are split into bounded messages, with buttons on the last part.
- PDF export failed on naira signs and Yoruba text. Licensed DejaVu fonts are bundled for exports and comparison PDFs.
- Changing 70/30 installments to 50/50 reduced invoice charges. It now records a proposed payment schedule while preserving charges and quote total. Quote changes invalidate the previous check. Naira caps cannot be substituted into foreign-currency charges from Telegram.
- A polling conflict automatically deleted the configured webhook. Delivery modes are now explicit; a conflict is reported without changing the webhook or stopping email checks.
- Webhook intake accepted unauthenticated traffic when no secret was configured. Webhook mode and its shared secret are now required.
- Temporary Supabase failures hid locally saved work. The bot preserves local downloads, labels sync as pending, and retries pending records from the intake loop.

## Configuration and deployment

Default delivery is polling, matching the existing Docker startup:

```dotenv
TELEGRAM_DELIVERY_MODE=polling
TELEGRAM_BOT_TOKEN=...
DASHBOARD_URL=https://your-clearing-desk.example
```

`DASHBOARD_URL` is optional. The bot can also derive the public desk origin from a `PAYSTACK_CALLBACK_URL` ending in `/billing`; it does not turn a localhost callback into a Telegram link. A bare site origin opens `/desk`, while an explicitly configured path is retained.

For webhook delivery, set `TELEGRAM_DELIVERY_MODE=webhook` and a strong `TELEGRAM_WEBHOOK_SECRET`. Register your public `/telegram/webhook` endpoint with Telegram using that same `secret_token`. Do not run a poller against a registered webhook. The app deliberately does not delete or register a webhook on your behalf.

Keep `automate.py` running alongside the API, including in webhook mode, for job recovery, sync retries, and email intake. The Dockerfile already starts both. `state/telegram_jobs.sqlite`, quote files, and cache files need the persistent state volume described in the main README. Ephemeral hosting cannot preserve local queued work through restarts.

Diagnostic commands:

```bash
python telegram_diagnostics.py
python telegram_diagnostics.py --live
```

The first checks configuration without printing secrets. `--live` additionally calls only `getMe` and `getWebhookInfo`; neither sends chat messages. It can identify a webhook/polling conflict, but does not prove the deployed intake process is running.

Payment execution still requires a real `PAYOUT_URL`; customs execution requires `CUSTOMS_CLEAR_URL`. Requests can be queued without those providers, but approval cannot execute them. SMTP and Gemini availability remain dependent on their configured services. Approval and submission now have separate states: `pending` awaits a human decision, `approved` means approved but not sent, `processing` means submission started, `executed` means the provider accepted the request, and `execution_uncertain` requires verification with the provider. A conditional database update claims each submission before calling the provider. Uncertain or interrupted submissions cannot be retried from the desk; verify the outcome before an administrator reconciles the record. Provider-side idempotency and settlement confirmation still depend on the integration.

## Verification

The latest local run passed **70 Python regression checks**: 43 Telegram workflow tests and 27 existing unit checks. The full HTTP integration suite was not rerun for these Telegram changes; webhook mode, authentication, validation, and durable acknowledgement were checked directly in the bot tests. Python compilation and `git diff --check` also passed.

Bot regression tests exercise linking, group permissions, draft follow-ups, parse billing, cancellations, corrections, chat isolation, update replay, downloads, Unicode PDF text, request confirmation/deduplication, media failures, same-route comparisons, cache expiry, persistent job recovery, polling conflicts, authenticated webhook intake, and storage retries. They mock Telegram, media, email, and payment calls and use temporary files. They do not send messages to real chats.

Run the bot-specific checks with:

```bash
python -m unittest discover -s tests -p test_telegram_flow.py
```

Research references: [Telegram bot features](https://core.telegram.org/bots/features) for commands, menus, authorization and inline actions; [Telegram Bot API](https://core.telegram.org/bots/api) for callback acknowledgement, delivery modes and webhook secrets. The broader dashboard research is in [UX-RESEARCH.md](UX-RESEARCH.md).
