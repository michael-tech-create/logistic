import s from "./home.module.css";
import Brand from "./Brand";
import CargoHero from "./CargoHero";
import { FormatMarquee, MotionControl, QuoteRoute } from "./HomeMotion";
import { LegacyDeskLinks, WorkflowPreview } from "./HomeExperience";

export const metadata = {
  title: "Clearing Desk | Freight quotes. Clear next steps.",
  description: "Turn freight quotes from PDFs, text, and Telegram into checked costs and client-ready files. Built for clearing teams. Start with 5 free trial parses.",
  openGraph: { title: "Freight quotes. Clear next steps. | Clearing Desk", description: "One workspace to collect freight quotes, check costs, and prepare client files.", images: [{ url: "/cargo-ship-poster-960.webp", width: 960, height: 540, alt: "A container ship and connected cargo terminal at night" }], type: "website" },
};

function Icon({ type = "box" }) {
  const paths = { box: "m12 2 9 5v10l-9 5-9-5V7l9-5ZM3 7l9 5 9-5M12 12v10M7.5 4.5l9 5", arrow: "M4 12h16m-6-6 6 6-6 6", check: "m5 12 4 4L19 6", file: "M14 3H5v18h14V8l-5-5ZM14 3v5h5M8 12h8M8 16h6", review: "M9 3H5v18h14V3h-4M9 2h6v4H9zM8 12l2 2 5-5M8 18h8", export: "M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5", chat: "M21 3 3 10l7 3 3 7 8-17ZM10 13l6-5" };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[type] || paths.box} /></svg>;
}
function CTA({ children = "Start your free workspace", secondary = false, href = "/desk?mode=register", small = false }) { return <a href={href} className={`${s.button} ${secondary ? s.secondary : ""} ${small ? s.buttonSmall : ""}`}>{children}<Icon type="arrow" /></a>; }

const features = [
  ["file", "Less copying. More clarity.", "Bring PDFs, text files, and Telegram quotes into one inbox. Keep the source alongside the extracted details.", "01 / COLLECT YOUR QUOTES"],
  ["review", "Know what you’re quoting.", "Check routes, charges, and currencies. See missing details and review the NGN estimate before you share.", "02 / CHECK THE DETAILS"],
  ["export", "Make the next step easy.", "Turn checked quotes into a clean PDF or Excel file. Export a single quote or prepare a complete client pack.", "03 / PREPARE CLIENT FILES"],
];
const plans = [
  { name: "Explore", price: "Free", unit: "to get started", parses: "5 trial parses", description: "Get a feel for your new quote workflow.", cta: "Start free", details: ["Check and export your quotes", "Connect your Telegram chat", "No card needed for the trial"] },
  { name: "Desk 200", price: "₦15,000", unit: "/ month", parses: "200 parses per month", description: "Room for your everyday quote work.", cta: "Start with the free trial", details: ["PDF and Excel client exports", "Company quote inbox", "Manage rates and port risk"], featured: true },
  { name: "Desk 1,000", price: "₦50,000", unit: "/ month", parses: "1,000 parses per month", description: "More capacity for a busier desk.", cta: "Start with the free trial", details: ["PDF and Excel client exports", "Company quote inbox", "Manage rates and port risk"] },
];
const faqs = [
  ["What does Clearing Desk actually do?", "Clearing Desk helps you collect and check freight quotes, review charges and estimated NGN costs, and prepare files for your clients. It is quote management software; transport and shipment arrangements stay with your providers."],
  ["How do I bring in my first quote?", "Create a workspace, choose Add a quote, and paste the quote text or upload a PDF or TXT file. Check the extracted route and charges, fill in anything missing, and mark the quote checked before exporting."],
  ["Can I use it from Telegram?", "Yes. Open Connections inside your workspace, copy your company’s link command, and send it to your Telegram bot. Once linked, you can send quote text, PDFs, photos, and voice notes. Photo and voice processing require the configured media service."],
  ["What counts as a parse?", "A new quote submitted for extraction uses one parse. A file in an upload batch counts separately. Checking and exporting saved quotes do not use parses. Your workspace shows your remaining allowance."],
  ["Does approving a request send a payment?", "Approval records a human decision. A payment or customs request can only be submitted when your administrator has connected the matching provider. Without a provider, the approval is saved and nothing is sent. After connecting one, use Send to provider in Approvals."],
  ["How do I choose a paid plan?", "Start with the free trial. When you need more parses, open Settings in your workspace and choose the 200-parse or 1,000-parse plan. Plan checkout uses Paystack when configured by the administrator."],
];

