---
name: freight-futuristic-homepage
description: Build a futuristic, animation-rich homepage for a logistics / freight / shipping / cargo company. Use when the user asks for a freight, logistics, shipping, haulage, courier, supply-chain or cargo website, landing page or homepage with a modern, high-tech, animated look (3D globe, live tracking, scroll animations, neon/glass UI).
---

# Futuristic Logistics & Freight Homepage — Master Skill

Goal: ship a homepage that looks like a 2030 logistics-tech company, loads fast,
converts visitors into quote requests, and still works on a cheap phone on a
slow network.

Rule zero: **animation serves conversion.** Every motion either explains the
product (routes, tracking, speed) or guides the eye to the CTA. If it does
neither, cut it.

---

## 1. Default stack (pick unless the user specifies otherwise)

| Need | Choice | Why |
|------|--------|-----|
| Static / quick ship | Vanilla HTML + CSS + JS (ES modules) | Zero build, fastest to deploy |
| App-like / CMS | Next.js + TypeScript | SSR, SEO, image optimisation |
| Scroll animation | GSAP + ScrollTrigger | Timeline control, pinning, scrub |
| Smooth scroll | Lenis | Buttery inertia, plays well with GSAP |
| 3D globe / routes | Three.js (or `three-globe`) | Real WebGL globe with arcs |
| Micro-interactions | CSS transitions + `@property` + `IntersectionObserver` | No JS cost |
| Icons | Inline SVG | Crisp, animatable, no requests |
| Fonts | Space Grotesk / Sora / Inter + JetBrains Mono for data | Techy but readable |

Keep business logic (quote calc, tracking lookup, form validation) in separate
modules / hooks. UI files only render and animate. Never mix the two.

