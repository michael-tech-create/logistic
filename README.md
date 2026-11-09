# GlobalTrade.ai

**AI-assisted freight quoting and customs operations for clearing teams.**

**Creator: Michael Unogwu**

GlobalTrade.ai turns freight quotes from WhatsApp, Telegram, email, PDFs, images, voice notes, and pasted text into structured records that your team can review, price, and share. It brings quote intake, currency planning, sourced customs estimates, shipment charges, client documents, approval workflows, and subscriptions into one workspace.

The platform supports international routes and company home-country settings. Its customs and cash-planning workflows currently focus on Nigeria; the product name does not imply built-in customs rules for every country.

```text
WhatsApp · Telegram · Email · Uploads · Pasted text · API
                            ↓
                Document reading and extraction
                     Gemini + rules parser
                            ↓
                  Structured freight quote
                            ↓
          FX planning · Customs · Shipment charges
                            ↓
                    Team review and approval
                            ↓
        Client PDF / Excel · Saved records · Chat replies
```

## Features

### Quote intake and AI extraction

- **WhatsApp:** receive quote text, PDFs, images, and voice notes through waapi.app. Link a personal number to its workspace with a single-use command, reply with missing details, review the extracted quote, and request PDF or Excel files in chat.
- **Self-service WhatsApp setup:** enter the API token, instance ID, and business number in the dashboard. **Save and connect** stores workspace settings, generates the security secret, and registers the message webhook automatically. Failed setup can be retried; the provider token is hidden after saving.
- **Telegram:** link a company, submit text or media, complete missing details in chat, check a quote, download files, compare quotes, and request payment or clearance review.
- **Email:** process mail from approved company senders, deduplicate intake, and create a separate quote for each supported attachment. The body is used when there are no attachments. Outgoing notifications require a configured mail provider.
- **Dashboard uploads:** paste quote text or upload PDF, TXT, image, and audio files in batches. Uploads allow 10 MB per file. The shared messaging/email reader allows 20 MB; email is limited to ten attachments and 20 MB of decoded content.
- **Document reading:** extract readable PDF text, read scanned documents and images, and transcribe voice notes when Gemini is configured. Supported audio includes MP3, M4A, WAV, OGG, Opus, and AAC.
- **Structured extraction:** identify carrier/vendor, quote references, dates, origin, destination, currencies, priced charge lines, commodity details, and supplied HS codes. Preserve extraction uncertainty and ask for missing information.
- **Rules fallback:** parse supported text formats with deterministic rules when AI extraction is unavailable. Scanned documents, images, and audio still require the configured media reader.

### Quote workspace and client documents

- **Company workspace:** sign up, sign in, reset a forgotten password, and access records scoped to the authenticated company.
- **Quote inbox:** search and filter loaded records, inspect source text and extraction notes, view processing status, and delete owned quotes.
- **Review and correction:** inspect routes, charges, currencies, and missing inputs; revise the source to create a corrected quote; save a checked status before exporting from the desk.
- **Client packs:** process multiple uploaded files, review each quote, and export a checked pack. The latest pack is restored in the same browser/account.
- **PDF and Excel exports:** download individual quotes and batches. Saved customs and shipment calculations include their inputs, source references, dates, and calculation details.
- **Quote comparison:** compare up to three quotes on the same route through Telegram or the API.
- **Planning views:** retain original currencies, show currency estimates and charge splits, and avoid adding USD and NGN amounts into an unlabeled total.
- **Risk flags:** surface suspicious totals or inconsistent currency estimates for review, with an API workflow for resolving flags.

### Customs, currencies, and shipment costs

