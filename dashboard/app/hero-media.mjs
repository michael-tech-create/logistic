// Playback policy is independent of the UI so network preferences can be
// verified without starting a video or relying on a particular browser.
export function shouldAutoplayHero({ reducedMotion = false, saveData = false, effectiveType = "", pagePaused = false, locallyPaused = false, visible = false, pageVisible = true, ready = false, manuallyStarted = false }) {
  const constrained = saveData || ["slow-2g", "2g"].includes(effectiveType);
  return ready && visible && pageVisible && !pagePaused && !locallyPaused && (manuallyStarted || (!reducedMotion && !constrained));
}

export function heroVideoSource({ mobile, webm }) {
  const variant = mobile ? "mobile" : "desktop";
  return `/cargo-ship-${variant}.${webm ? "webm" : "mp4"}`;
}
