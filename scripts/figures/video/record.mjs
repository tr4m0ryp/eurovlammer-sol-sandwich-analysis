// Record the live dashboard (a real `python3 . live` run against Solana mainnet) as a ~60 s
// scripted walkthrough. Nothing is mocked: every row comes from the running screener's API.
//
//   NODE_PATH=<dir with playwright> node scripts/figures/video/record.mjs <url> <out_dir>
//
// Writes <out_dir>/raw.webm and <out_dir>/meta.json (first/last slot, UTC start) for the caption.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [url = "http://127.0.0.1:8781/", outDir = "video-out"] = process.argv.slice(2);
const SIZE = { width: 1600, height: 900 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function stats() {
  const r = await fetch(new URL("api/snapshot?parts=stats", url));
  return (await r.json()).stats;
}

// A small honest caption in the empty header strip: what this is and which live slots it shows.
async function caption(page, startSlot) {
  await page.evaluate((s0) => {
    const el = document.createElement("div");
    el.id = "rec-caption";
    el.style.cssText = "position:fixed;top:27px;left:50%;transform:translateX(-50%);z-index:99;padding:6px 12px;"
      + "border-radius:8px;font:500 12px/16px Geist,system-ui,sans-serif;color:#fff;background:rgba(20,24,40,.85)";
    document.body.appendChild(el);
    const tick = async () => {
      const st = (await (await fetch("api/snapshot?parts=stats")).json()).stats;
      el.textContent = `Live dry run, Solana mainnet, slots ${s0.toLocaleString()}-${st.slot.toLocaleString()},`
        + ` ${st.swaps.toLocaleString()} swaps, nothing traded`;
    };
    tick();
    setInterval(tick, 1000);
  }, startSlot);
}

async function scroll(page, selector, px, steps = 12) {
  for (let i = 0; i < steps; i++) {
    await page.evaluate(([s, d]) => document.querySelector(s)?.scrollBy({ top: d, behavior: "smooth" }), [selector, px / steps]);
    await sleep(250);
  }
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: SIZE, recordVideo: { dir: outDir, size: SIZE } });
  const page = await context.newPage();
  const t0 = new Date().toISOString();
  const first = await stats();
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForSelector("#strict-live-rows tr:not([data-empty])", { timeout: 60_000 });
  await caption(page, first.slot);

  await sleep(14_000);                                              // scene 1: the live strict stream
  const seg = (v) => page.click(`.seg[data-sl="view"] button[data-v="${v}"]`);
  await seg("high_roi"); await sleep(6_000);                        // scene 2: ROI >= 5%
  await seg("frequent"); await sleep(6_000);                        // scene 3: repeat pools
  await seg(""); await sleep(1_500);
  await scroll(page, '[data-panel="strict"] .tbl-scroll', 900);     // scene 4: the target table
  await sleep(2_000);
  await page.click('#tabs .tab[data-tab="wallet"]'); await sleep(8_000);   // scene 5: simulated wallet
  await scroll(page, "main", 700); await sleep(5_000);
  await page.click('#tabs .tab[data-tab="strict"]'); await sleep(6_000);   // scene 6: back to the stream

  const last = await stats();
  const video = page.video();
  await context.close();
  await browser.close();
  fs.renameSync(await video.path(), path.join(outDir, "raw.webm"));
  fs.writeFileSync(path.join(outDir, "meta.json"), JSON.stringify(
    { started_utc: t0, first_slot: first.slot, last_slot: last.slot, swaps: last.swaps,
      sandwiches: last.sandwiches, flags: last.flags }, null, 1));
  console.log(`recorded slots ${first.slot}..${last.slot}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