- **Trade-lane classification:** classify import, export, domestic, cross-trade, or unknown routes using the company's home country. Incoterms come from the supplied document.
- **Currency planning:** keep foreign-currency freight separate from local charges, provide NGN/USD/CNY views where rates are available, and support saved parallel rates and fallback settings. Quotes already in naira are not converted into naira a second time.
- **Sourced tariff profiles:** save reviewed 8- or 10-digit HS profiles with source URLs, effective dates, charge percentages, and calculation bases.
- **Customs valuation:** calculate from confirmed goods value, freight, insurance, adjustments, and a dated assessment exchange rate. Charges can use CIF, FOB, or earlier charges as their base. A freight total is not assumed to be the goods value.
- **Shipment charges:** calculate demurrage, detention, or terminal storage from container details, an inclusive last free date, quantities, and tiered daily schedules. Support calendar days or weekdays with excluded holidays.
- **Shipment checks:** recalculate saved schedules on demand and show approaching deadlines, overdue charges, or sources needing review. These checks are separate from the terminal watcher.
- **Review history:** retain the tariff snapshot used by a saved calculation. Changing a cost calculation clears the checked status so the quote can be reviewed again.
- **Port-risk planning:** choose normal, elevated, or severe risk settings for planning buffers.
- **Finance and allocation planning:** record duty-finance requests, escrow entries, and payout plans, with a configurable finance-fee estimate and charge allocation. These records do not themselves move money.

### Approvals, billing, and operations

- **Human approvals:** confirm payment or cargo-clearance requests, approve or reject them in the dashboard, and inspect request history.
- **Provider submission:** submit an approved request when a payment or customs provider is connected. An approval can be retained until a provider is available. Atomic submission claims prevent concurrent requests from sending the same approval twice.
- **Delivery uncertainty:** flag uncertain provider responses for verification instead of automatically resending potentially completed payments or messages.
- **Subscriptions:** Paystack checkout, payment verification, webhook processing, and account parse allowances.
- **Usage accounting:** enforce parse limits, retain durable quota receipts for supported intake paths, and avoid charging failed media reads or a second parse for completing an already charged chat draft.
- **Performance measurements:** display recent processing samples, median, 95th percentile, and the count prepared within five seconds. Each quote records what its timing covers.
- **Durable intake:** deduplicate WhatsApp events and email content, process chat jobs in order, recover eligible pending jobs, and retry transient processing failures.
- **Storage:** SQLite for local operation and Supabase-backed storage for hosted records and operational state. Existing local job queues and file-backed state still require durable storage.
- **Terminal integration:** an optional Go watcher reads the public PTML vessel schedule and submits updates; the API also provides terminal scraping/status workflows and review handling for unavailable feeds.
- **Developer access:** authenticated FastAPI endpoints, account API keys, interactive API documentation, health checks, and a minimal MCP JSON-RPC endpoint exposing `parse_freight_quote`.
- **Public website:** product overview, workflow examples, pricing, FAQs, signup, and sign-in entry points. A separate Vite quote-review demonstration remains in `web/`.

## Plans and usage

The prices below are the plans currently configured in the application.

| Plan | Parse allowance | Price |
| --- | --- | --- |
| Trial | 5 parses | Free |
| `quote-200` | 200 parses per 30-day period | ₦15,000 |
| `quote-1000` | 1,000 parses per 30-day period | ₦50,000 |

New quote parsing consumes the account allowance. Parsing endpoints return HTTP 402 when the cap is reached. Reviewing saved quotes and downloading exports do not consume another parse. Subscription payments purchase parsing capacity; they do not fund freight, customs duties, or payouts.

## Everyday workflow

1. **Create a workspace.** Sign up and set the company details and home country.
2. **Choose an intake channel.** Upload files, paste text, or connect WhatsApp, Telegram, or email.
3. **Prepare the quote.** Read the extracted route, charge lines, currency estimates, and source. Supply missing details or correct the source where needed.
4. **Add supported costs.** Apply a reviewed tariff profile and confirmed valuation, or enter the shipment's actual free-time and charge schedule.
5. **Check and share.** Save the checked status, then download a client PDF or Excel file. Review every quote in a client pack before exporting it from the dashboard.
6. **Request approval when needed.** Payment and clearance actions use a separate approval queue and require configured external providers for submission.

The dashboard sections are **Quotes**, **Approvals**, **Connections**, and **Settings**. The homepage is `/`; the workspace is `/desk`; registration opens `/desk?mode=register`.

### Connect WhatsApp without editing server settings