export default function HomePage() {
  const schema = { "@context": "https://schema.org", "@graph": [{ "@type": "Organization", "@id": "#organization", name: "Clearing Desk", description: "Freight quote management software for clearing teams." }, { "@type": "Service", name: "Freight quote processing", provider: { "@id": "#organization" }, serviceType: "Freight quote extraction, review, and client document preparation", areaServed: "Nigeria" }] };
  return <div className={s.site} id="home-page">
    <LegacyDeskLinks />
    <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(schema).replace(/</g, "\\u003c") }} />
    <a className={s.skip} href="#main">Skip to content</a>
    <header className={s.header}><div data-scroll-progress className={s.scrollProgress} /><div data-nav className={`${s.container} ${s.nav}`}><Brand /><nav className={s.navLinks} aria-label="Main navigation"><a href="#features">The platform</a><a href="#workflow">How it works</a><a href="#pricing">Pricing</a><a href="#faq">FAQs</a></nav><div className={s.navActions}><a href="/desk">Sign in</a><CTA small>Start free</CTA></div><details id="home-menu" className={s.mobileMenu}><summary>Menu ☰</summary><nav aria-label="Mobile navigation"><a href="#features">The platform</a><a href="#workflow">How it works</a><a href="#pricing">Pricing</a><a href="#faq">FAQs</a><a href="/desk">Sign in to your desk →</a></nav></details></div></header>
    <main id="main">
      <section data-hero className={s.hero} aria-labelledby="hero-title"><div className={s.heroGridFloor} aria-hidden="true" /><div className={s.container}>
        <div className={s.heroGrid}><div className={s.heroCopy}><div className={s.eyebrow}><span className={s.dot} /> BUILT FOR THE WORK BEHIND EVERY SHIPMENT</div><h1 id="hero-title">Freight quotes.<br /><span>Clear next steps.</span></h1><p>From a forwarded quote to a file your client can use. Collect, check, and prepare your freight quotes in one connected workspace.</p><div className={s.ctaRow}><CTA>Start free</CTA><CTA secondary href="#workflow">See how it works</CTA></div><p className={s.trial}><Icon type="check" /> 5 free trial parses. No card required.</p></div>
          <CargoHero />
        </div>
        <div className={s.heroFoot}><div><span>A clearer route from intake to client.</span><br /><MotionControl /></div><div className={s.formats}><span><Icon type="file" /> PDF &amp; text</span><span><Icon type="chat" /> Telegram</span><span><Icon type="export" /> PDF &amp; Excel exports</span></div></div>
      </div></section>
      <FormatMarquee />
      <section id="features" className={s.section}><div className={s.container}><div className={s.sectionHead} data-reveal><div><div className={s.eyebrow}>01 / ONE CONNECTED WORKSPACE</div><h2>Less back and forth.<br />More moving forward.</h2></div><p>Your quote workflow deserves the same attention as the shipment itself. Keep the details together, from the first message to the final file.</p></div><div className={s.cards}>{features.map(([icon, title, text, foot]) => <article className={s.card} key={title} data-reveal data-tilt><div className={s.iconBox}><Icon type={icon} /></div><h3>{title}</h3><p>{text}</p><div className={s.cardFoot}>{foot}</div></article>)}</div></div></section>
      <section id="workflow" className={`${s.section} ${s.workflow}`}><div className={s.container}><div className={s.sectionHead} data-reveal><div><div className={s.eyebrow}>02 / A WORKFLOW THAT MAKES SENSE</div><h2>Three steps.<br />One clear handoff.</h2></div><p>Explore the workflow below, then try it with a quote of your own.</p></div><QuoteRoute /><WorkflowPreview /><div className={s.approvalNote} data-reveal><div><h3>Human decisions. Clear boundaries.</h3><p>Quote checking and payment approval are separate. Provider submissions require your approval and a connected service.</p></div><a href="#faq">Understand approvals ↗</a></div></div></section>
      <section id="pricing" className={s.section}><div className={s.container}><div className={s.sectionHead} data-reveal><div><div className={s.eyebrow}>03 / START SMALL. MAKE ROOM TO GROW.</div><h2>A plan for your desk.</h2></div><p>Try the complete quote workflow first. Choose more capacity in your workspace when you need it.</p></div><div className={s.cards}>{plans.map((plan) => <article key={plan.name} data-reveal className={`${s.card} ${s.plan} ${plan.featured ? s.featured : ""}`}>{plan.featured && <span className={s.planTag}>FOR EVERYDAY QUOTE WORK</span>}<h3>{plan.name}</h3><p>{plan.description}</p><div className={s.price}><strong>{plan.price}</strong><span>{plan.unit}</span></div><span className={s.parseCount}>{plan.parses}</span><ul className={s.planList}>{plan.details.map((detail) => <li key={detail}><Icon type="check" />{detail}</li>)}</ul><CTA secondary={!plan.featured}>{plan.cta}</CTA></article>)}</div><p className={s.pricingNote}>One parse per newly processed quote or uploaded file. Checking and exporting saved quotes use no extra parses.</p></div></section>
      <section id="faq" className={s.section}><div className={`${s.container} ${s.faqLayout}`} data-reveal><div><div className={s.eyebrow}>04 / A FEW THINGS TO KNOW</div><h2>Before you<br />get moving.</h2></div><div className={s.faqList}>{faqs.map(([q, a]) => <details key={q}><summary>{q}</summary><p>{a}</p></details>)}</div></div></section>
      <section className={s.finalCta}><div className={s.container}><div className={s.ctaPanel} data-reveal><div><h2>Your next quote.<br />A clearer way forward.</h2><p>Open your desk and put your first five trial parses to work.</p></div><CTA /></div></div></section>
    </main>
    <footer className={s.footer}><div className={s.container}><div className={s.footerTop}><Brand /><nav className={s.footerLinks} aria-label="Footer navigation"><a href="#features">Platform</a><a href="#workflow">Workflow</a><a href="#pricing">Pricing</a><a href="/desk">Open your desk ↗</a></nav></div><div className={s.footerBottom}><span>© {new Date().getFullYear()} Clearing Desk. Built for the work behind every shipment.</span><span>Freight quote management · Nigeria &amp; beyond</span></div></div></footer>
    <div className={s.mobileCta}><span>5 free trial parses</span><CTA small>Start free</CTA></div>
  </div>;
}
