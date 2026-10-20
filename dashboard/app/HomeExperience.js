"use client";

import { useEffect, useState } from "react";
import s from "./home.module.css";

const steps = [
  ["Bring in a quote", "Upload a PDF or text file, paste a quote, or send it through your linked Telegram chat."],
  ["Check what matters", "Review the route, currency, and charges. Fill in missing details before marking it checked."],
  ["Prepare your client file", "Export a checked quote or client pack as a PDF or Excel spreadsheet."],
];

export function LegacyDeskLinks() {
  useEffect(() => {
    // Old Telegram and billing links used fragments at the site's root.
    if (["#quotes", "#approvals", "#connections", "#settings"].includes(window.location.hash)) window.location.replace(`/desk${window.location.search}${window.location.hash}`);
    const closeMenu = (event) => {
      const menu = document.getElementById("home-menu");
      if (event.key === "Escape" && menu?.open) { menu.open = false; menu.querySelector("summary").focus(); }
      else if (event.type === "click" && event.target.closest("#home-menu a")) menu.open = false;
    };
    document.addEventListener("keydown", closeMenu); document.addEventListener("click", closeMenu);
    return () => { document.removeEventListener("keydown", closeMenu); document.removeEventListener("click", closeMenu); };
  }, []);
  return null;
}

export function WorkflowPreview() {
  const [step, setStep] = useState(0);
  return <div className={s.workflowGrid}>
    <div className={s.stepList} aria-label="Explore the quote workflow">{steps.map(([title, text], index) => <button key={title} type="button" className={s.step} aria-pressed={step === index} aria-controls="workflow-example" onClick={() => setStep(index)}><span className={s.stepNum}>0{index + 1}</span><span><strong>{title}</strong><span className={s.stepDescription}>{text}</span></span></button>)}</div>
    <div className={s.preview} id="workflow-example" aria-live="polite" aria-atomic="true">
      <div className={s.previewBar}><span><span className={s.windowDots}>● ● ●</span> CLEARING DESK</span><span>ILLUSTRATIVE EXAMPLE</span></div>
      <div className={`${s.previewBody} ${s.previewContent}`} key={step}><span className={s.mono}>STEP 0{step + 1} / 03</span><h3>{["A quote comes in.", "Every detail, in view.", "Ready for your client."][step]}</h3><p>{["Start with the information you already have.", "Check the source before you mark it checked.", "A clear file, in the format you need."][step]}</p>
        {step === 0 && <div className={s.demoQuote}>{"Provider: Example Freight\nRoute: Shanghai → Lagos\nOcean freight: USD 2,400\nDocumentation: USD 100"}</div>}
        {step === 1 && <div><div className={s.demoRow}><span>Route</span><strong>Shanghai → Lagos</strong></div><div className={s.demoRow}><span>Original quote total</span><strong>USD 2,500.00</strong></div><div className={s.demoRow}><span>2 extracted charges</span><strong>Ready for your check</strong></div><div className={s.demoNotice}>You review and confirm the details.</div></div>}
        {step === 2 && <><div className={s.download}><div><strong>Client quote · Shanghai to Lagos</strong><span>PDF or Excel · Original currency preserved</span></div></div><p className={s.demoNotice}>Exports are available after checking your real quote.</p><a href="/desk?mode=register" className={`${s.button} ${s.buttonSmall}`}>Try your own quote →</a></>}
      </div>
    </div>
  </div>;
}
