// Record a ~60 s walkthrough of the live dry-run dashboard into docs/research/figures/readme/.
//
// Prerequisite: the screener running against Solana mainnet (real data only), for ~25 min first:
//   python3 . live [--config F.toml]
// Usage (playwright from any local install, e.g. NODE_PATH=<dir>/node_modules):
//   node scripts/figures/video/record.mjs [--live http://127.0.0.1:8765]
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { caption, cardHtml, clickTab } from "./overlay.mjs";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const OUT = path.join(REPO, "docs/research/figures/readme");
const SIZE = { width: 1600, height: 900 };
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const LIVE = arg("--live", "http://127.0.0.1:8765");
const hold = (page, s) => page.waitForTimeout(s * 1000);
const snap = async (parts) => (await fetch(`${LIVE}/api/snapshot?parts=${parts}`)).json();
const fmtInt = (n) => Math.round(n || 0).toLocaleString("en-US");
const seg = (page, v) => page.click(`.seg[data-sl="view"] button[data-v="${v}"]`);

async function scenes(page) {
  const start = (await snap("stats")).stats;
  const day = new Date().toISOString().slice(0, 10);
  await page.setContent(cardHtml({
    title: "trenches-sol",
    sub: `Live dry-run on Solana mainnet, ${day}. Real blocks, real swaps; nothing is signed or sent.`,
    note: "Thesis research (analysis only): which pump.fun and PumpSwap trades get sandwiched, and why?",
  }));
  await hold(page, 5);

  await page.goto(LIVE);
  await page.waitForSelector("#strict-live-rows tr:not([data-empty])", { timeout: 60_000 });
  await caption(page, "Every confirmed slot is decoded and scored; strict rows are real buys a 0.5 SOL attacker could have sandwiched");
  await hold(page, 15);
  await seg(page, "high_roi");
  await caption(page, "Filter: return on the front-run leg of at least 5%, priced on the exact constant-product curve");
  await hold(page, 6);
  await seg(page, "frequent");
  await caption(page, "Filter: pools with repeated strict targets; attackers camp on pools with recent same-side flow");
  await hold(page, 6);
  await seg(page, "");
  await page.evaluate(() => document.querySelector('[data-panel="strict"] .tbl-scroll')?.scrollBy({ top: 600, behavior: "smooth" }));
  await caption(page, "Each flag is settled 14 slots later against the sandwiches that actually landed on chain");
  await hold(page, 8);

  await clickTab(page, "wallet");
  await caption(page, "Simulated wallet: commits by the allocation rule, then settles on the observed sandwich feed");
  await hold(page, 10);

  const { stats: end } = await snap("stats");
  const settled = end.settled_flags || 0;
  await page.setContent(cardHtml({
    title: "This recording, measured",
    sub: `${fmtInt(end.slots)} slots followed live, slots ${fmtInt(start.slot)} to ${fmtInt(end.slot)} (${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC)`,
    stats: [
      [fmtInt(end.swaps), "swaps decoded and scored"],
      [fmtInt(end.sandwiches), "real sandwiches detected"],
      [settled ? ((100 * end.flag_hits) / settled).toFixed(1) + "%" : "n/a", "of settled flags were real victims"],
      [fmtInt(end.strict_vis?.strict), "strict targets"],
    ],
    note: "Dry-run only. Sandwich attacks harm the traders they target; this measures, it does not trade.",
  }));
  await hold(page, 8);
}

async function main() {
  const tmp = mkdtempSync(path.join(os.tmpdir(), "rec-"));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: SIZE, recordVideo: { dir: tmp, size: SIZE } });
  const page = await ctx.newPage();
  await scenes(page);
  await ctx.close();
  await browser.close();
  const webm = path.join(tmp, readdirSync(tmp).find((f) => f.endsWith(".webm")));
  mkdirSync(OUT, { recursive: true });
  const mp4 = path.join(OUT, "platform.mp4");
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", webm, "-c:v", "libx264", "-preset", "slow",
    "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4]);
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", mp4, "-vf",
    "fps=8,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
    path.join(OUT, "platform-preview.gif")]);
  console.log(`wrote ${mp4} and platform-preview.gif (${tmp}/${path.basename(webm)} kept)`);
}

main().catch((e) => { console.error(e); process.exit(1); });
