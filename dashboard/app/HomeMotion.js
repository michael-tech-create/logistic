"use client";

import { useEffect, useState } from "react";
import s from "./home.module.css";

export function MotionControl() {
  const [paused, setPaused] = useState(false);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const preference = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(preference.matches);
    update(); preference.addEventListener("change", update);
    try { setPaused(localStorage.getItem("home_motion_paused") === "true"); } catch {}
    return () => preference.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const root = document.getElementById("home-page");
    root.dataset.motionPaused = String(paused);
    try { localStorage.setItem("home_motion_paused", String(paused)); } catch {}
    if (paused || reduced) return;
    let disposed = false;
    let media;
    // Load animation code after the server-rendered hero; no animation library
    // is needed for reading the page or following its workspace links.
    Promise.all([import("gsap"), import("gsap/dist/ScrollTrigger"), import("gsap/dist/MotionPathPlugin")]).then(([core, scroll, path]) => {
      if (disposed) return;
      const gsap = core.gsap || core.default;
      gsap.registerPlugin(scroll.ScrollTrigger, path.MotionPathPlugin);
      media = gsap.matchMedia(root);
      media.add({ motion: "(prefers-reduced-motion: no-preference)", pointer: "(hover: hover) and (pointer: fine)", desktop: "(min-width: 761px)" }, (context) => {
        if (!context.conditions.motion) return;
        const removers = [];
        const loops = [];
        const observe = (element, callback) => {
          const observer = new IntersectionObserver(([entry]) => callback(entry.isIntersecting), { threshold: .05 });
          observer.observe(element); removers.push(() => observer.disconnect());
        };

        root.querySelectorAll("[data-reveal]").forEach((element) => {
          gsap.from(element, { y: 36, opacity: 0, duration: .85, ease: "power3.out", scrollTrigger: { trigger: element, start: "top 94%", once: true } });
        });

        const orbit = root.querySelector("[data-orbit-marker]");
        const orbitPath = root.querySelector("[data-orbit-path]");
        const orbitTween = orbit && orbitPath ? gsap.to(orbit, { duration: 12, repeat: -1, ease: "none", motionPath: { path: orbitPath, align: orbitPath, alignOrigin: [.5,.5] } }) : null;
        if (orbitTween) loops.push(orbitTween);
        let heroVisible = true;
        const updateVisibility = () => {
          root.dataset.pageHidden = String(document.hidden);
          orbitTween?.paused(!heroVisible || document.hidden);
        };
        observe(root.querySelector("[data-hero]"), (visible) => { heroVisible = visible; root.dataset.offscreen = String(!visible); updateVisibility(); });
        document.addEventListener("visibilitychange", updateVisibility);
        removers.push(() => document.removeEventListener("visibilitychange", updateVisibility));

        const route = root.querySelector("[data-quote-route]");
        gsap.to(root.querySelector("[data-route-marker]"), { ease: "none", motionPath: { path: route, align: route, alignOrigin: [.5,.5] }, scrollTrigger: { trigger: root.querySelector("#workflow"), start: "top 85%", end: "bottom 40%", scrub: .8, invalidateOnRefresh: true } });
        gsap.fromTo(root.querySelector("[data-scroll-progress]"), { scaleX: 0 }, { scaleX: 1, ease: "none", scrollTrigger: { start: 0, end: "max", scrub: .2 } });
        if (context.conditions.desktop) gsap.to(root.querySelector("[data-nav]"), { height: 70, ease: "none", scrollTrigger: { start: 50, end: 250, scrub: .4 } });

        // Pointer tilt is opt-in for precise pointing devices; touch retains
        // native scrolling and never incurs pointer animation work.
        if (context.conditions.pointer) {
          root.querySelectorAll("[data-tilt]").forEach((element) => {
            const rotateX = gsap.quickTo(element, "rotationX", { duration: .5, ease: "power2.out" });
            const rotateY = gsap.quickTo(element, "rotationY", { duration: .5, ease: "power2.out" });
            const move = (event) => {
              const box = element.getBoundingClientRect();
              const x = (event.clientX - box.left) / box.width;
              const y = (event.clientY - box.top) / box.height;
              element.style.setProperty("--mx", `${x * 100}%`); element.style.setProperty("--my", `${y * 100}%`);
              rotateX((.5-y)*5); rotateY((x-.5)*6);
            };
            const leave = () => { rotateX(0); rotateY(0); };
            element.addEventListener("pointermove", move); element.addEventListener("pointerleave", leave);
            removers.push(() => { element.removeEventListener("pointermove", move); element.removeEventListener("pointerleave", leave); });
          });
        }
        root.dataset.motionReady = "true";
        return () => { removers.forEach((remove) => remove()); loops.forEach((loop) => loop.kill()); delete root.dataset.motionReady; delete root.dataset.offscreen; delete root.dataset.pageHidden; };
      });
    }).catch(() => { /* Native CSS motion and all page content remain usable. */ });
    // Strict Mode, route changes, pause, and OS preference changes all undo
    // inline styles and ScrollTriggers, leaving every section visible.
    return () => { disposed = true; media?.revert(); };
  }, [paused, reduced]);

  return <button type="button" className={s.motionControl} disabled={reduced} aria-pressed={paused || reduced} onClick={() => setPaused(!paused)}>{reduced ? "Motion reduced by your settings" : paused ? "▶ Resume motion" : "Ⅱ Pause motion"}</button>;
}

export function HeroOrbit() {
  return <svg className={s.orbitGraphic} viewBox="0 0 600 540" fill="none" aria-hidden="true"><path data-orbit-path d="M44 290 C-5 160 130 25 305 30 C510 30 625 210 555 355 C490 495 220 555 95 438 C55 400 35 350 44 290Z" stroke="currentColor" strokeWidth="1" strokeDasharray="3 8" /><g data-orbit-marker transform="translate(44 290)"><circle r="7" className={s.orbitMarker} /></g><circle cx="305" cy="30" r="4" fill="white" stroke="currentColor" /><circle cx="555" cy="355" r="4" fill="white" stroke="currentColor" /></svg>;
}

export function QuoteRoute() {
  return <svg className={s.routeGraphic} viewBox="0 0 1000 130" fill="none" aria-hidden="true"><path data-quote-route className={s.routeBase} d="M60 70C220 70 285 20 500 45S740 105 940 60" />{[[60,70,"COLLECT"],[500,45,"CHECK"],[940,60,"EXPORT"]].map(([x,y,label]) => <g key={label}><circle cx={x} cy={y} r="7" className={s.routeNode} /><text x={x} y={y+35} className={s.routeLabel}>{label}</text></g>)}<g data-route-marker transform="translate(60 70)"><rect x="-15" y="-15" width="30" height="30" rx="8" fill="#2269d8" /><path d="m-7-3 7-4 7 4v8l-7 4-7-4v-8ZM-7-3l7 4 7-4M0 1v8" stroke="white" strokeWidth="1.5" /></g></svg>;
}

export function FormatMarquee() {
  const items = ["PDF & TEXT INTAKE", "TELEGRAM CONNECTED", "HUMAN REVIEW", "ORIGINAL CURRENCIES", "CLIENT-READY EXPORTS"];
  return <div className={s.marquee} aria-label="PDF and text intake, Telegram connections, human review, original currencies, and client-ready exports"><div className={s.marqueeTrack} aria-hidden="true">{[0,1].map((set) => <div className={s.marqueeSet} key={set}>{items.map((item) => <span key={item}>{item}</span>)}</div>)}</div></div>;
}
