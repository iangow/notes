#!/usr/bin/env python3
"""Rebuild the Spirit purchase-price waterfalls from Boeing's reported data.

Amounts in the input CSV are US$ millions. Liability amounts are positive
magnitudes; the chart subtracts them. The positive 'Other' line is included
with identifiable assets. Source: Note 2, Boeing's 2026 Q2 Form 10-Q:
https://www.sec.gov/Archives/edgar/data/12927/000162828026050038/ba-20260630.htm

The 2025 column also agrees with Note 2 of Boeing's 2025 Form 10-K:
https://www.sec.gov/Archives/edgar/data/12927/000162828026004357/ba-20251231.htm

Run with Python and Matplotlib. No network access is needed.
"""

import argparse
import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


ROOT = Path(__file__).resolve().parents[1]
COLORS = {
    "assets": "#ef7900",
    "liabilities": "#a74700",
    "consideration": "#111111",
    "goodwill": "#fa9272",
    "net_assets": "#b6b6b6",
}
PERIODS = [("2025-12-31", "Dec. 31, 2025"), ("2026-06-30", "June 30, 2026")]


def billions_label(millions):
    value = (Decimal(millions) / 1000).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"({abs(value):.2f})" if value < 0 else f"{value:.2f}"


def read_totals(path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    totals = {}
    for period, _ in PERIODS:
        values = {group: sum(int(row[period]) for row in rows if row["group"] == group)
                  for group in ("asset", "liability", "goodwill", "consideration")}
        values["net_assets"] = values["asset"] - values["liability"]
        if values["net_assets"] + values["goodwill"] != values["consideration"]:
            raise ValueError(f"Purchase-price allocation does not reconcile for {period}")
        totals[period] = values
    return totals


def draw_panel(ax, title, values):
    assets = values["asset"] / 1000
    liabilities = values["liability"] / 1000
    net_assets = values["net_assets"] / 1000
    consideration = values["consideration"] / 1000
    goodwill = values["goodwill"] / 1000
    width = 0.57
    asset_x, liability_x, consideration_x, goodwill_x = 0, 1, 2.55, 3.55

    ax.set_axisbelow(True)
    ax.set_xlim(-0.6, 4.15)
    ax.set_ylim(-3.1, 11.4)
    ax.set_yticks(range(-2, 11, 2))
    ax.grid(axis="y", color="#e1e1e1", linewidth=0.8)
    ax.tick_params(axis="both", which="both", length=0, labelleft=False, labelbottom=False)
    ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.axhline(0, color="#333333", linewidth=1.0)

    ax.bar(asset_x, assets, width, color=COLORS["assets"], zorder=3)
    ax.bar(liability_x, liabilities, width, bottom=net_assets,
           color=COLORS["liabilities"], zorder=3)
    ax.bar(consideration_x, -net_assets, width, bottom=net_assets,
           color=COLORS["net_assets"], zorder=3)
    ax.bar(consideration_x, consideration, width, color=COLORS["consideration"], zorder=3)
    ax.bar(goodwill_x, goodwill, width, bottom=net_assets, color=COLORS["goodwill"], zorder=3)

    def connector(left, right, height):
        ax.plot([left + width / 2, right - width / 2], [height, height],
                color="#404040", linewidth=1.0, linestyle=(0, (4, 4)), zorder=4)

    connector(asset_x, liability_x, assets)
    connector(liability_x, consideration_x, net_assets)
    connector(consideration_x, goodwill_x, net_assets)
    connector(consideration_x, goodwill_x, consideration)

    ax.annotate(billions_label(values["asset"]), (asset_x, assets),
                xytext=(0, 8), textcoords="offset points", ha="center", va="bottom")
    ax.annotate(billions_label(-values["liability"]), (liability_x, net_assets),
                xytext=(0, -8), textcoords="offset points", ha="center", va="top")
    ax.annotate(billions_label(values["consideration"]), (consideration_x, consideration),
                xytext=(0, 8), textcoords="offset points", ha="center", va="bottom")
    ax.annotate(billions_label(values["net_assets"]), (consideration_x, net_assets),
                xytext=(0, -8), textcoords="offset points", ha="center", va="top")
    ax.text(goodwill_x, net_assets + goodwill / 2, billions_label(values["goodwill"]),
            ha="center", va="center", fontweight="bold")
    ax.set_title(title + "\n($ billions)", fontsize=14, pad=12)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=ROOT / "migration/data/boeing-spirit-purchase-price-allocation.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "posts/images")
    args = parser.parse_args()
    totals = read_totals(args.data)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11.5,
                         "svg.hashsalt": "spirit-goodwill", "svg.fonttype": "path"}):
        fig, axes = plt.subplots(1, 2, figsize=(12.8, 7.16))
        fig.subplots_adjust(left=0.025, right=0.985, bottom=0.065, top=0.70, wspace=0.09)
        fig.text(0.025, 0.955, "Spirit of Goodwill", fontsize=23, fontweight="bold", va="top")
        fig.text(0.025, 0.895,
                 "How Boeing allocated its $8.4 billion purchase price for Spirit AeroSystems",
                 fontsize=14, va="top")
        handles = [Patch(color=COLORS[key], label=label) for key, label in [
            ("assets", "Identifiable assets acquired"),
            ("liabilities", "Liabilities recognized"),
            ("consideration", "Consideration paid"),
            ("goodwill", "Goodwill"),
        ]]
        fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.02, 0.835),
                   ncol=4, frameon=False, handlelength=1.0, handleheight=1.0,
                   columnspacing=2.2, fontsize=11)
        for ax, (period, title) in zip(axes, PERIODS):
            draw_panel(ax, title, totals[period])
        fig.text(0.025, 0.015, "Source: Boeing, Q2 2026 Form 10-Q, Note 2. Values rounded to $0.01 billion.",
                 fontsize=9, color="#555555", va="bottom")
        stem = args.output_dir / "boeing-spirit-goodwill"
        svg = stem.with_suffix(".svg")
        fig.savefig(svg, metadata={"Date": None})
        svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
        fig.savefig(stem.with_suffix(".png"), dpi=180)
        plt.close(fig)
    for period, values in totals.items():
        print(f"{period}: assets={values['asset']}, liabilities={values['liability']}, "
              f"net assets={values['net_assets']}, consideration={values['consideration']}, "
              f"goodwill={values['goodwill']} ($ millions)")


if __name__ == "__main__":
    main()