1. In **Connections → Connect WhatsApp**, enter the waapi.app API token, numeric instance ID, and business WhatsApp number, including its country code.
2. Click **Save and connect**. The app saves the details and registers the webhook automatically. The token needs update permission; this replaces any existing webhook on that instance.
3. Create a connection code and send the displayed `/link` command from your own WhatsApp to the business number within ten minutes. The command works once.
4. Wait for the confirmation reply, then send a sample quote and check the inbox.

Your business number must already be linked in WaAPI, and the app must be reachable over public HTTPS. Saved settings and accepted webhook registration do not prove end-to-end delivery. Workspace-owned settings take effect without a restart; legacy environment-based installations remain supported. The hosted database must already have the operational storage migration.

WhatsApp commands include `/help`, `/new`, `/cancel`, `/status`, `/check`, `/pdf`, and `/excel`. Only private phone-number chats are supported; disconnect a personal number before moving it to another workspace. See [the operations guide](docs/OPERATIONS.md) for setup, delivery behavior, and calculation details.

### Telegram and email

Telegram links using the company's `/link CODE`. Commands include `/start`, `/help`, `/new`, `/cancel`, `/status`, `/settings`, `/compare`, `/pay`, `/clear`, and `/unlink`. See [the Telegram workflow](docs/TELEGRAM-WORKFLOW.md). Run `python telegram_diagnostics.py` for local diagnostics; `--live` adds read-only provider checks.

Email uses the configured IMAP mailbox and each company's approved **sender** addresses in `inbound_emails` or the existing business configuration. Outbound notifications use configured Resend or SMTP delivery. See [the operations guide](docs/OPERATIONS.md) and [email/password-reset setup](docs/PASSWORD-RESET.md).

## Run it locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with the keys you use: Gemini, Telegram, mail, Paystack, and, if you want remote storage, Supabase. Copy `businesses.example.json` to `businesses.json` and set the company name, home country, notify address, and inbound addresses.

Start the website and API together:

```bash
cd dashboard
npm install
npm run dev
```

`npm run dev` starts the Python API on `127.0.0.1:8000`, waits until it is ready, then starts Next.js. It automatically uses the project’s `.venv` Python. If the API is already running, it reuses it; if `API_PROXY_URL` points at a remote host, it starts only the website. Ctrl+C stops the processes started by this command. Restart an older `npm run dev` process after updating these scripts.

Open the homepage at http://localhost:3000, the desk at http://localhost:3000/desk, and API docs at http://127.0.0.1:8000/docs. Health is `GET /health`. Starting just the website without an API causes connection-refused errors on sign-in.

To manage the services separately, run `uvicorn api.main:app --reload --port 8000` from the project root and `npm run dev:web` from `dashboard/`. Telegram/email intake is separate: run `python automate.py` from the root when needed, with only one copy running. The development launcher does not start Telegram or email intake.

The terminal watcher reads the live PTML schedule:

```bash
cd terminal-watch
go run .
```

By default it opens `https://www.ptml-nigeria.com/`, takes the first vessel row, and posts it to `POST /v1/terminal/status`. Set `TERMINAL_URL` to point it at another public page, and set `TERMINAL_WEBHOOK_SECRET` in `.env`. The watcher reads that file. If the page cannot be read, the API opens a human review and tells Telegram the feed is down. A container that is still in the yard with 2 or fewer free days left also warns Telegram. The PTML page is a published vessel schedule, not a per-container gate-out record.

## Supabase

The login page includes **Forgot password?** with expiring email reset links. For an existing Supabase deployment, apply [`supabase/password_reset.sql`](supabase/password_reset.sql), configure outbound Resend HTTPS (recommended on Render Free) or SMTP and the public `PASSWORD_RESET_URL`, and redeploy the API and dashboard. SQLite updates automatically. Setup and verification are in [docs/PASSWORD-RESET.md](docs/PASSWORD-RESET.md).

For Paystack checkout errors such as `401 invalid_Key`, update `PAYSTACK_SECRET_KEY` on the Python API service, then restart it. Use `python paystack_diagnostics.py --live` for a read-only credential check. See [docs/PAYSTACK.md](docs/PAYSTACK.md).

