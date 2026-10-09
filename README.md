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
| Telegram bot `@freight_quote_bot` | Accepts text, voice notes, photos, and PDFs. Replies in the chat and emails the longer letter. |
| Email intake | Reads unread mail for the addresses listed on the business, and ignores mail the desk sent itself. |
| Quote API | FastAPI on port 8000. Parse, batch upload, Excel, PDF, company tools, plans, and human reviews. |
| Clearing desk | Next.js app on port 3000. Charts, inbox, delete, port-risk level, fallback rates, and the review queue. |
| Review screen | Vite app in `web/` for checking one normalized quote. |
| Supabase sync | Upserts a priced quote into `quotes`, `line_items`, and `quote_splits` after you run `supabase/schema.sql`. |
| Terminal watcher | A Go program that reads the public PTML Tin Can vessel schedule and posts it to the API. |

New accounts get 5 trial parses. Paystack then offers two monthly plans: ₦15,000 for 200 parses (`quote-200`) and ₦50,000 for 1,000 parses (`quote-1000`). `POST /v1/quotes/parse` and `POST /v1/quotes/batch` reject the call with 402 when the account is over its cap.

## How a quote moves

1. Telegram, email, or `POST /v1/quotes/parse` receives the text or file.
2. `quote_agent.py` extracts the vendor, dates, currency, and charge lines. Gemini is tried first when keys are configured. The rules parser covers the rest.
3. `customs.py` assigns a lane: export, import, cross-trade, domestic, or unknown. The home country comes from the business profile. Incoterms are taken from the document only.
4. `market.py` adds the naira and yuan view, a 2% duty-finance estimate when duty is present, a demurrage buffer from the desk port-risk setting, and a 70/15/12/3 split across the shipping line, trucker, clearing agent, and platform fee.
5. `duty.py` adds an HS-code estimate when the text names a known commodity or already contains an 8-digit code. The lines are import duty, import adjustment tax when the table has one, ETLS 0.5%, CISS 1%, and VAT 7.5%.
6. The record is stored under `state/records/`. Telegram shows the summary and the action buttons. The longer letter goes by email.
7. Voice notes, photos, and PDFs are read after the bot has accepted the message. `POST /telegram/webhook` returns HTTP 200 immediately and finishes that work in the background. The local poller queues the same heavy files so the next Telegram update is not blocked.

Company signup creates a code such as `co-…`. A Telegram chat links with `/link CODE`.

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

On a priced quote, “pay the trucker” calls `PAYOUT_URL` and “clear the cargo” calls `CUSTOMS_CLEAR_URL`. If either address is missing, or the call fails, the bot does not invent a payment or a customs entry. It writes a human review and replies with the review number. The desk button **Human reviews** lists the waiting items. Approve or reject one with `POST /v1/reviews/{id}` and a status of `approved` or `rejected`.

## Honest limits

- Official USD/NGN comes from the open ExchangeRate-API mid-market feed unless you save `cbn_usd_ngn`. That feed is not the Central Bank customs assessment rate. If the feed is down, the desk uses the fallback official rate, which starts at 1,550 and can be changed on the desk or with `FX_FALLBACK_OFFICIAL_USD_NGN`. A missing parallel rate uses the fallback that starts at 1,650 (`FX_FALLBACK_PARALLEL_USD_NGN`) only when the quote is not already in naira.
- Port risk is a desk setting: normal ₦350,000, elevated ₦900,000, severe ₦1,800,000. It is not a live congestion index.
- The duty table is an estimate on the all-in naira figure. It is not an NCS assessment.
- Duty finance, escrow, and payout plans on the desk are ledger rows. Paystack charges only the ₦15,000 or ₦50,000 subscription. No lender disburses funds.
- The bot cannot pay a person or clear cargo until `PAYOUT_URL` and `CUSTOMS_CLEAR_URL` point at a real bank and a real customs system. Until then every such request waits for a person.

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

The web service must stay awake. A sleeping instance stops Telegram long-polling and unread-mail checks. Use a plan that does not spin the service down.

To run the two processes on different hosts later, both need the same `state/` volume. Until then, keep the single container.

## Creator

Michael Unogwu built this desk so a clearing business can take a quote from a chat, an inbox, or a file and answer with one priced record the client can read.
