"""Dashboard metrics. Pure functions over normalised opportunities."""
from collections import defaultdict
from statistics import median


def month_label(dt):
    return f"{dt.year}-{dt.month:02d}"


def quarter_label(dt):
    return f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"


def created_by_period(opps, period="month"):
    """Pipeline created per period, keyed on the entry date. Returns sorted [(label, count, amount)]."""
    fn = month_label if period == "month" else quarter_label
    agg = defaultdict(lambda: [0, 0.0])
    for o in opps:
        a = agg[fn(o["entry"])]
        a[0] += 1
        a[1] += o["amount"]
    return [(k, v[0], v[1]) for k, v in sorted(agg.items())]


def group_by(opps, key):
    """Count and amount grouped by an opportunity key ('stage', 'source'), largest amount first."""
    agg = defaultdict(lambda: [0, 0.0])
    for o in opps:
        a = agg[o[key]]
        a[0] += 1
        a[1] += o["amount"]
    return sorted(((k, v[0], v[1]) for k, v in agg.items()), key=lambda r: (-r[2], r[0]))


def win_rate(opps):
    """Win rate over closed opportunities: by count and by amount."""
    won = [o for o in opps if o["stage_cat"] == "won"]
    lost = [o for o in opps if o["stage_cat"] == "lost"]
    won_amt, lost_amt = sum(o["amount"] for o in won), sum(o["amount"] for o in lost)
    n, amt = len(won) + len(lost), won_amt + lost_amt
    return {
        "won": len(won), "lost": len(lost),
        "rate_by_count": len(won) / n if n else None,
        "rate_by_amount": won_amt / amt if amt else None,
    }


def win_rate_by_quarter(opps):
    """Win rate by the quarter of the close date. Returns sorted [(quarter, won, lost, rate)]."""
    agg = defaultdict(lambda: [0, 0])
    for o in opps:
        if o["stage_cat"] in ("won", "lost") and o["close"]:
            agg[quarter_label(o["close"])][0 if o["stage_cat"] == "won" else 1] += 1
    return [(q, w, l, w / (w + l)) for q, (w, l) in sorted(agg.items())]


def cycle_days(o):
    """Days from pipeline entry to close date (never negative)."""
    return max((o["close"].date() - o["entry"].date()).days, 0)


def cycle_time(opps):
    """Entry-to-close days for won opportunities: average, median, count."""
    days = [cycle_days(o) for o in opps if o["stage_cat"] == "won" and o["close"]]
    if not days:
        return {"count": 0, "average": None, "median": None}
    return {"count": len(days), "average": sum(days) / len(days), "median": median(days)}


def cycle_time_by_quarter(opps):
    """Median cycle time of won opportunities by close quarter: [(quarter, count, median_days)]."""
    agg = defaultdict(list)
    for o in opps:
        if o["stage_cat"] == "won" and o["close"]:
            agg[quarter_label(o["close"])].append(cycle_days(o))
    return [(q, len(d), median(d)) for q, d in sorted(agg.items())]


def stage_funnel(opps, labels):
    """How many opportunities have a date stamped for each configured stage label."""
    return [(lbl, sum(1 for o in opps if o["stage_dates"].get(lbl))) for lbl in labels]