`SUPABASE_URL` must be the project HTTP address, `https://<project-ref>.supabase.co`, with the service-role or secret key in `SUPABASE_SERVICE_ROLE_KEY`. Run `supabase/schema.sql` in the Supabase SQL editor before the first sync, then apply `supabase/operations.sql` for WhatsApp settings, intake jobs, quota receipts, tariffs, and shipment calculations. Each saved quote starts at status `pending`.

## Pay, clearance, and human review

On a checked quote, “pay the trucker” or `/pay` opens a confirmation for a payment review; “clear the cargo” or `/clear` opens a clearance review. Confirmation queues a person and replies with the review number. Only approval on the desk attempts `PAYOUT_URL` or `CUSTOMS_CLEAR_URL`. Human approval is saved as `approved` when no provider is connected; nothing is sent. After connecting the provider, use **Send to provider** or `POST /v1/reviews/{id}/execute`. A provider submission is claimed atomically before the call, preventing concurrent approvals from sending it twice. An unconfirmed provider response becomes `execution_uncertain`; verify with the provider before any further action. Successful submission becomes `executed` (provider accepted, not proof of final settlement or clearance). A process interrupted during submission stays `processing` for manual verification rather than automatic resubmission. The **Approvals** section lists requests and recent decisions. Approve or reject through `POST /v1/reviews/{id}` with a status of `approved` or `rejected`.

## Scope and limits

- Official USD/NGN comes from the open ExchangeRate-API mid-market feed unless you save `cbn_usd_ngn`. That feed is not the Central Bank customs assessment rate. If the feed is down, the desk uses the fallback official rate, which starts at 1,550 and can be changed on the desk or with `FX_FALLBACK_OFFICIAL_USD_NGN`. A missing parallel rate uses the fallback that starts at 1,650 (`FX_FALLBACK_PARALLEL_USD_NGN`) only when the quote is not already in naira.
- Port risk is a desk setting: normal ₦350,000, elevated ₦900,000, severe ₦1,800,000. It is not a live congestion index.
- Processing measurements exclude queue time, final delivery, exports, and human review; they are not a five-second end-to-end guarantee.
- Customs estimates require a sourced tariff profile and explicit valuation. They are not an NCS assessment. Shipment charges require the carrier or terminal’s actual dates and rate schedule.
- Duty finance, escrow, and payout plans on the desk are ledger rows. Paystack charges only the ₦15,000 or ₦50,000 subscription. No lender disburses funds.
- The bot cannot pay a person or clear cargo until `PAYOUT_URL` and `CUSTOMS_CLEAR_URL` point at a real bank and a real customs system. Requests require human approval; without a provider, that approval is retained and nothing is sent.

## Layout

```
automate.py          Telegram, email, and intake recovery loop
quote_agent.py       Rules parser and Gemini
customs.py           Lane, notice text, business match
market.py            FX, finance estimate, demurrage, split
shipment_costs.py    Sourced customs and shipment charge calculations
whatsapp_intake.py   Linked WhatsApp intake and durable delivery jobs
whatsapp_settings.py Workspace credentials and automatic webhook registration
media_intake.py      Shared PDF, image, audio, and email reader
operations_store.py  Durable operational state and quota receipts
email_intake.py      Separate, deduplicated email attachment quotes
supabase_sync.py     Remote insert
api/                 FastAPI, billing, exports
dashboard/           GlobalTrade.ai website and workspace
web/                 Single-quote review screen
actions.py           Pay and clear attempts, or a human review
workers.py           Background voice and PDF work
terminal-watch/      Go watcher for the live PTML schedule
supabase/schema.sql  Quotes, line items, splits
```

## Deploy

The GlobalTrade.ai dashboard is Next.js in `dashboard/`. The API and the Telegram/email loop are Python in this repo root. They share `state/` (billing SQLite, quote JSON, Telegram offset). Run them as one container so that folder is one disk. Two Render or Railway services each get a private disk, and the desk would not see quotes the worker saved.

### Desk on Vercel

