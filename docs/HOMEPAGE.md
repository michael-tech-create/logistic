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
- `dashboard/public/brand-emblem-*.webp`: responsive 6 KB/16 KB versions of the currently selected logo. `clearing-desk-icon-*.png` supplies browser icons. Source artwork is preserved.
- `dashboard/app/HomeExperience.js`: illustrative workflow preview, mobile menu behavior, and compatibility with old desk links.
- `dashboard/app/HomeMotion.js`: GSAP/ScrollTrigger/MotionPath effects, quote route, scroll reveals, pointer tilt, and page-wide pause control.
- `dashboard/app/CargoHero.js`, `cargo-hero.module.css`, and `hero-media.mjs`: ship-video presentation, animated quote workflow, playback controls, viewport selection, and loading policy.
- `dashboard/scripts/dev.mjs`: API readiness checks and coordinated development startup.
- `dashboard/app/DeskApp.js`: the existing authenticated workspace, preserved behind `/desk`.
- `dashboard/public/cargo-ship-*`: locally hosted ship videos and responsive poster images. Original robot hero assets are retained in `delivery-robot-*.webp`.

The page follows the skill’s light-mode variant: neutral white surfaces, fine typography, and restrained blue accents. The hero shows the supplied container-ship animation with a separate illustrative “AI extracts → You check → Client file” strip. CSS animates the strip, grid, and format marquee. GSAP animates the scroll-driven quote parcel, section reveals, navigation, and pointer tilt. The workflow preview transitions between steps. Pause motion freezes decorative CSS loops and reverts GSAP effects to visible static content; the choice persists in this browser. Reduced-motion preferences disable animation. Motion libraries load after the initial content. The cargo scene and workflow strip are illustrative; they are not live shipment telemetry or automatic payment approval.

Animation cleanup follows the official [GSAP matchMedia guidance](https://gsap.com/docs/v3/GSAP/gsap.matchMedia()/); route animation uses [MotionPathPlugin](https://gsap.com/docs/v3/Plugins/MotionPathPlugin/). All marketing content, FAQ disclosures, navigation, and workspace links render without JavaScript. The workspace and interactive example need JavaScript. There are no invented delivery statistics, testimonials, partner logos, or tracking services.

## Cargo-video loading

The supplied 1280 × 720 MP4 is 8 seconds and 4.4 MB. The homepage uses silent, locally hosted 24-fps variants:

| Asset | Dimensions | Approximate size |
| --- | --- | --- |
| Desktop VP9 WebM | 960 × 540 | 634 KB |
| Mobile VP9 WebM | 640 × 360 | 334 KB |
| Desktop H.264 MP4 fallback | 960 × 540 | 912 KB |
| Mobile H.264 MP4 fallback | 640 × 360 | 494 KB |
| Responsive WebP posters | 960 × 540 / 640 × 360 | 71 KB / 42 KB |

The poster is server-rendered with responsive sources and fixed dimensions. The video has no URL in the initial HTML and uses `preload="none"`. Its source is attached after the poster loads and the browser becomes idle, only while the scene is visible. Each browser fetches one suitable viewport/codec variant; MP4 is tried if WebM playback fails. Playback is silent and inline. The hero reserves a 16:9 area to avoid layout shifts.

Reduced-motion, Data Saver, and slow-2G/2G visitors initially receive only the poster. They can explicitly select **Play animation**. Playback pauses when the hero is off-screen, the tab is hidden, the local pause button is selected, or page-wide motion is paused. Failed video loading retains the poster and offers a retry. The poster, text, and workspace links also render without JavaScript. No Lottie player, third-party iframe, or video CDN is loaded. The supplied LottieFiles app link was not publicly accessible; this implementation uses the supplied local MP4.

Verification covered actual frame playback, local/page-wide pause, off-screen pause/resume, responsive variants at 320/390/768/1440 px, zero video requests under reduced-motion and Data Saver preferences, a working page without JavaScript, and poster recovery when both video formats fail. One local headless-Chrome simulation at 150 ms latency, 1.6 Mbps throughput, and 4× CPU slowdown measured an LCP of 2.4 seconds with negligible layout shift; deployed results depend on hosting and the visitor’s device/network.

Poster-first loading follows the [web.dev video performance guidance](https://web.dev/learn/performance/video-performance). Asset budgets and playback policy are covered by `dashboard/tests/hero-media.test.mjs`. To replace the footage, transcode both desktop and mobile variants with audio removed, retain WebM and fast-start H.264 fallbacks, regenerate both posters, and keep each clip under 2 MB.

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