Suggested structure (preserve the user's existing structure if they have one):

```
/css      tokens.css  base.css  sections.css  animations.css
/js       main.js  scroll.js  globe.js  tracker.js  quote.js  utils.js
/assets   img/  video/  models/
index.html
```

---

## 2. Visual language ("future" look)

**Palette (dark-first):**
```css
:root {
  --bg-0: #05070d;          /* near-black base */
  --bg-1: #0b1020;          /* panels */
  --line: rgba(255,255,255,.08);
  --text: #e8ecf8;
  --muted: #8a94b3;
  --cyan: #00e5ff;          /* primary glow */
  --violet: #7c4dff;        /* secondary glow */
  --lime: #b6ff3c;          /* success / "in transit" */
  --amber: #ffb020;         /* warnings / delays */
  --grad: linear-gradient(135deg, var(--cyan), var(--violet));
  --glass: rgba(255,255,255,.04);
  --radius: 18px;
}
```

**Signature elements (use 4–6, not all):**
- Glassmorphism cards: `backdrop-filter: blur(14px)` + 1px gradient border
- Neon glow on hover (`box-shadow` with cyan at low alpha)
- Faint animated grid / perspective floor behind the hero
- Noise + radial gradient blobs that drift slowly
- Monospace data labels (coordinates, tracking IDs, ETA counters)
- Thin HUD-style corner brackets on cards
- Gradient text for the key headline word only
- Scanline / shimmer on loading states

Avoid: stock-photo-only heroes, rainbow gradients, more than 2 glow colours,
text over busy imagery without a scrim.

---

## 3. Page blueprint (section order)

1. **Nav** — sticky, glass, shrinks on scroll. Logo, Services, Tracking, Network, Pricing, Contact, primary CTA "Get a Quote". Mobile: full-screen overlay menu.
2. **Hero** — headline + subhead + 2 CTAs (Get Quote / Track Shipment) + live 3D globe or animated route map. Inline tracking input right in the hero.
3. **Trust strip** — client logos or stats marquee (infinite scroll, pauses on hover).
4. **Live stats** — count-up numbers: shipments delivered, countries/ports, on-time %, tonnes moved.
5. **Services** — Air, Sea, Road, Rail, Warehousing, Customs clearance. Cards with hover tilt + icon animation.
6. **How it works** — pinned scroll sequence: Request → Quote → Pickup → Transit → Delivery. A truck/plane/ship icon travels along an SVG path as you scroll.
7. **Global network** — interactive globe with arcs between hubs; click a hub to see lanes and transit times.
8. **Smart quote widget** — origin, destination, cargo type, weight/CBM → instant estimate (logic in `quote.js`).
9. **Tech / platform** — dashboard mockup that animates in (live status ticks, map pings).
10. **Testimonials** — draggable carousel.
11. **FAQ** — accessible accordion.
12. **Final CTA band** — big gradient, one action.
13. **Footer** — links, offices, social, newsletter, WhatsApp button.

---

## 4. Animation recipes (copy-ready, commented)

### 4.1 Smooth scroll + GSAP wired together
```js
// scroll.js — Lenis drives the scroll, GSAP ScrollTrigger listens to it.
import Lenis from 'lenis';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export function initScroll() {
  // Respect users who ask the OS for less motion.
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const lenis = new Lenis({ lerp: 0.1 });
  // Keep ScrollTrigger in sync with Lenis' virtual scroll position.
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((t) => lenis.raf(t * 1000));
  gsap.ticker.lagSmoothing(0); // avoid jumps after tab switches
}
```

### 4.2 Reveal-on-scroll (headline split by line)
```js
// Fade + rise each element marked data-reveal as it enters the viewport.
gsap.utils.toArray('[data-reveal]').forEach((el) => {
  gsap.from(el, {
    y: 40, opacity: 0, duration: 0.9, ease: 'power3.out',
    scrollTrigger: { trigger: el, start: 'top 85%', once: true },
  });
});
```

### 4.3 Count-up stats
```js
// Animate a number from 0 to data-target when it scrolls into view.
export function countUp(el) {
  const target = +el.dataset.target;
  const obj = { v: 0 };
  gsap.to(obj, {
    v: target, duration: 2, ease: 'power2.out',
    scrollTrigger: { trigger: el, start: 'top 90%', once: true },
    onUpdate: () => (el.textContent = Math.round(obj.v).toLocaleString()),
  });
}
```

### 4.4 Vehicle travelling along a route as you scroll
```html
<svg viewBox="0 0 1000 200">
  <path id="route" d="M20 150 C 250 20, 450 20, 500 100 S 800 180, 980 50"
        fill="none" stroke="url(#g)" stroke-width="3" stroke-dasharray="6 8"/>
  <g id="truck"><!-- inline SVG icon here --></g>
</svg>
```
```js
// Scrubs the truck along the path; needs MotionPathPlugin.
gsap.to('#truck', {
  motionPath: { path: '#route', align: '#route', alignOrigin: [0.5, 0.5], autoRotate: true },
  ease: 'none',
  scrollTrigger: { trigger: '#how', start: 'top top', end: '+=1500', scrub: 1, pin: true },
});
```

### 4.5 Hero 3D globe with animated shipping arcs (Three.js outline)
```js
// globe.js — keep it light: low-poly sphere, dotted land texture, few arcs.
// 1. Sphere (r = 1) with a dotted-world alpha texture, additive cyan atmosphere.
// 2. Hubs = small glowing points placed from lat/lon (see latLonToVec3 below).
// 3. Arcs = QuadraticBezierCurve3 between two hubs, lifted off the surface;
//    animate a bright "packet" along each curve with getPointAt(t).
// 4. Slow auto-rotate; pointer parallax tilts the globe a few degrees.
// 5. Pause rendering when the canvas is off-screen (IntersectionObserver).
export function latLonToVec3(lat, lon, r = 1) {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lon + 180) * (Math.PI / 180);
  return [
    -r * Math.sin(phi) * Math.cos(theta),
     r * Math.cos(phi),
     r * Math.sin(phi) * Math.sin(theta),
  ];
}
```
Fallback: if WebGL is unavailable or the device is low-end
(`navigator.hardwareConcurrency <= 4`), show a pre-rendered looping WebM or an
animated SVG map instead.

### 4.6 Card tilt + glow follow cursor (pure CSS vars + tiny JS)
```js
// Writes the pointer position into CSS vars; CSS draws the glow from them.
document.querySelectorAll('.card').forEach((card) => {
  card.addEventListener('pointermove', (e) => {
    const r = card.getBoundingClientRect();
    card.style.setProperty('--mx', `${e.clientX - r.left}px`);
    card.style.setProperty('--my', `${e.clientY - r.top}px`);
  });
});
```
```css
.card::before {
  content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
  background: radial-gradient(260px circle at var(--mx) var(--my), rgba(0,229,255,.18), transparent 60%);
  opacity: 0; transition: opacity .3s;
}
.card:hover::before { opacity: 1; }
```

### 4.7 Infinite marquee (logos / ports)
```css
.marquee { overflow: hidden; mask-image: linear-gradient(90deg, transparent, #000 10%, #000 90%, transparent); }
.marquee__track { display: flex; gap: 3rem; width: max-content; animation: slide 30s linear infinite; }
.marquee:hover .marquee__track { animation-play-state: paused; }
@keyframes slide { to { transform: translateX(-50%); } } /* track content is duplicated once */
```

### 4.8 Tracking widget (UI vs logic separated)
- `tracker.js` exports `fetchShipment(id)` → returns `{status, steps[], eta, position}`.
- UI renders a vertical timeline; the active step pulses; a progress line fills; the map ping moves to `position`.
- Show skeleton shimmer while loading and a friendly error state for bad IDs.

### 4.9 Other motion ideas (choose sparingly)
Magnetic buttons, cursor spotlight, text scramble on tracking IDs, parallax
container/ship layers, animated grid floor (CSS `perspective` + moving
`background-position`), WebGL particle "cargo" stream, page-load intro
(logo draw-on SVG stroke, ≤1.2s, skippable).

---

## 5. Performance budget (non-negotiable)

- LCP < 2.5s on mid-range 4G; total JS < 250 KB gzipped before the globe lazy-loads.
- Lazy-load Three.js and the globe only when the hero is idle (`requestIdleCallback`) or visible.
- Animate only `transform` and `opacity`; avoid animating `width/height/top/left/box-shadow` on scroll.
- `will-change` only on elements actively animating; remove after.
- Images: AVIF/WebP, `srcset`, explicit width/height (no layout shift), `loading="lazy"` below the fold.
- Video: ≤ 2 MB loop, muted, `playsinline`, poster image, no autoplay on data-saver.
- Cap devicePixelRatio at 2 for the canvas; pause render loops when the tab or section is hidden.
- Mobile: halve particle counts, drop heavy blur, disable cursor-only effects.

## 6. Accessibility & robustness

- `prefers-reduced-motion`: disable smooth scroll, pinning, parallax, auto-rotate; keep fades only.
- Contrast ≥ 4.5:1 for body text on dark backgrounds; never rely on colour alone for status.
- All interactive elements keyboard-reachable with visible focus rings (use the cyan glow).
- Decorative canvases/SVGs `aria-hidden="true"`; real content stays in the DOM as text.
- Forms: labels, inline validation, clear success/error messages, no placeholder-only labels.
- Works with JavaScript disabled for core content and CTAs (progressive enhancement).

## 7. Conversion & SEO checklist

- One primary CTA per viewport ("Get a Quote"); secondary is "Track Shipment".
- Above-the-fold promise in ≤ 12 words + one proof point (stat or client).
- Trust signals near CTAs: licences, insurance, certifications, response-time promise.
- Semantic HTML (`header, main, section, footer`), one `h1`, descriptive meta title/description, Open Graph image.
- `Organization` + `Service` JSON-LD; `LocalBusiness` if there are physical offices.
- Sticky mobile CTA bar (Call / WhatsApp / Quote).

## 8. Optional module — Nigeria / West Africa market

Use when the user is targeting Nigerian customers:
- Currency in ₦ (`Intl.NumberFormat('en-NG', {style:'currency', currency:'NGN'})`).
- Phone validation for +234 numbers (`/^(\+234|0)[789][01]\d{8}$/`).
- WhatsApp click-to-chat on every CTA (`https://wa.me/234XXXXXXXXXX?text=...` prefilled with route/cargo).
- Hubs: Lagos (Apapa, Tin Can, Lekki Deep Sea Port), Port Harcourt, Onne, Abuja, Kano, Murtala Muhammed Airport, plus Accra, Tema, Abidjan, Dubai, Shanghai, Rotterdam.
- Services to highlight: import/export clearance, door-to-door, groupage/LCL, cargo consolidation from China, last-mile.
- Payments: Paystack for deposits / invoices.
- Light pages and data-saver mode matter: compress aggressively.

---

## 9. Workflow when this skill is invoked

1. Confirm (only if missing): company name, services, target region, brand colours/logo, primary CTA. Otherwise invent sensible placeholders and flag them.
2. Output tokens (CSS variables) first, then HTML structure, then section CSS, then JS modules.
3. Keep code heavily commented, explaining *why* for non-obvious decisions.
4. Don't restructure the user's existing code; add to it.
5. Finish with: how to run it, what to replace (logos, copy, API endpoints), and a short list of optional upgrades.

---

## 10. MASTER PROMPT (paste into any AI to generate the site)

```
You are a senior creative developer and UX designer specialising in
logistics-tech websites. Build a complete, production-ready, FUTURISTIC
homepage for a freight & logistics company.

COMPANY
- Name: [COMPANY NAME]
- Tagline: [TAGLINE]
- Services: air freight, sea freight, road haulage, warehousing, customs clearance, last-mile
- Main markets / lanes: [e.g. China → Lagos, Dubai → Abuja, Europe → West Africa]
- Primary CTA: Get a Quote   Secondary CTA: Track Shipment
- Contact: [PHONE] · [WHATSAPP] · [EMAIL]

STACK
- [Vanilla HTML/CSS/JS ES modules | Next.js + TypeScript]
- GSAP + ScrollTrigger, Lenis smooth scroll, Three.js for the hero globe
- No heavy frameworks beyond that; keep it fast.

DESIGN
- Dark, high-tech aesthetic: near-black background, cyan (#00e5ff) and violet
  (#7c4dff) glow accents, lime for "in transit" status, glassmorphism cards,
  HUD-style corner brackets, monospace data labels, subtle animated grid floor.
- Fonts: Space Grotesk (headings), Inter (body), JetBrains Mono (data).
- Fully responsive, mobile-first, pixel-polished spacing and typography.

SECTIONS (in order)
1 Sticky glass nav  2 Hero with 3D rotating globe + animated shipping arcs +
inline tracking input  3 Trust marquee  4 Count-up live stats  5 Services
cards with tilt/glow  6 Pinned scroll "How it works" with a vehicle moving
along an SVG route  7 Interactive global network globe with clickable hubs
8 Smart quote calculator  9 Animated platform/dashboard mockup  10 Testimonial
carousel  11 FAQ accordion  12 Big final CTA band  13 Footer with newsletter
and WhatsApp button.

ANIMATION
- Page-load intro (≤1.2s, skippable), scroll reveals, count-ups, magnetic
  buttons, cursor-follow glow on cards, marquee, route-scrub animation,
  globe auto-rotate with pointer parallax, pulsing live-status dots.
- Animate only transform/opacity. Respect prefers-reduced-motion.
- Lazy-load Three.js; provide a lightweight fallback if WebGL is unavailable.

CODE RULES
- Separate business logic (quote calculation, tracking lookup, validation)
  from UI code, in their own modules.
- Heavily comment the code and explain the reasoning behind complex decisions.
- Semantic HTML, accessible (keyboard, focus rings, aria, contrast ≥ 4.5:1).
- SEO: meta tags, Open Graph, JSON-LD (Organization + Service).
- Performance: LCP < 2.5s, JS < 250 KB before globe, optimised images.

DELIVERABLES
- Complete file tree and every file's full code, no placeholders like "...".
- Clear notes: how to run, what to customise, and 5 optional upgrades.
```

### Master-prompt variants (append one line)
- **Premium/corporate:** "Tone: calm, enterprise-grade, minimal motion, lots of whitespace."
- **Startup/bold:** "Tone: loud, kinetic typography, oversized headlines, aggressive motion."
- **Light mode:** "Use a light theme: white base, deep-navy text, electric-blue accent, soft shadows."
- **Nigeria-focused:** "Apply the Nigeria / West Africa module: ₦ pricing, +234 validation, WhatsApp commerce, Lagos ports, Paystack."