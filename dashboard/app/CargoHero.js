"use client";

import { useEffect, useRef, useState } from "react";
import { heroVideoSource, shouldAutoplayHero } from "./hero-media.mjs";
import s from "./cargo-hero.module.css";

function FlowIcon({ kind }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={kind === "read" ? "M4 8V4h4m8 0h4v4M4 16v4h4m8 0h4v-4M7 12h10M9 8h6M9 16h6" : kind === "check" ? "M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Zm-4 9 3 3 5-6" : "M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 13h8M8 17h5"} /></svg>;
}

export default function CargoHero() {
  const host = useRef(null);
  const player = useRef(null);
  const controls = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [hasFrame, setHasFrame] = useState(false);
  const [pagePaused, setPagePaused] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const root = document.getElementById("home-page");
    const video = player.current;
    const poster = host.current.querySelector("img");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    let visible = false;
    let ready = false;
    let locallyPaused = false;
    let manuallyStarted = false;
    let disposed = false;
    let useFallback = false;
    let unavailable = false;
    let idle;
    let timer;
    let frame;
    let scheduled = false;

    const update = () => {
      if (disposed) return;
      const paused = root.dataset.motionPaused === "true";
      setPagePaused(paused);
      const play = !unavailable && shouldAutoplayHero({ reducedMotion: reduced.matches, saveData: connection?.saveData, effectiveType: connection?.effectiveType, pagePaused: paused, locallyPaused, visible, pageVisible: !document.hidden, ready, manuallyStarted });
      if (!play) { video.pause(); return; }
      if (!video.getAttribute("src")) {
        const webm = !useFallback && !!video.canPlayType('video/webm; codecs="vp9"');
        video.src = heroVideoSource({ mobile: matchMedia("(max-width: 760px)").matches, webm });
        video.muted = true;
        video.load();
      }
      // Autoplay can be refused by battery-saving or browser policy. Keep the
      // poster and a real play button instead of leaving an empty video box.
      video.play()?.catch(() => { if (!disposed) setPlaying(false); });
    };

    const schedule = () => {
      if (scheduled || disposed) return;
      scheduled = true;
      // The responsive poster paints first. Only then may an idle callback
      // attach a video URL, so the movie never competes for initial HTML/image bandwidth.
      frame = requestAnimationFrame(() => {
        const begin = () => { if (!disposed) { ready = true; update(); } };
        if ("requestIdleCallback" in window) idle = requestIdleCallback(begin, { timeout: 1800 });
        else timer = setTimeout(begin, 200);
      });
    };
    if (poster.complete) schedule();
    else { poster.addEventListener("load", schedule, { once: true }); poster.addEventListener("error", schedule, { once: true }); }

    const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; update(); }, { threshold: .1 });
    observer.observe(host.current);
    const pauseObserver = new MutationObserver(update);
    pauseObserver.observe(root, { attributes: true, attributeFilter: ["data-motion-paused"] });
    const preferenceChanged = () => { manuallyStarted = false; update(); };
    const failedSource = () => {
      if (disposed) return;
      setHasFrame(false);
      // H.264 is the fallback for browsers/devices that cannot decode VP9.
      if (!useFallback && video.getAttribute("src")?.endsWith(".webm")) {
        useFallback = true; video.removeAttribute("src"); update();
      } else { unavailable = true; video.pause(); setPlaying(false); setFailed(true); }
    };
    video.addEventListener("error", failedSource);
    document.addEventListener("visibilitychange", update);
    reduced.addEventListener("change", preferenceChanged);
    connection?.addEventListener?.("change", preferenceChanged);
    controls.current = () => {
      if (!video.paused) locallyPaused = true;
      else {
        locallyPaused = false; manuallyStarted = true; ready = true;
        if (unavailable) { unavailable = false; useFallback = true; video.removeAttribute("src"); setFailed(false); }
      }
      update();
    };
    return () => {
      disposed = true; controls.current = null;
      observer.disconnect(); pauseObserver.disconnect();
      poster.removeEventListener("load", schedule); poster.removeEventListener("error", schedule);
      video.removeEventListener("error", failedSource);
      document.removeEventListener("visibilitychange", update);
      reduced.removeEventListener("change", preferenceChanged);
      connection?.removeEventListener?.("change", preferenceChanged);
      cancelAnimationFrame(frame); clearTimeout(timer);
      if (idle !== undefined) cancelIdleCallback(idle);
      video.pause(); video.removeAttribute("src"); video.load();
    };
  }, []);

  return <figure className={s.scene} ref={host} aria-label="Cargo ship and AI-assisted quote workflow illustration">
    <div className={s.halo} aria-hidden="true" />
    <div className={s.window}>
      <div className={s.toolbar}><span className={s.windowName}><span className={s.statusDot} aria-hidden="true" /> THE CONNECTED QUOTE DESK</span><span className={s.sceneTag}>CARGO IN MOTION</span></div>
      <div className={s.media}>
        <picture><source srcSet="/cargo-ship-poster-640.webp 640w, /cargo-ship-poster-960.webp 960w" sizes="(max-width: 760px) calc(100vw - 40px), (max-width: 1050px) 55vw, 720px" type="image/webp" /><img className={s.poster} src="/cargo-ship-poster-960.webp" width="960" height="540" fetchPriority="high" alt="A container ship beside a cargo terminal, with cranes, stacked containers, and glowing blue connections between automated vehicles." /></picture>
        <video ref={player} data-cargo-video className={`${s.video} ${hasFrame ? s.hasFrame : ""}`} width="960" height="540" loop muted playsInline preload="none" aria-hidden="true" tabIndex={-1} onPlaying={() => { setPlaying(true); setHasFrame(true); }} onPause={() => setPlaying(false)} />
        <div className={s.mediaCaption}><span>SMARTER TOOLS.<br /><strong>CLEARER HANDOFFS.</strong></span><span className={s.corner} aria-hidden="true" /></div>
      </div>
      <div className={s.agentFlow} aria-label="AI extracts quote details, you check them, then prepare a client file">
        <div className={s.flowStep}><span className={s.flowIcon}><FlowIcon kind="read" /></span><span><small>01 / INTAKE</small><strong>AI extracts</strong></span></div><span className={s.connector} aria-hidden="true" />
        <div className={s.flowStep}><span className={s.flowIcon}><FlowIcon kind="check" /></span><span><small>02 / REVIEW</small><strong>You check</strong></span></div><span className={s.connector} aria-hidden="true" />
        <div className={s.flowStep}><span className={s.flowIcon}><FlowIcon kind="file" /></span><span><small>03 / EXPORT</small><strong>Client file</strong></span></div>
      </div>
    </div>
    <figcaption className={s.caption}><span>Illustrative cargo scene · Your team stays in control</span><button type="button" className={s.playback} disabled={pagePaused} aria-label={playing ? "Pause ship animation" : "Play ship animation"} onClick={() => controls.current?.()}><svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">{playing ? <path d="M4 3h3v10H4zm5 0h3v10H9z" /> : <path d="m5 3 8 5-8 5z" />}</svg>{pagePaused ? "Page motion paused" : playing ? "Pause animation" : failed ? "Retry animation" : "Play animation"}</button></figcaption>
  </figure>;
}
