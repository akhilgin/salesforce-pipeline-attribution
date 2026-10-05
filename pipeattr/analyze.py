"""Glue: raw records -> metrics and attribution results."""
from . import metrics
from .attribution import attribute_opportunity, rollup
from .data import build_touches_by_opp, normalise_opportunities


def analyze(raw, cfg):
    opps, excluded = normalise_opportunities(raw["opportunities"], cfg)
    touches = build_touches_by_opp(opps, raw["contact_roles"], raw["campaign_members"], cfg)
    u = cfg["u_shaped"]

    results, coverage = {}, None
    for model in cfg["models"]:
        attributed = [
            (o, attribute_opportunity(touches[o["id"]], o["entry"], model,
                                      window_days=cfg["window_days"],
                                      collapse=cfg["collapse_by_campaign"],
                                      u_first=u["first"], u_last=u["last"]))
            for o in opps
        ]
        results[model] = {
            "channel": rollup(attributed, lambda t: t["channel"]),
            "campaign": rollup(attributed, lambda t: t["campaign_name"]),
        }
        if coverage is None:
            touched = sum(1 for _, c in attributed if c)
            coverage = {"opps": len(opps), "with_touches": touched,
                        "pct": touched / len(opps) if opps else 0.0}

    closed = [o for o in opps if o["stage_cat"] != "open"]
    dash = {
        "total": len(opps),
        "excluded_no_entry_date": excluded,
        "total_amount": sum(o["amount"] for o in opps),
        "by_month": metrics.created_by_period(opps, "month"),
        "by_quarter": metrics.created_by_period(opps, "quarter"),
        "by_stage": metrics.group_by(opps, "stage"),
        "by_source": metrics.group_by(opps, "source"),
        "win_rate": metrics.win_rate(closed),
        "win_rate_by_quarter": metrics.win_rate_by_quarter(opps),
        "cycle": metrics.cycle_time(opps),
        "cycle_by_quarter": metrics.cycle_time_by_quarter(opps),
        "funnel": metrics.stage_funnel(opps, list(cfg["stage_date_fields"])),
    }
    return {"dashboard": dash, "attribution": results, "coverage": coverage}
