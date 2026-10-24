"""README figures, light and dark, from the recorded data only (read-only DuckDB over Parquet and
the consolidated screener database). Run with ``TSOL_ROOT`` pointing at a checkout that holds
``data/`` (the 24 h labels and ``screener.duckdb``):

    TSOL_ROOT=/path/with/data python3 -m scripts.figures.readme
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from sol_mev.config import DATA_DIR, REPO  # noqa: E402

OUT = REPO / "docs" / "research" / "figures" / "readme"
THEMES = {"light": {"bg": "#ffffff", "fg": "#1f2328", "grid": "#d0d7de", "line": "#3b5bdb", "ref": "#8c959f"},
          "dark": {"bg": "#0d1117", "fg": "#e6edf3", "grid": "#30363d", "line": "#74a0ff", "ref": "#6e7681"}}
PHI_EDGES = [0, 0.01, 0.03, 0.1, 0.3, 1, 3, 10, 1e12]
P_EDGES = [0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1.01]


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DATA_DIR / "screener.duckdb"), read_only=True,
                          config={"memory_limit": "6GB", "threads": 4})


def phi_rates(con, labels: Path) -> list[tuple[str, float, int]]:
    """Victim rate (per mille) by phi bin over every non-attacker swap of the 24 h labels."""
    cases = " ".join(f"when phi < {hi} then {i}" for i, hi in enumerate(PHI_EDGES[1:]))
    rows = con.execute(f"""
        with s as (select role, bot, sol::double n, greatest(x_pre, 1)::double x, fee_bps / 1e4 r, is_buy
                   from read_parquet('{labels}') where role in ('', 'victim')
                     and signer not in (select distinct attacker from read_parquet('{labels}')
                                        where bot and role in ('front', 'back'))),
             f as (select role, bot, (case when is_buy then pow(1 + n / x, 2) - 1
                                          else 1 - pow(1 - least(n / x, 0.999), 2) end)
                                     / greatest((1 + r) / (1 - r) - 1, 1e-4) phi from s)
        select case {cases} end b, avg((role = 'victim' and bot)::int) * 1000, count(*)
        from f group by b order by b""").fetchall()
    labels_ = [f"<{PHI_EDGES[1]}"] + [f"{lo}-{hi}" for lo, hi in zip(PHI_EDGES[1:-2], PHI_EDGES[2:-1])] + [f">{PHI_EDGES[-2]}"]
    return [(labels_[int(b)], rate, n) for b, rate, n in rows]


def live_calibration(con) -> list[tuple[float, float, int]]:
    """Live, out-of-sample: mean model score against the observed victim rate, per score bin."""
    cases = " ".join(f"when p < {hi} then {i}" for i, hi in enumerate(P_EDGES[1:]))
    return con.execute(f"""
        with v as (select distinct signature, ev_index from victims),
             s as (select distinct on (signature, ev_index) signature, ev_index, p from swaps where p is not null)
        select avg(p), avg((v.signature is not null)::int), count(*) from s left join v using (signature, ev_index)
        group by case {cases} end order by 1""").fetchall()


def profit_curve(con) -> np.ndarray:
    return np.array(con.execute("select log10_pred, log10_real from optimal_calibration order by 1").fetchall())


def _axes(theme: dict):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    fig.patch.set_facecolor(theme["bg"])
    ax.set_facecolor(theme["bg"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["grid"])
    ax.tick_params(colors=theme["fg"])
    ax.xaxis.label.set_color(theme["fg"])
    ax.yaxis.label.set_color(theme["fg"])
    ax.title.set_color(theme["fg"])
    ax.grid(color=theme["grid"], linewidth=0.6, alpha=0.7)
    return fig, ax


def _save(fig, name: str, mode: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}-{mode}.png", bbox_inches="tight", dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)


def draw(phi, cal, curve) -> None:
    for mode, t in THEMES.items():
        fig, ax = _axes(t)
        ax.bar([b for b, _, _ in phi], [r for _, r, _ in phi], color=t["line"])
        ax.set(xlabel="phi = price impact / round-trip fee hurdle", ylabel="victim rate (per mille)",
               title=f"Who gets sandwiched: victim rate by phi ({sum(n for *_, n in phi):,} swaps, 24 h)")
        _save(fig, "phi", mode)

        fig, ax = _axes(t)
        p, hit = np.array([c[0] for c in cal]), np.array([c[1] for c in cal])
        ax.plot([0, max(p.max(), hit.max())], [0, max(p.max(), hit.max())], "--", color=t["ref"], label="perfect")
        ax.plot(p, hit, "o-", color=t["line"], label="live screener")
        ax.set(xlabel="mean model score p in bin", ylabel="observed victim rate",
               title=f"Live calibration ({sum(c[2] for c in cal):,} scored swaps, 4 runs)")
        ax.legend(frameon=False, labelcolor=t["fg"])
        _save(fig, "calibration", mode)

        fig, ax = _axes(t)
        sol = lambda v: 10 ** v / 1e9  # noqa: E731
        ax.plot(sol(curve[:, 0]), sol(curve[:, 0]), "--", color=t["ref"], label="realised = predicted")
        ax.step(sol(curve[:, 0]), sol(curve[:, 1]), where="mid", color=t["line"], label="isotonic fit")
        ax.set(xscale="log", yscale="log", xlabel="predicted MESP (SOL)", ylabel="realised attacker profit (SOL)",
               title="Predicted vs realised profit, single-victim sandwiches")
        ax.legend(frameon=False, labelcolor=t["fg"])
        _save(fig, "profit", mode)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=DATA_DIR / "interim" / "labels_fullday.parquet")
    labels = ap.parse_args().labels
    con = _con()
    phi, cal, curve = phi_rates(con, labels), live_calibration(con), profit_curve(con)
    con.close()
    for row in phi:
        print("phi", row)
    for row in cal:
        print("cal", row)
    draw(phi, cal, curve)
    print("wrote", sorted(p.name for p in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
