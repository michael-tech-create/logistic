# Global Customs Quote Desk

**Creator: Michael Unogwu**

Global Customs Quote Desk is an AI-assisted logistics operations platform that converts messy freight quotes from Telegram, email, PDFs, images, and voice notes into normalized customs pricing records, with FX handling, duty estimation, risk controls, human review, exports, and subscription billing.


diagram:
Then immediately show:

Telegram / Email / PDF / Voice
              ↓
       Quote Extraction
       Gemini + Rules
              ↓
     Normalized Quote
              ↓
 ┌────────────┼────────────┐
 FX          Duty        Risk
 │            │            │
 └────────────┼────────────┘
              ↓
        Human Review
              ↓
 Dashboard / Telegram / Email
 PDF / Excel / Client Record
 
## The problem it solves

A clearing agent receives quotes as messy text, screenshots, voice notes, and PDFs. The numbers sit in different currencies. Ocean freight is often in dollars while local charges are in naira. Turning that into a client-ready figure, then into a file the office can keep, takes the same manual pass on every job.

This project does that pass once:

- It reads the quote with a rules parser and, when a Gemini key has quota, with Gemini.
- It keeps dollar freight separate from naira charges instead of treating the whole total as dollars.
- It reads `Origin:` and `Destination:` lines, including city names such as Lagos and Houston, and names the carrier on the quote rather than the desk that received it.
- A quote that is already in naira stays in naira. It is not run through a second exchange rate.
- It shows an official naira figure from a live mid-market rate, or from a rate you save, plus a parallel cash rate when you set one. Fallback rates start at 1,550 official and 1,650 parallel, and the desk can change them without a code edit.
- It estimates Nigerian customs charges when it recognises a commodity or an HS code already written on the quote.
- It holds a quote that looks wrong, such as a dollar total above 100,000 with no naira split, or an all-in naira figure above 500 million.
- It remembers a short follow-up in the same Telegram chat so the client can add a missing port or price.
- It emails the client letter and keeps a shorter summary in Telegram, with buttons for a PDF, a spreadsheet, a WhatsApp link, and a comparison of up to three quotes.

## What you get

| Piece | What it does |
| --- | --- |
| Telegram bot `@freight_quote_bot` | Links a company, accepts text, voice notes, photos, and PDF/TXT files, then guides checking and export. Email copies follow the quote check. |
| Email intake | Reads unread mail for the addresses listed on the business, and ignores mail the desk sent itself. |
| Quote API | FastAPI on port 8000. Parse, batch upload, Excel, PDF, company tools, plans, and human reviews. |
| Clearing desk | Next.js app on port 3000. Charts, inbox, delete, port-risk level, fallback rates, and the review queue. |
| Review screen | Vite app in `web/` for checking one normalized quote. |
| Supabase sync | Upserts a priced quote into `quotes`, `line_items`, and `quote_splits` after you run `supabase/schema.sql`. |
| Terminal watcher | A Go program that reads the public PTML Tin Can vessel schedule and posts it to the API. |

New accounts get 5 trial parses. Paystack then offers two monthly plans: ₦15,000 for 200 parses (`quote-200`) and ₦50,000 for 1,000 parses (`quote-1000`). `POST /v1/quotes/parse` and `POST /v1/quotes/batch` reject the call with 402 when the account is over its cap. Telegram also uses the linked account's allowance for new priced quotes; commands, failed file reads, and replies completing a charged draft do not use another parse.

## How a quote moves

1. Telegram, email, or `POST /v1/quotes/parse` receives the text or file.
2. `quote_agent.py` extracts the vendor, dates, currency, and charge lines. Gemini is tried first when keys are configured. The rules parser covers the rest.
3. `customs.py` assigns a lane: export, import, cross-trade, domestic, or unknown. The home country comes from the business profile. Incoterms are taken from the document only.
4. `market.py` adds the naira and yuan view, a 2% duty-finance estimate when duty is present, a demurrage buffer from the desk port-risk setting, and a 70/15/12/3 split across the shipping line, trucker, clearing agent, and platform fee.
5. `duty.py` adds an HS-code estimate when the text names a known commodity or already contains an 8-digit code. The lines are import duty, import adjustment tax when the table has one, ETLS 0.5%, CISS 1%, and VAT 7.5%.
6. The record is stored under `state/records/` before Telegram shows its buttons. The user checks the extracted details before downloads become available. An email copy is sent after the check when SMTP is configured.
7. Telegram updates are saved to `state/telegram_jobs.sqlite` before polling acknowledges them, or authenticated webhook intake returns HTTP 200. Workers process files and text in order within each chat, allowing other chats to proceed independently. Drafts and file-backed FX caches expire, and pending storage syncs are retried.

Company signup creates a code such as `co-…`. A Telegram chat links with `/link CODE`.

Telegram commands include `/start`, `/help`, `/new`, `/cancel`, `/status`, `/settings`, `/compare`, `/pay`, `/clear`, and `/unlink`. See [docs/TELEGRAM-WORKFLOW.md](docs/TELEGRAM-WORKFLOW.md) for the repaired features, delivery setup, and workflow. Check configuration without sending messages with `python telegram_diagnostics.py`; add `--live` for read-only Telegram credential/webhook checks.

## Run it locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with the keys you use: Gemini, Telegram, mail, Paystack, and, if you want remote storage, Supabase. Copy `businesses.example.json` to `businesses.json` and set the company name, home country, notify address, and inbound addresses.

Three processes:

