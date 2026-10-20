# Homepage and approval workflow

The Next.js site has a public homepage at `/` and the existing workspace at `/desk`. Start-free buttons open `/desk?mode=register`; existing sessions still open their workspace. Older `/#quotes`, `/#approvals`, `/#connections`, and `/#settings` links redirect to the matching desk section. Telegram and billing links now use `/desk` directly.

## Run locally

Start both the Python API and website with one command:

```bash
cd dashboard
npm install
npm run dev
```

`npm run dev` automatically uses the root `.venv`, starts the local API, waits for readiness, then starts Next.js. It reuses an already running API. A remote `API_PROXY_URL` starts only the website. Ctrl+C stops only its own processes. Use `npm run dev:web` if managing the API separately. Restart any existing development server after this update.

Visit `http://localhost:3000` for the homepage or `/desk` for the workspace. Production checks are `npm test` and `npm run build`. The existing API proxy configuration still applies. Set `NEXT_PUBLIC_SITE_URL` to your public website origin for social preview image URLs; Vercel also supplies a deployment URL automatically.

## Customize

- `dashboard/app/page.js`: brand, feature copy, plan descriptions, FAQs, metadata, and structured data. Plan figures match the current backend plans; update both when changing prices.
- `dashboard/app/home.module.css`: homepage color tokens, layout, mobile styles, and reduced-motion rules.
- `dashboard/app/theme.js`: matching workspace palette, neutral surfaces, typography, buttons, inputs, and tables.
- `dashboard/app/Brand.js` and `brand.module.css`: the shared robot emblem and wordmark used by the homepage, authentication, workspace, password reset, and billing.
- `dashboard/public/clearing-desk-logo-*.webp` and `clearing-desk-icon-*.png`: optimized supplied emblem and browser icons; the source artwork is preserved.
- `dashboard/app/HomeExperience.js`: illustrative workflow preview, mobile menu behavior, and compatibility with old desk links.
- `dashboard/app/HomeMotion.js`: GSAP/ScrollTrigger/MotionPath effects, orbit markers, quote route, scroll reveals, pointer tilt, and pause control.
- `dashboard/scripts/dev.mjs`: API readiness checks and coordinated development startup.
- `dashboard/app/DeskApp.js`: the existing authenticated workspace, preserved behind `/desk`.
- `dashboard/public/delivery-robot-*.webp`: optimized versions of the supplied hero image, approximately 104 KB and 44 KB. The image has responsive sources and explicit dimensions.

The page follows the skill’s light-mode variant: neutral white surfaces, fine typography, and restrained blue accents. CSS animates the hero, grid, annotation, and format marquee. GSAP animates the orbit marker, scroll-driven quote parcel, section reveals, navigation, and pointer tilt. The workflow preview transitions between steps. Pause motion freezes decorative CSS loops and reverts GSAP effects to visible static content; the choice persists in this browser. Reduced-motion preferences disable animation. Motion libraries load after the initial content. The decorative SVG orbit illustrates connectivity; it is not shipment telemetry.

Animation cleanup follows the official [GSAP matchMedia guidance](https://gsap.com/docs/v3/GSAP/gsap.matchMedia()/); route animation uses [MotionPathPlugin](https://gsap.com/docs/v3/Plugins/MotionPathPlugin/). All marketing content, FAQ disclosures, navigation, and workspace links render without JavaScript. The workspace and interactive example need JavaScript. There are no invented delivery statistics, testimonials, partner logos, or tracking services.

## Approval states

An absent provider is a configuration limitation, not a rejected human decision. Previously, approving without a provider returned the request to `pending`, causing repeated approval prompts. Approval is now retained:

| Status | Meaning | Next step |
| --- | --- | --- |
| `pending` | Awaiting a human decision | Review, approve, or reject |
| `approved` | Approved; no provider submission occurred | Connect/repair the provider or quote, then explicitly **Send to provider** |
| `processing` | Submission has started | Wait; if interrupted, verify the outcome with the provider |
| `executed` | Provider accepted the request | Check provider settlement or clearance outcome |
| `execution_uncertain` | Provider outcome was not confirmed | Verify with the provider; resubmission is blocked |
| `rejected` | Human rejected the request | No submission |

`POST /v1/reviews/{id}` records approval or rejection. Approval attempts submission when the matching provider is configured. `POST /v1/reviews/{id}/execute` sends an already approved, unsent payment or customs request. Both claim the row with a conditional status update before calling a provider, in SQLite and Supabase. This prevents concurrent callers from submitting the same review twice. It does not provide provider-side settlement reconciliation; interrupted or uncertain outcomes require manual verification.

`PAYOUT_URL`, `CUSTOMS_CLEAR_URL`, and optional `ACTION_BEARER` are backend administrator settings. Paystack plan billing is separate from these payment/customs providers. Real payout and customs calls were not used in verification.

Optional later improvements: verified customer stories; a configured support contact; analytics with consent where required; provider reconciliation and idempotency integration; usability sessions with clearing agents.
