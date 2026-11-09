# Quote intake, sourced costs, and performance

The project now supports WhatsApp intake, email attachments, scanned-document/audio uploads, sourced customs estimates, shipment-specific free-time calculations, and recorded processing times. These capabilities do not establish a five-second end-to-end guarantee or guaranteed business outcomes.

## Deploy and connect

### WhatsApp setup in the app

Open **Connections → Connect WhatsApp**. Enter the WaAPI API token (with update permission), numeric instance ID, and linked business number, then select **Save and connect**. The API saves private workspace settings, generates a secret, and registers the message webhook automatically using [WaAPI's update-instance endpoint](https://waapi.readme.io/reference/update-instance). This replaces the instance's existing webhook. The app must be accessed through public HTTPS; the dashboard proxies `/whatsapp/*` callbacks to the API.

Provider failures leave a retryable setup state. An empty token on retry keeps the saved token. Only confirmed webhook registration unlocks connection codes for saved settings. Workers use the workspace's credentials; other workspaces cannot read them. The provider token and secret are never returned by the status endpoint. Verify delivery by linking your own number and sending a sample quote. Existing server-based settings remain supported.

Deploy the dashboard, API, and worker from the same revision. The release must include `dashboard/app/WhatsAppConnection.js`, `dashboard/next.config.js`, `api/operations.py`, `whatsapp_intake.py`, and `whatsapp_settings.py`. Deploying only the settings helper leaves the old instruction panel active. No additional database migration beyond the existing operational storage migration is needed.

### Server steps

1. Apply `supabase/operations.sql` in the project's Supabase SQL editor after the existing `supabase/schema.sql`. It adds private operational state, compare-and-swap claims, and atomic quota receipts. Browser roles have no access. SQLite creates these tables automatically for local development. The new Supabase migration must be applied before enabling these features on Render Free.
2. Deploy the Python API and dashboard. Run one `python automate.py` intake loop alongside the API as the existing container does. Webhooks schedule WhatsApp work immediately; the loop also recovers pending jobs. A sleeping or restarting host adds latency.
3. Set `WAAPI_TOKEN`, the numeric `WAAPI_INSTANCE_ID`, a random `WAAPI_WEBHOOK_SECRET` of at least 32 characters, and `WHATSAPP_BUSINESS_NUMBER` (international digits). Use the existing **waapi.app** provider, not similarly named services. Register its **message** event to `https://YOUR_API/whatsapp/webhook/YOUR_SECRET`. The URL is a credential: keep it out of screenshots, source control, and shared proxy logs. Application access logs redact it; configure infrastructure logs separately.
4. In the desk, open **Connections → WhatsApp intake**, create a code, and send the displayed `/link` command to the connected number. Codes expire after ten minutes and work once. Only private phone-number chats are accepted; groups and WhatsApp LID-only identifiers are not supported. Disconnect a number before moving it to another workspace. `WAAPI_CHAT_ID` restricts trial replies to that recipient; other chats are never silently redirected there.
5. Set `GEMINI_API_KEYS` for scanned PDFs, images, and audio. Uploads allow 10 MB per file; messaging/email readers allow 20 MB, with email limited to ten attachments and 20 MB decoded content. Failed media reads do not consume a parse. Each email attachment becomes a separate quote; the email body is used only when there are no attachments.
6. For email, set `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, and `IMAP_PASSWORD`. An administrator must assign permitted sender addresses in the company's `inbound_emails` array (or the existing `businesses.json` configuration). These are **sender** allowlists, not recipient mailboxes. Forward from an approved company address. The mailbox provider should reject spoofed sender mail. Configure Resend HTTPS for outgoing notifications on Render Free; see [PASSWORD-RESET.md](PASSWORD-RESET.md). Polling runs about once per minute and may be delayed by other work.

Provider references: [WaAPI webhooks](https://waapi.readme.io/reference/webhooks), [message event](https://waapi.readme.io/reference/message-event), [message retrieval](https://waapi.readme.io/reference/get-message-by-id), [media download](https://waapi.readme.io/reference/download-media), [media sending](https://waapi.readme.io/reference/send-media-message).

## Operator workflow

Send text, PDF, photo, or audio. On WhatsApp, reply with missing details, then use `/check` after reviewing the extracted charges. `/pdf` and `/excel` return client documents; `/new` starts another quote and `/status` shows workspace status. Payments and customs submissions still use the separate approval workflow and require connected providers.

Open a saved quote to add costs:

- **Customs calculation:** add an 8- or 10-digit HS tariff profile, source URL, effective dates, and reviewed percentage charges. Choose each charge's bases: CIF, FOB, or earlier charges. Enter goods value, freight, insurance, adjustments, and the assessment exchange rate with its date and source. All four valuation amounts use the selected currency. The freight quote's all-in total is never treated as the goods value. Fixed charges, exemptions, currency-specific fees, and product-specific rules must be reviewed separately; this is not a full NCS tariff database.
- **Shipment free time and charges:** enter the container, inclusive last free date, calculation date, quantity, currency, day basis, and carrier/terminal daily tiers. Choose calendar days or weekdays excluding entered holidays. Save separate schedules for demurrage, detention, and terminal storage. Sources must cover the entire charge period; split periods with changing rates outside this calculator. Quantity applies one schedule to containers with identical terms; otherwise record them separately.
- **Shipment checks:** click the check button in the quote inbox to recalculate saved schedules as of the current Lagos date. It shows deadlines within two days, overdue charges, or sources requiring review. This is an on-demand check, not a live port feed or an automatic reminder service.

Saving a cost calculation clears the quote's checked status. Review it again before sharing. PDF and Excel exports include the saved inputs, sources, formulas, and dates, separately from freight charges so existing duty/storage lines are not counted twice. Saved customs estimates retain their tariff snapshot when a profile changes.

Use the current [NCS tariff resources](https://customs.gov.ng/cet-tariff/), [valuation guidance](https://www.customs.gov.ng/rules-guidelines/customs-valuation), and [exchange-rate source](https://www.customs.gov.ng/exchange-rate) when reviewing applicable inputs. No current official tariff dataset or live NCS rate integration is bundled. Mid-market FX used for cash planning is not the customs assessment rate.

## Retry and delivery behavior

WhatsApp IDs and email content fingerprints deduplicate intake. Quota receipts debit once, including a retry after a storage failure. WhatsApp jobs are claimed per chat in received order. Transient processing failures retry up to three times; a worker crash can be recovered after its 15-minute lease. Provider delivery timeouts are marked `delivery_uncertain` and are not automatically resent, because the provider may already have delivered the reply. Operators should inspect provider logs before retrying a delivery. Completed jobs omit message content.

WaAPI documents timeout retries but does not retry explicit non-2xx webhook responses. Monitor failed webhook delivery and storage availability. After storage recovers, replay the original provider event using its original message ID. Cloud state requires the migration above; an ephemeral Render disk alone does not provide restart durability. Existing Telegram local queues also need durable storage or a separate persistence plan.

## What the measurements mean

The desk reports samples, median, 95th percentile, and counts within five seconds for the most recent workspace quotes. Timings cover reading and quote preparation where recorded; each quote retains its exact measurement scope. They exclude queue/polling delays, final network delivery, file export, and human review. They are not an end-to-end service promise. Render Free cold starts and external AI requests can exceed five seconds.

Before advertising a speed SLA, measure representative text, scanned PDF, image, and audio cases on the deployed system, including cold starts and failures. Revenue gains, saved staff time, and fewer demurrage incidents require customer pilot results. The product assists quoting and approved provider requests; it does not independently move cargo or guarantee NCS clearance.

## Local validation

Run `PYTHON_DOTENV_DISABLED=1 GEMINI_API_KEYS= GEMINI_API_KEY= SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= REDIS_URL= .venv/bin/python -m unittest discover -s tests`. New operational tests mock all AI, messaging, and email delivery. Run `npm test` and `npm run build` in `dashboard`. These checks do not validate live provider credentials, an applied Supabase migration, or production delivery.
