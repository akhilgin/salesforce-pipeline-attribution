"""Load raw records (Salesforce or offline JSON) and normalise them for the math."""
import json
import os
from collections import defaultdict

from .attribution import parse_dt


def dig(record, path):
    """Follow a dotted path through nested dicts: dig(m, 'Campaign.Type')."""
    cur = record
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


# --- loading ------------------------------------------------------------------

RAW_FILES = {
    "opportunities": "opportunities.json",
    "contact_roles": "contact_roles.json",
    "campaign_members": "campaign_members.json",
}


def load_offline(directory):
    raw = {}
    for key, name in RAW_FILES.items():
        with open(os.path.join(directory, name)) as f:
            raw[key] = json.load(f)
    return raw


def _since_literal(since, field_type):
    if field_type == "datetime":
        return f"{since}T00:00:00Z"
    return since


def load_salesforce(client, cfg):
    """Pull the four record sets with read-only SOQL. See README for the exact queries."""
    entry = cfg["entry_date_field"]
    since = cfg["since"]
    if since:
        lit = _since_literal(since, client.field_type("Opportunity", entry))
        opp_filter = f"{entry} >= {lit}"
        rel_filter = f"Opportunity.{entry} >= {lit}"
    else:
        opp_filter = f"{entry} != null"
        rel_filter = f"Opportunity.{entry} != null"

    extra = [v for v in cfg["stage_date_fields"].values()]
    opp_fields = ["Id", "Name", "AccountId", "Account.Name", "Amount", "StageName",
                  "IsClosed", "IsWon", "CreatedDate", "CloseDate", entry, cfg["source_field"]] + extra
    opp_fields = list(dict.fromkeys(opp_fields))
    opps = client.query(f"SELECT {', '.join(opp_fields)} FROM Opportunity WHERE {opp_filter}")

    roles = client.query(
        f"SELECT OpportunityId, ContactId FROM OpportunityContactRole "
        f"WHERE ContactId != null AND {rel_filter}")

    chan = f"Campaign.{cfg['channel_field']}"
    cm_fields = list(dict.fromkeys(
        ["Id", "ContactId", "Contact.AccountId", "CampaignId", "Campaign.Name", chan,
         "CreatedDate", "FirstRespondedDate", "HasResponded"]))
    base = f"SELECT {', '.join(cm_fields)} FROM CampaignMember WHERE ContactId != null AND "
    members = {}
    if cfg["touch_scope"] in ("contact_roles", "both"):
        q = (base + "ContactId IN (SELECT ContactId FROM OpportunityContactRole "
             f"WHERE ContactId != null AND {rel_filter})")
        for m in client.query(q):
            members[m["Id"]] = m
    if cfg["touch_scope"] in ("account_contacts", "both"):
        q = (base + f"Contact.AccountId IN (SELECT AccountId FROM Opportunity WHERE {opp_filter})")
        for m in client.query(q):
            members[m["Id"]] = m
    return {"opportunities": opps, "contact_roles": roles, "campaign_members": list(members.values())}


# --- normalising --------------------------------------------------------------

def stage_category(opp):
    if opp.get("IsWon"):
        return "won"
    if opp.get("IsClosed"):
        return "lost"
    return "open"


def _parse_entry(value):
    return parse_dt(value, end_of_day=bool(value) and len(str(value)) == 10)


def normalise_opportunities(rows, cfg):
    """Return (opps, excluded_count). Opportunities without an entry date are excluded."""
    opps, excluded = [], 0
    for r in rows:
        entry = _parse_entry(r.get(cfg["entry_date_field"]))
        if entry is None:
            excluded += 1
            continue
        opps.append({
            "id": r["Id"],
            "name": r.get("Name") or "",
            "account_id": r.get("AccountId"),
            "account": dig(r, "Account.Name") or "",
            "amount": float(r.get("Amount") or 0),
            "stage": r.get("StageName") or "",
            "stage_cat": stage_category(r),
            "entry": entry,
            "close": parse_dt(r.get("CloseDate")),
            "source": r.get(cfg["source_field"]) or "(none)",
            "stage_dates": {label: parse_dt(r.get(field))
                            for label, field in cfg["stage_date_fields"].items()},
        })
    return opps, excluded


def normalise_touch(member, cfg):
    """Turn a CampaignMember record into a touch dict, or None if it should be ignored."""
    name = dig(member, "Campaign.Name") or ""
    if name in cfg["exclude_campaigns"]:
        return None
    if cfg["responded_only"] and not member.get("HasResponded"):
        return None
    ts = parse_dt(member.get(cfg["touch_date_field"]) or member.get("CreatedDate"))
    raw_channel = dig(member, f"Campaign.{cfg['channel_field']}") or "(none)"
    return {
        "campaign_id": member.get("CampaignId"),
        "campaign_name": name,
        "channel": cfg["channel_map"].get(raw_channel, raw_channel),
        "ts": ts,
        "contact_id": member.get("ContactId"),
    }


def build_touches_by_opp(opps, roles, members, cfg):
    """Map opportunity id -> list of candidate touches (before date windowing)."""
    by_contact, by_account = defaultdict(list), defaultdict(list)
    for m in members:
        t = normalise_touch(m, cfg)
        if t is None:
            continue
        by_contact[m.get("ContactId")].append(t)
        acct = dig(m, "Contact.AccountId")
        if acct:
            by_account[acct].append(t)
    role_contacts = defaultdict(set)
    for r in roles:
        role_contacts[r["OpportunityId"]].add(r["ContactId"])

    scope = cfg["touch_scope"]
    out = {}
    for o in opps:
        picked = {}
        if scope in ("contact_roles", "both"):
            for c in role_contacts.get(o["id"], ()):
                for t in by_contact.get(c, ()):
                    picked[(t["contact_id"], t["campaign_id"], t["ts"])] = t
        if scope in ("account_contacts", "both") and o["account_id"]:
            for t in by_account.get(o["account_id"], ()):
                picked[(t["contact_id"], t["campaign_id"], t["ts"])] = t
        out[o["id"]] = list(picked.values())
    return out
