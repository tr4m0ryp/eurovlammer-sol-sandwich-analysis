"""trenches-sol command line: ``python3 . <command> [args]``. Run without a command for the list.

Every command runs one module as if it were ``python -m <module>``; the module parses its own args.
Analysis only: no command signs, submits or trades.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

COMMANDS = {
    # live measurement
    "live": ("sol_mev.app.live", "follow confirmed blocks, score and settle every swap, serve the dashboard"),
    "artifact": ("sol_mev.app.dashboard.artifact", "write the self-contained dashboard HTML"),
    # run storage and study artifacts
    "consolidate": ("sol_mev.app.store.consolidate", "merge live runs into data/screener.duckdb"),
    "export": ("sol_mev.app.store.export", "export a night's risk rows to Parquet/CSV"),
    "push-night": ("sol_mev.app.store.push.artifact", "night study pages (risk, deciles, hours)"),
    "push-exposure": ("sol_mev.app.store.push.exposure", "exposure study pages (protection shields)"),
    "push-optimal": ("sol_mev.app.store.push.optimal", "optimal-target study pages"),
    "push-visibility": ("sol_mev.app.store.push.visibility", "visibility study pages"),
    # offline research pipeline
    "pull": ("scripts.research.data.pull", "pull a range of confirmed blocks (venue-filtered JSONL)"),
    "scan": ("scripts.research.data.scan", "decode pulled blocks into swap Parquet"),
    "label": ("scripts.research.data.label", "label cross-slot sandwiches and attach exposure"),
    "release": ("scripts.research.data.release.solana", "stage the recorded data for publication (zstd Parquet tree)"),
    "manifest": ("scripts.research.data.release.manifest", "MANIFEST.json (sha256, rows, ranges) for a staging root"),
    "evaluate": ("scripts.research.study.evaluate", "score every filter on a time split; --save the model"),
    "optimal": ("scripts.research.study.optimal", "realistic, sandwichable, profitable target selection"),
    # simulated allocation, offline replay
    "backtest": ("scripts.finetune.backtest", "replay strict events through the simulated allocator"),
    "sweep": ("scripts.finetune.sweep", "random search and refinement of allocator knobs"),
    "report": ("scripts.finetune.report", "train/holdout finetune and the markdown report"),
}


def _usage() -> None:
    print("usage: python3 . <command> [args]\n")
    for name, (_, desc) in COMMANDS.items():
        print(f"  {name:<16} {desc}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        _usage()
        sys.exit(0 if len(sys.argv) < 2 else 2)
    module = COMMANDS[sys.argv[1]][0]
    sys.argv = [f"python3 . {sys.argv[1]}", *sys.argv[2:]]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
