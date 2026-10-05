"""Attribution math. Pure functions only: no I/O, no Salesforce, no clock.

Vocabulary
- touch:  a dict with keys campaign_id, campaign_name, channel, ts (datetime), contact_id
- opp:    a dict with keys id, amount, stage_cat ("open" | "won" | "lost"), entry (datetime)
- credit: a (touch, weight) pair; the weights for one opportunity sum to 1.0
"""
import re
from datetime import datetime, timedelta

MODELS = ("first_touch", "last_touch", "linear", "u_shaped")
UNATTRIBUTED = "(no touches)"

_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}):(\d{2}))?")


def parse_dt(value, end_of_day=False):
    """Parse a Salesforce date or datetime string into a naive UTC datetime.

    Date-only strings ("2025-03-04") become midnight, or 23:59:59 when
    end_of_day=True. Fractional seconds and UTC offsets are ignored
    (Salesforce returns UTC). Returns None for empty input.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    m = _DT_RE.match(str(value).strip())
    if not m:
        raise ValueError(f"Unrecognised date: {value!r}")
    y, mo, d, h, mi, s = m.groups()
    if h is None:
        h, mi, s = ("23", "59", "59") if end_of_day else ("0", "0", "0")
    return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))


def weights(model, n, u_first=0.4, u_last=0.4):
    """Return n weights (ordered oldest touch first) that sum to 1.0.

    first_touch: all credit to the oldest touch.
    last_touch:  all credit to the newest touch.
    linear:      1/n each.
    u_shaped:    u_first to the first, u_last to the last, the remainder split
                 evenly across the middle touches. With 2 touches the middle
                 share is empty, so the weights are renormalised to 50/50
                 (proportional to u_first:u_last). With 1 touch it gets 1.0.
    """
    if n <= 0:
        return []
    if model == "first_touch":
        return [1.0] + [0.0] * (n - 1)
    if model == "last_touch":
        return [0.0] * (n - 1) + [1.0]
    if model == "linear":
        return [1.0 / n] * n
    if model == "u_shaped":
        if n == 1:
            return [1.0]
        if n == 2:
            total = u_first + u_last
            return [u_first / total, u_last / total]
        middle = (1.0 - u_first - u_last) / (n - 2)
        return [u_first] + [middle] * (n - 2) + [u_last]
    raise ValueError(f"Unknown model: {model!r} (choose from {MODELS})")


def window_touches(touches, entry, window_days=None):
    """Keep touches that happened at or before `entry` and within `window_days`.

    window_days=None (or 0) means no lower bound. Result is sorted oldest first;
    ties are broken by campaign_id then contact_id so output is deterministic.
    """
    lower = entry - timedelta(days=window_days) if window_days else None
    kept = [
        t for t in touches
        if t["ts"] is not None and t["ts"] <= entry and (lower is None or t["ts"] >= lower)
    ]
    kept.sort(key=lambda t: (t["ts"], str(t.get("campaign_id")), str(t.get("contact_id"))))
    return kept


def collapse_by_campaign(touches):
    """Keep only the earliest touch per campaign (input must be sorted oldest first)."""
    seen, out = set(), []
    for t in touches:
        if t["campaign_id"] not in seen:
            seen.add(t["campaign_id"])
            out.append(t)
    return out


def attribute_opportunity(touches, entry, model, window_days=None,
                          collapse=False, u_first=0.4, u_last=0.4):
    """Return [(touch, weight), ...] for one opportunity (zero-weight touches omitted).

    Empty if nothing qualifies."""
    kept = window_touches(touches, entry, window_days)
    if collapse:
        kept = collapse_by_campaign(kept)
    pairs = zip(kept, weights(model, len(kept), u_first, u_last))
    return [(t, w) for t, w in pairs if w > 0]


def _empty_bucket(label):
    return {"label": label, "opps": 0.0, "open_amount": 0.0, "won_amount": 0.0,
            "lost_amount": 0.0, "total_amount": 0.0}


def rollup(attributed, keyfn):
    """Aggregate credit by a key.

    attributed: list of (opp, [(touch, weight), ...])
    keyfn:      touch -> label (campaign name, channel, ...)

    An opportunity with no qualifying touch is credited 100% to UNATTRIBUTED, so
    totals always reconcile to the full set of opportunities. Opportunities are
    counted fractionally (a weight of 0.4 is 0.4 of an opportunity).
    Returns {label: bucket}.
    """
    out = {}
    for opp, credits in attributed:
        amount = opp.get("amount") or 0.0
        pairs = [(keyfn(t), w) for t, w in credits] or [(UNATTRIBUTED, 1.0)]
        for label, w in pairs:
            b = out.setdefault(label, _empty_bucket(label))
            b["opps"] += w
            b["total_amount"] += amount * w
            b[f"{opp['stage_cat']}_amount"] += amount * w
    return out
