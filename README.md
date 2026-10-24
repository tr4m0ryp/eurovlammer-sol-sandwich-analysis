# trenches-sol

**Measuring sandwich attacks on Solana memecoin markets.** Bachelor thesis research (Computer
Science) on market microstructure and liquidity on Solana's pump.fun bonding curve and the
PumpSwap AMM.

> **For analysis purposes only.** This repository is a research instrument. It reads confirmed,
> public blocks, measures how exposed each swap is to a sandwich attack, and labels the attacks
> that really happened. It contains **no code to sign, build or submit transactions**, holds no
> keys, and never trades. Every "profit", "commit" or "wallet" figure below is a **simulation**
> settled against observed data, used to quantify the phenomenon, not to perform it.

## The question

A **sandwich attack** is a form of front-running: an attacker sees a victim's buy, buys first to
push the price up, lets the victim buy at the worse price, then sells into it. The victim's own
slippage limit is the only thing capping the loss.

The thesis asks **which swaps sandwichers actually pick**, and why. "Interesting" is not assumed by
a rule. It is derived from real attacks, robust to per-pool fees and to fast scalpers paying high
priority fees.

> Analysis only: the attacker's side is modelled to explain victim selection. Nothing here executes it.

## How it works

The live screener follows confirmed blocks and runs every swap through five measurement stages:

1. **Decode.** pump.fun and PumpSwap swaps are decoded from each block in true chain order.
2. **Exposure.** Exact constant-product math gives each swap's slippage slack and the **maximum
   extractable sandwich profit** (MESP), with the pool's fee paid on both legs.
3. **Score.** A LightGBM model on 20 features flags the swaps a sandwicher would likely pick.
4. **Visibility and risk gate.** Each buy is tiered by whether it was observable in time, then
   checked for token safety (mint/freeze authority, Token-2022 transfer hooks and fees) and
   opportunity risks. Passing rows are **counted, never acted on**.
5. **Settle.** A delayed labeller detects the real sandwiches a few slots later and grades every
   flag against them, so precision and recall are measured live.

The central exposure measure is **phi**, the price impact a swap causes divided by the round-trip
fee hurdle an attacker pays:

```
impact  i = (1 + n/x)^2 - 1          (buy of n lamports into SOL reserve x)
hurdle  h = (1 + r)/(1 - r) - 1      (r = combined fee rate, both legs)
phi       = i / h                    (> 1: the swap alone can carry a sandwich)
```

Ground truth uses the H1/H2 cross-slot heuristics of Heimbach, Solmaz, Oz and Ferreira Torres
(2026, *No Place to Hide*, arXiv 2609.28115) with Solana parameters, plus an H3 entity filter on
attacker wallets. Cross-slot matters: about 96% of Solana sandwiches span several slots, so a
same-slot detector misses almost all of them.

## Findings so far

Measured on a 24 h pull (216,000 slots, 7.9M swaps) and several live sessions:

- **Fee-normalised exposure works.** phi is the best single swap property (AUC 0.83); slippage
  slack alone is near chance (0.54).
- **Attackers target flow, not single transactions.** Prior same-side pool flow and pool attack
  history are the two strongest features.
- **Selection model.** The full model reaches AUC 0.970 on a held-out time split; live, it flags
  2% of swaps at about 19% precision and 50% recall against a 1.1% base rate.
- **Protection.** A Jito tip lowers the victim rate (8 vs 38 per mille); the `jitodontfront` flag
  barely does (20.5 vs 22.6), consistent with cross-slot attacks bypassing bundle rules.
- **Retail front-running is structurally closed.** Solana has no public mempool and Jito mitigates
  sandwiches, so the measured edge sits with privileged infrastructure. This is a finding, not a
  plan: the repository stays an analysis tool.

Full tables, method and caveats are in `notes/sandwich-screener.md`. The simulated
capital-allocation model is derived in `notes/capital-allocation-framework.md` and tuned by offline
replay in `notes/finetune-report.md`.

## Layout

```
tsol/                  live screener (read-only)
  chain/               transaction and swap decoding (pump.fun, PumpSwap)
  ingest/              confirmed-block follower and paced RPC pool
  metrics/             CP curve, exposure (slack, MESP), features, sandwich detector
  screen/              scorer, delayed labels, risk book, visibility tiers, safety gate
  engine/              simulated capital allocator, settled on observed sandwiches
  store/               Parquet + DuckDB run storage and artifact exports
  serve/               local dashboard (SSE stream, snapshot API)
  run/                 per-block pipeline and entry point
research/sandwich/     offline pipeline: pull, scan, label, evaluate, optimal targets
scripts/               AWS block-pull fleet, replay finetune, cron watchdog
notes/                 findings, framework, infrastructure research
tests/                 unit tests
```

## Running it

Requires Python 3.12 and a read-only Solana RPC endpoint.

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
cp .env.example .env              # fill in ALCHEMY_RPC_URL and/or HELIUS_RPC_URL
.venv/bin/python -m pytest -q
```

Offline study (reproduces the labels and the model):

```bash
.venv/bin/python -m research.sandwich.pull --slots 27000 --out data/raw/blocks_DAY
.venv/bin/python -m research.sandwich.scan --raw data/raw/blocks_DAY --out data/interim/swaps_DAY
.venv/bin/python -m research.sandwich.label --swaps data/interim/swaps_DAY --out data/interim/labels_DAY.parquet
.venv/bin/python -m research.sandwich.evaluate --labels data/interim/labels_DAY.parquet --save
```

Live screener (needs the trained model under `data/models/`):

```bash
set -a; . ./.env; set +a
.venv/bin/python -m tsol.run      # dashboard on http://127.0.0.1:8765
```

Collected data (`data/`) is not versioned; the pipeline above regenerates it from public blocks.

## Scope and ethics

- **Read-only on chain.** The code observes public, confirmed data. No keypairs, signing,
  transaction construction or submission exist in this repository.
- **Simulated economics.** Allocator "wins" and "profit" are counterfactual replays against the
  observed sandwich feed, used to size the phenomenon.
- **Purpose.** Understanding victim selection supports defences: better slippage defaults, routing
  and wallet warnings for users exposed to sandwiching.
- Wallet addresses in outputs are public on-chain identifiers, analysed in aggregate.

This project is for academic analysis. It is not a trading tool and is not financial advice.

## License

trenches-sol is **source-available**, licensed under the [PolyForm Noncommercial License 1.0.0](./LICENSE), **not** an OSI open-source license.

- **You may** use, modify, fork, and share trenches-sol freely for any **noncommercial** purpose, as long as you keep the copyright and `Required Notice:` lines (see [`NOTICE`](./NOTICE)) and credit *"trenches-sol by Keygraph, Inc."*
- **You may not** sell it, bundle it into a paid product, or run it as a paid/hosted service **without a commercial license**.

Copyright (c) 2026 Keygraph, Inc. Commercial licensing enquiries: see [`NOTICE`](./NOTICE).