```bash
# API
uvicorn api.main:app --reload --port 8000

# Desk, from dashboard/
npm install
npm run dev

# Telegram and email intake. Run one copy only.
python automate.py
```

Open the desk at http://localhost:3000 and the API docs at http://127.0.0.1:8000/docs. Health is `GET /health`.

The terminal watcher reads the live PTML schedule:

```bash
cd terminal-watch
go run .
```

By default it opens `https://www.ptml-nigeria.com/`, takes the first vessel row, and posts it to `POST /v1/terminal/status`. Set `TERMINAL_URL` to point it at another public page, and set `TERMINAL_WEBHOOK_SECRET` in `.env`. The watcher reads that file. If the page cannot be read, the API opens a human review and tells Telegram the feed is down. A container that is still in the yard with 2 or fewer free days left also warns Telegram. The PTML page is a published vessel schedule, not a per-container gate-out record.

## Supabase

`SUPABASE_URL` must be the project HTTP address, `https://<project-ref>.supabase.co`, with the service-role or secret key in `SUPABASE_SERVICE_ROLE_KEY`. Run `supabase/schema.sql` in the Supabase SQL editor before the first sync. Each saved quote starts at status `pending`.

## Pay, clearance, and human review

On a checked quote, “pay the trucker” or `/pay` opens a confirmation for a payment review; “clear the cargo” or `/clear` opens a clearance review. Confirmation queues a person and replies with the review number. Only approval on the desk attempts `PAYOUT_URL` or `CUSTOMS_CLEAR_URL`. If a provider is missing or refuses the call, the request stays pending and no payment or clearance is claimed. The **Approvals** section lists requests and recent decisions. Approve or reject through `POST /v1/reviews/{id}` with a status of `approved` or `rejected`.

## Honest limits

- Official USD/NGN comes from the open ExchangeRate-API mid-market feed unless you save `cbn_usd_ngn`. That feed is not the Central Bank customs assessment rate. If the feed is down, the desk uses the fallback official rate, which starts at 1,550 and can be changed on the desk or with `FX_FALLBACK_OFFICIAL_USD_NGN`. A missing parallel rate uses the fallback that starts at 1,650 (`FX_FALLBACK_PARALLEL_USD_NGN`) only when the quote is not already in naira.
- Port risk is a desk setting: normal ₦350,000, elevated ₦900,000, severe ₦1,800,000. It is not a live congestion index.
- The duty table is an estimate on the all-in naira figure. It is not an NCS assessment.
- Duty finance, escrow, and payout plans on the desk are ledger rows. Paystack charges only the ₦15,000 or ₦50,000 subscription. No lender disburses funds.
- The bot cannot pay a person or clear cargo until `PAYOUT_URL` and `CUSTOMS_CLEAR_URL` point at a real bank and a real customs system. Until then every such request waits for a person.

## Desk workflow

The dashboard in `dashboard/` is organized into **Quotes**, **Approvals**, **Connections**, and **Settings**.

1. Choose **Add a quote** and upload readable PDF/TXT files (up to 10 MB each), or paste the original text. The desk shows how many parses this needs.
2. Check the selected quote's route, charges, original text, extraction notes, and currency estimates. Use **Correct quote** to revise the source and create a new quote if needed.
3. Confirm the check and choose **Mark checked and continue**. The check is saved to that quote and survives a refresh.
4. Export the selected quote as PDF or Excel. An uploaded client pack becomes available for export in the interface after every quote in it is checked. The most recent pack is restored in the same browser/account.

Finance requests, escrow ledger entries, and payout plans operate on the quote currently open. Payment and clearance requests have a separate **Approvals** queue with confirmation before a decision. **Connections** explains Telegram linking and checks the email connection; **Settings** contains company preferences and subscription checkout.

The inbox shows recent quotes; search and filters apply to the loaded records. Monetary totals retain their original currencies rather than adding USD and NGN together. The separate `web/` parser demonstration is unchanged.

Research rationale, sources, implementation scope, and follow-up usability tasks are in [docs/UX-RESEARCH.md](docs/UX-RESEARCH.md). Run dashboard workflow checks with `cd dashboard && npm test`.

## Layout

```
automate.py          Telegram and email loop
quote_agent.py       Rules parser and Gemini
customs.py           Lane, notice text, business match
market.py            FX, finance estimate, demurrage, split
duty.py              HS and duty estimate
supabase_sync.py     Remote insert
api/                 FastAPI, billing, exports
dashboard/           Clearing desk
web/                 Single-quote review screen
actions.py           Pay and clear attempts, or a human review
workers.py           Background voice and PDF work
terminal-watch/      Go watcher for the live PTML schedule
supabase/schema.sql  Quotes, line items, splits
```

## Deploy

The clearing desk is Next.js in `dashboard/`. The API and the Telegram/email loop are Python in this repo root. They share `state/` (billing SQLite, quote JSON, Telegram offset). Run them as one container so that folder is one disk. Two Render or Railway services each get a private disk, and the desk would not see quotes the worker saved.

### Desk on Vercel

1. Push this repo to GitHub.
2. Import it in Vercel. Set the root directory to `dashboard/`.
3. Set `API_PROXY_URL` to the public API origin, for example `https://quote-desk-api.onrender.com`. No trailing slash.
4. Leave `NEXT_PUBLIC_API_URL` unset. The desk then calls `/v1/...` on its own host, and `dashboard/next.config.js` proxies that to `API_PROXY_URL`.
5. Set `PAYSTACK_CALLBACK_URL` on the API to `https://<your-vercel-host>/billing`.

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
