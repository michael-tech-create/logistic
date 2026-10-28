"use client";

import { useEffect, useRef, useState } from "react";
import s from "./home.module.css";

const products = [
  ["Intake agent", "Telegram, WhatsApp, and email can bring a quote into your company inbox once those services are connected."],
  ["Quote handoff", "After your team checks a quote, prepare a PDF or Excel file for the person who needs it. The letter keeps the figures already on the record."],
  ["Yard watch", "Look up a container on a public terminal page. The desk can alert you when free time is down to 48 hours."],
  ["Lane compare", "Place up to three saved quotes side by side on landed cost, transit, free days, and risk."],
];

const slides = [
  {
    src: "/agent-quote-folder.webp",
    width: 960,
    height: 795,
    alt: "The logistics quote agent carries an open freight folder through a bright office.",
    kicker: "01 / INTAKE AGENT",
    title: "The quote agent",
    text: "Reads the route and charges from the message, file, or voice note that arrived.",
  },
  {
    src: "/agent-quote-handoff.webp",
    width: 960,
    height: 795,
    alt: "The logistics quote agent hands a folder to a freight coordinator across a desk.",
    kicker: "02 / QUOTE HANDOFF",
    title: "Taking the quote to a person",
    text: "A checked quote is ready to hand to the person who needs the client file.",
  },
  {
    src: "/agent-yard-tablet.webp",
    width: 960,
    height: 795,
    alt: "The logistics quote agent walks a yard of blue and white shipping containers with a tablet.",
    kicker: "03 / YARD WATCH",
    title: "Watching the container",
    text: "Follows a box on the public terminal page and flags free time that is running out.",
  },
];

const agents = [
  {
    src: "/agent-greeting.webp",
    width: 960,
    height: 795,
    alt: "A logistics desk agent waves while holding a small parcel.",
    name: "Intake agent",
    line: "Send a quote by Telegram, WhatsApp, or email. I bring it into your company inbox once the service is connected. Your team still checks the result.",
  },
  {
    src: "/agent-quote-handoff.webp",
    width: 960,
    height: 795,
    alt: "The handoff agent passes a quote folder to a person at the desk.",
    name: "Handoff agent",
    line: "I take a checked quote to the person who needs the client PDF or Excel. The figures stay the ones already on the record.",
  },
  {
    src: "/agent-yard-tablet.webp",
    width: 960,
    height: 795,
    alt: "The yard agent stands among shipping containers with a tablet.",
    name: "Yard agent",
    line: "I look up the container on the public terminal page and watch the free days, including the point when fewer than 48 hours remain.",
  },
];

function useMotionOff() {
  const [motionOff, setMotionOff] = useState(false);
  useEffect(() => {
    const root = document.getElementById("home-page");
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setMotionOff(media.matches || root?.dataset.motionPaused === "true");
    sync();
    media.addEventListener("change", sync);
    const observer = new MutationObserver(sync);
    if (root) observer.observe(root, { attributes: true, attributeFilter: ["data-motion-paused"] });
    return () => {
      media.removeEventListener("change", sync);
      observer.disconnect();
    };
  }, []);
  return motionOff;
}