1. Push this repo to GitHub.
2. Import it in Vercel. Set the root directory to `dashboard/`.
3. Set `API_PROXY_URL` to the public API origin, for example `https://quote-desk-api.onrender.com`. No trailing slash.
4. Set `NEXT_PUBLIC_SITE_URL` to the public website origin for absolute Open Graph image URLs. Leave `NEXT_PUBLIC_API_URL` unset. The desk then calls `/v1/...` on its own host, and `dashboard/next.config.js` proxies that to `API_PROXY_URL`.
5. Set `PAYSTACK_CALLBACK_URL` on the API to `https://<your-vercel-host>/billing`.
6. Deploy the dashboard, Python API, and intake worker from the same revision. Confirm the production deployment uses the latest commit; redeploying an old deployment rebuilds its old code. The WhatsApp form requires the updated dashboard, settings API, worker, and `/whatsapp/*` proxy route.

The desk does not read Supabase. `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are not used.

### API and intake on Render or Railway

`Dockerfile` listens on `$PORT` and starts `python automate.py` beside uvicorn. `render.yaml` is a Render Blueprint: one web service, health check `GET /health`, and a 1 GB disk mounted at `state/`.

Copy the same keys you use in `.env` into the host’s environment: Gemini, Telegram, IMAP, SMTP, Paystack, and Supabase if you sync quotes. Run `supabase/schema.sql` in the Supabase SQL editor before the first sync. Put `businesses.json` in the service if email routing depends on it, or bake a copy into the image before you build.

On Railway, create one service from this repo root, leave the start command as the Dockerfile `CMD`, and add a volume mounted at `/app/state`.

The web service must stay awake. A sleeping instance stops Telegram long-polling and unread-mail checks. The Blueprint above specifies Starter, a paid compute plan without Free's idle spin-down.

### Keep a Free Render service awake

`keep_render_awake.py` sends an HTTP request to `https://logistic-ii6n.onrender.com/health` every 5 minutes. It allows 120 seconds for a cold start and retries failures up to 3 times. It uses only Python's standard library.

Run it on another machine that stays on:

```bash
python3 keep_render_awake.py
```

Set `RENDER_HEALTH_URL` or pass `--url` to target another service. Set `RENDER_PING_SECONDS` or pass `--interval` to change the interval (30–600 seconds). The script reads environment variables directly; it does not load `.env`.

For automatic external pings, push `.github/workflows/keep-render-awake.yml` and the script to your GitHub repository's default branch, with Actions enabled. The workflow schedules a check every 5 minutes and can also be run from **Actions → Keep Render awake → Run workflow**. Optionally set the repository Actions variable `RENDER_HEALTH_URL` to override the URL. It uses `--once`, which exits with status 1 if all retries fail. Scheduled runs consume your repository's Actions allowance.

Run the pinger outside the Render service it watches: a process on that service stops when the service sleeps. These pings are best effort. [Render Free](https://render.com/docs/free) sleeps after 15 minutes without inbound traffic and still has monthly usage limits. [GitHub schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) can be delayed or dropped; public repositories also lose scheduled runs after 60 days without activity. Use a paid Render compute plan when continuous operation is required.

To run the two processes on different hosts later, both need the same `state/` volume. Until then, keep the single container.

## Creator

Michael Unogwu built this desk so a clearing business can take a quote from a chat, an inbox, or a file and answer with one priced record the client can read.

## Validation and further documentation

From the repository root, run the backend tests with provider environment values disabled:

```bash
PYTHON_DOTENV_DISABLED=1 GEMINI_API_KEYS= GEMINI_API_KEY= SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= REDIS_URL= .venv/bin/python -m unittest discover -s tests
```

Check the dashboard from `dashboard/`:

```bash
npm test
npm run build
```

Tests and builds do not verify live credentials or message delivery. Test each configured channel on the deployed application before relying on it.

- [Operations, WhatsApp, customs, shipment costs, and performance](docs/OPERATIONS.md)
- [Telegram workflow and diagnostics](docs/TELEGRAM-WORKFLOW.md)
- [Password reset and outgoing email](docs/PASSWORD-RESET.md)
- [Paystack setup and troubleshooting](docs/PAYSTACK.md)
- [Homepage and local development](docs/HOMEPAGE.md)
- [UX research and implementation scope](docs/UX-RESEARCH.md)
