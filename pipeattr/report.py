"""Render a self-contained HTML report (inline CSS and SVG, no JavaScript) and CSV exports."""
import csv
import os
from html import escape

from .attribution import UNATTRIBUTED

MODEL_LABELS = {"first_touch": "First touch", "last_touch": "Last touch",
                "linear": "Linear", "u_shaped": "U-shaped"}


def money(n):
    return f"${n:,.0f}"


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def days(x):
    return "n/a" if x is None else f"{x:.0f} days"


def bar_chart(rows, value_fmt=money, width=640, bar_h=22, gap=6, label_w=150):
    """Horizontal SVG bar chart. rows = [(label, value)]."""
    if not rows:
        return "<p class='muted'>No data.</p>"
    top = max(v for _, v in rows) or 1
    h = len(rows) * (bar_h + gap)
    plot_w = width - label_w - 90
    out = [f"<svg viewBox='0 0 {width} {h}' width='100%' role='img'>"]
    for i, (label, v) in enumerate(rows):
        y = i * (bar_h + gap)
        w = max(v / top * plot_w, 1)
        out.append(f"<text x='0' y='{y + 15}' class='lbl'>{escape(str(label))[:22]}</text>")
        out.append(f"<rect x='{label_w}' y='{y}' width='{w:.1f}' height='{bar_h}' rx='3' class='bar'/>")
        out.append(f"<text x='{label_w + w + 6:.1f}' y='{y + 15}' class='val'>{escape(value_fmt(v))}</text>")
    out.append("</svg>")
    return "".join(out)


def table(headers, rows, right_from=1):
    th = "".join(f"<th class='{'r' if i >= right_from else ''}'>{escape(h)}</th>" for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(f"<td class='{'r' if i >= right_from else ''}'>{escape(str(c))}</td>"
                         for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def _attr_table(results, level, models, first_col):
    """One row per channel/campaign, with credited amount and opps per model."""
    labels = set()
    for m in models:
        labels |= set(results[m][level])
    anchor = models[0]
    ordered = sorted(labels, key=lambda k: (k == UNATTRIBUTED, -results[anchor][level].get(k, {}).get("total_amount", 0), k))
    headers = [first_col]
    for m in models:
        headers += [f"{MODEL_LABELS.get(m, m)} amount", "opps"]
    rows = []
    for k in ordered:
        row = [k]
        for m in models:
            b = results[m][level].get(k)
            row += [money(b["total_amount"]) if b else "-", f"{b['opps']:.1f}" if b else "-"]
        rows.append(row)
    return table(headers, rows)


CSS = """
:root{--bg:#f7f8fa;--fg:#1a1d23;--muted:#6b7280;--card:#fff;--line:#e5e7eb;--accent:#2f6fed}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e8eaee;--muted:#9aa1ad;--card:#1d2026;--line:#2c313a;--accent:#6c9bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 16px}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 12px}
h3{font-size:14px;margin:0 0 10px}.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:20px}
.card,.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.card .v{font-size:24px;font-weight:650;margin-top:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:12px}
@media (max-width:520px){.grid{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-weight:600;font-size:12px}.r{text-align:right;font-variant-numeric:tabular-nums}
.panel{overflow-x:auto}.bar{fill:var(--accent)}.lbl,.val{font-size:12px;fill:var(--fg)}.val{fill:var(--muted)}
"""


def render_html(res, cfg, title="Pipeline and attribution report"):
    d, cov = res["dashboard"], res["coverage"]
    models = cfg["models"]
    wr = d["win_rate"]
    cards = [
        ("Opportunities", f"{d['total']:,}"), ("Total amount", money(d["total_amount"])),
        ("Win rate (count)", pct(wr["rate_by_count"])), ("Win rate (amount)", pct(wr["rate_by_amount"])),
        ("Median cycle", days(d["cycle"]["median"])),
        ("With campaign touches", pct(cov["pct"])),
    ]
    cards_html = "".join(f"<div class='card'><div class='k'>{k}</div><div class='v'>{v}</div></div>" for k, v in cards)

    def panel(name, inner):
        return f"<div class='panel'><h3>{escape(name)}</h3>{inner}</div>"

    parts = [f"<h1>{escape(title)}</h1>",
             f"<p class='muted'>Pipeline entry date: <code>{escape(cfg['entry_date_field'])}</code>. "
             f"Channel: <code>Campaign.{escape(cfg['channel_field'])}</code>. "
             f"Touch scope: {escape(cfg['touch_scope'])}, window: {cfg['window_days'] or 'unlimited'} days. "
             f"{d['excluded_no_entry_date']} opportunities excluded for a missing entry date.</p>",
             f"<div class='cards'>{cards_html}</div>",
             "<h2>Pipeline</h2><div class='grid'>",
             panel("Created by month (amount)", bar_chart([(m, a) for m, _, a in d["by_month"]], width=640)),
             panel("Created by quarter", table(["Quarter", "Opps", "Amount"], [(q, c, money(a)) for q, c, a in d["by_quarter"]])),
             panel("By stage", table(["Stage", "Opps", "Amount"], [(s, c, money(a)) for s, c, a in d["by_stage"]])),
             panel("By source", bar_chart([(s, a) for s, _, a in d["by_source"]])),
             panel("Win rate by close quarter", table(["Quarter", "Won", "Lost", "Win rate"],
                   [(q, w, l, pct(r)) for q, w, l, r in d["win_rate_by_quarter"]])),
             panel("Cycle time (won, entry to close)", table(["Quarter", "Won opps", "Median days"],
                   [(q, n, f"{m:.0f}") for q, n, m in d["cycle_by_quarter"]])
                   + f"<p class='muted'>Average {days(d['cycle']['average'])}, median {days(d['cycle']['median'])}, n={d['cycle']['count']}.</p>")]
    if d["funnel"]:
        parts.append(panel("Stage funnel (opportunities with a stage date)", bar_chart(d["funnel"], value_fmt=lambda v: f"{v:,.0f}")))
    parts.append("</div>")
    parts += ["<h2>Attribution by channel</h2>",
              f"<p class='muted'>Opportunity amount credited to each channel under each model. "
              f"{cov['with_touches']} of {cov['opps']} opportunities have at least one touch before pipeline entry; "
              f"the rest sit under <code>{escape(UNATTRIBUTED)}</code>, so every column adds up to the full total.</p>",
              f"<div class='panel'>{_attr_table(res['attribution'], 'channel', models, 'Channel')}</div>",
              "<h2>Attribution by campaign</h2>",
              f"<div class='panel'>{_attr_table(res['attribution'], 'campaign', models, 'Campaign')}</div>"]
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'><title>{escape(title)}</title>"
            f"<style>{CSS}</style></head><body><main>{''.join(parts)}</main></body></html>")


def write_csvs(res, cfg, out_dir):
    paths = []
    for level in ("channel", "campaign"):
        path = os.path.join(out_dir, f"attribution_by_{level}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([level, "model", "opps", "open_amount", "won_amount", "lost_amount", "total_amount"])
            for m in cfg["models"]:
                for k, b in sorted(res["attribution"][m][level].items()):
                    w.writerow([k, m, f"{b['opps']:.3f}", f"{b['open_amount']:.2f}",
                                f"{b['won_amount']:.2f}", f"{b['lost_amount']:.2f}", f"{b['total_amount']:.2f}"])
        paths.append(path)
    return paths
