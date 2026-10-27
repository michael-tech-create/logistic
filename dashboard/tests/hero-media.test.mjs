import assert from "node:assert/strict";
import { stat } from "node:fs/promises";
import test from "node:test";
import { heroVideoSource, shouldAutoplayHero } from "../app/hero-media.mjs";

const ready = { ready: true, visible: true };

test("automatic hero playback waits for the poster and a visible page", () => {
  assert.equal(shouldAutoplayHero({}), false);
  assert.equal(shouldAutoplayHero(ready), true);
  for (const blocked of [{ ready: false }, { visible: false }, { pageVisible: false }, { pagePaused: true }, { locallyPaused: true }]) {
    assert.equal(shouldAutoplayHero({ ...ready, ...blocked }), false);
  }
});

test("reduced motion and constrained connections do not autoplay", () => {
  for (const preference of [{ reducedMotion: true }, { saveData: true }, { effectiveType: "2g" }, { effectiveType: "slow-2g" }]) {
    assert.equal(shouldAutoplayHero({ ...ready, ...preference }), false);
  }
});

test("explicit play can override data savings but never a hidden or paused page", () => {
  const manual = { ...ready, manuallyStarted: true, saveData: true, reducedMotion: true };
  assert.equal(shouldAutoplayHero(manual), true);
  for (const blocked of [{ pageVisible: false }, { visible: false }, { pagePaused: true }, { locallyPaused: true }]) {
    assert.equal(shouldAutoplayHero({ ...manual, ...blocked }), false);
  }
});

test("each browser and viewport gets one local video variant within the size budget", async () => {
  const sizes = {};
  for (const mobile of [true, false]) for (const webm of [true, false]) {
    const src = heroVideoSource({ mobile, webm });
    assert.match(src, /^\/cargo-ship-(mobile|desktop)\.(webm|mp4)$/);
    sizes[src] = (await stat(new URL(`../public${src}`, import.meta.url))).size;
    assert.ok(sizes[src] > 0 && sizes[src] < 2 * 1024 * 1024, `${src} must be under 2 MB`);
  }
  for (const extension of ["webm", "mp4"]) assert.ok(sizes[`/cargo-ship-mobile.${extension}`] < sizes[`/cargo-ship-desktop.${extension}`]);
  assert.ok((await stat(new URL("../public/cargo-ship-poster-960.webp", import.meta.url))).size < 100 * 1024);
});