function useWideDesk() {
  const [wide, setWide] = useState(true);
  useEffect(() => {
    const media = matchMedia("(min-width: 901px)");
    const sync = () => setWide(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);
  return wide;
}

export function ProductStage() {
  const count = slides.length;
  const motionOff = useMotionOff();
  const wide = useWideDesk();
  const [pos, setPos] = useState(0);
  const [animate, setAnimate] = useState(true);
  const [hold, setHold] = useState(false);
  const [agent, setAgent] = useState(-1);
  const viewportRef = useRef(null);
  const loop = slides.concat(slides);
  const active = slides[((pos % count) + count) % count];
  const shown = agent >= 0 ? agents[agent] : null;

  useEffect(() => {
    const root = viewportRef.current;
    if (!root?.contains(document.activeElement)) return;
    root.querySelector("[data-lead='true']")?.focus();
  }, [pos]);

  useEffect(() => {
    if (pos < count) return undefined;
    const timer = setTimeout(() => {
      setAnimate(false);
      setPos((current) => current - count);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setAnimate(true));
      });
    }, motionOff ? 0 : 640);
    return () => clearTimeout(timer);
  }, [pos, count, motionOff]);

  useEffect(() => {
    if (motionOff || hold) return undefined;
    const timer = setInterval(() => setPos((current) => current + 1), 5200);
    return () => clearInterval(timer);
  }, [motionOff, hold, pos]);

  const next = () => setPos((current) => current + 1);

  return <section id="more-products" className={s.productStage} aria-labelledby="more-products-title">
    <div className={s.container}>
      <div className={s.productLayout}>
        <div className={s.productCopy} data-reveal>
          <div className={s.eyebrow}>MORE OF THE SAME DESK</div>
          <h2 id="more-products-title">Other products.<br />Same quote work.</h2>
          <p>The quote workflow is one part of Clearing Desk. These sit beside it. Your team still checks every figure before a client file goes out.</p>
          <div className={s.productList}>
            {products.map(([title, text]) => <article key={title} className={s.productItem}><strong>{title}</strong><p>{text}</p></article>)}
          </div>
        </div>
        <div
          className={s.productCarousel}
          role="region"
          aria-roledescription="carousel"
          aria-label="Logistics agents and quote handoff"
          onMouseEnter={() => setHold(true)}
          onMouseLeave={() => setHold(false)}
          onFocus={() => setHold(true)}
          onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setHold(false); }}
        >
          <div className={s.productCarouselBar}>
            <span className={s.mono}>CLICK A BOX TO SLIDE THE NEXT ONE</span>
            <span className={s.mono}>{String((pos % count) + 1).padStart(2, "0")} / 0{count}</span>
          </div>
          <div className={s.productViewport} ref={viewportRef}>
            <div className={`${s.productTrack} ${animate && !motionOff ? "" : s.productTrackInstant}`} style={{ "--shift": pos }}>
              {loop.map((slide, index) => {
                const visible = index === pos || (wide && index === pos + 1);
                return <div className={s.productSlide} key={`${slide.title}-${index}`}>
                  <button type="button" className={s.productCard} data-lead={index === pos} onClick={next} tabIndex={visible ? 0 : -1} aria-hidden={!visible}>
                    <img src={slide.src} width={slide.width} height={slide.height} alt={slide.alt} />
                    <span className={s.productCardCopy}><span>{slide.kicker}</span><strong>{slide.title}</strong><small>{slide.text}</small></span>
                    <span className={s.srOnly}>Show the next box.</span>
                  </button>
                </div>;
              })}
            </div>
          </div>
          <p className={s.productStatus}>Front box: {active.title}</p>
        </div>
      </div>
      <div className={s.agentCall} data-reveal>
        <div className={s.agentCallCopy}>
          <div className={s.eyebrow}>ANOTHER AGENT, FROM ABOVE</div>
          <h2>Call the next agent down.</h2>
          <p>One click brings another desk agent in from above. Each one covers a different part of the same quote work.</p>
          <button type="button" className={`${s.button} ${shown ? s.secondary : ""}`} onClick={() => setAgent((current) => (current + 1) % agents.length)}>{shown ? "Call the next agent" : "Call an agent"}</button>
        </div>
        <div className={s.agentStage} aria-live="polite">
          {shown ? <article className={s.agentDrop} key={shown.name}>
            <img src={shown.src} width={shown.width} height={shown.height} alt={shown.alt} />
            <div><span className={s.mono}>NOW ON THE DESK</span><h3>{shown.name}</h3><p>{shown.line}</p></div>
          </article> : <p className={s.agentEmpty}>The stage is clear. Call an agent and they arrive from above.</p>}
        </div>
      </div>
      <div className={s.refLayout}>
        <div className={s.refHero}>
          <div className={s.refCopy}>
            <div className={s.eyebrow}>ONE DESK FOR THE QUOTE</div>
            <h2 id="desk-layout-title">From the message<br />to the person<br />who needs the file.</h2>
            <p>The agent reads the quote that arrived. Your team checks the route and charges. The client PDF or Excel keeps the figures already on the record.</p>
            <div className={s.refActions}>
              <a className={s.button} href="/desk?mode=register">Start free <span aria-hidden="true">→</span></a>
              <a className={s.refLink} href="#workflow">See how it works</a>
            </div>
          </div>
          <div className={s.refArt}>
            <div className={s.refLoop} aria-hidden="true" />
            <span className={s.refDot} aria-hidden="true" />
            <span className={`${s.refDot} ${s.refDotB}`} aria-hidden="true" />
            <span className={`${s.refFace} ${s.refFaceA}`}><img src="/agent-quote-folder.webp" width="960" height="795" alt="The quote agent carries an open freight folder." /></span>
            <span className={`${s.refFace} ${s.refFaceB}`}><img src="/agent-quote-handoff.webp" width="960" height="795" alt="The quote agent hands the folder to a person at the desk." /></span>
            <span className={`${s.refFace} ${s.refFaceC}`}><img src="/agent-yard-tablet.webp" width="960" height="795" alt="The quote agent walks through a yard of shipping containers." /></span>
            <p className={s.refChip}><span>THE ROUTE</span>Collect → Check → Export</p>
          </div>
        </div>
        <div className={s.refCards}>
          <article className={s.refLight}>
            <img src="/agent-quote-handoff.webp" width="960" height="795" alt="The quote agent hands a folder to a person at the desk." />
            <div>
              <span className={s.mono}>QUOTE HANDOFF</span>
              <h3>The file goes to a person.</h3>
              <p>After the quote is checked, prepare a PDF or Excel for the person who needs it. The letter uses the figures already on the record.</p>
            </div>
          </article>
          <article className={s.refDark}>
            <span className={s.mono}>ON YOUR DESK</span>
            <h3>5 free trial parses.</h3>
            <p>No card required. Open a workspace, then connect Telegram. WhatsApp and email follow once those services are set up.</p>
            <a className={s.button} href="/desk?mode=register">Start free <span aria-hidden="true">→</span></a>
          </article>
        </div>
      </div>
    </div>
  </section>;
}
