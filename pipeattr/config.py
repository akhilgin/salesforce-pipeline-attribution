"""Configuration: defaults, optionally overridden by a JSON file."""
import json

DEFAULTS = {
    # Opportunity field that marks "entered pipeline". CreatedDate works if every
    # opportunity is created as a real pipeline opportunity; use a custom date
    # field if you stamp one (e.g. "Pipeline_Entry_Date__c").
    "entry_date_field": "CreatedDate",
    # Opportunity field used for the "by source" breakdown.
    "source_field": "LeadSource",
    # Optional {label: Opportunity date field} for a stage funnel on the dashboard.
    "stage_date_fields": {},
    # Campaign field used as the channel. "Type" is the standard picklist; a
    # custom field (e.g. "Channel__c") is usually better if you maintain one.
    "channel_field": "Type",
    # Optional {raw channel value: display label} to merge or rename channels.
    "channel_map": {},
    # Whose campaign memberships count as touches:
    #   contact_roles    - contacts on the opportunity's contact roles
    #   account_contacts - every contact on the opportunity's account
    #   both             - the union
    "touch_scope": "contact_roles",
    # CampaignMember field that dates a touch: CreatedDate or FirstRespondedDate
    # (falls back to CreatedDate when empty).
    "touch_date_field": "CreatedDate",
    # Count only members with HasResponded = true.
    "responded_only": False,
    # Ignore touches older than this many days before pipeline entry (null = no limit).
    "window_days": 365,
    # Count each campaign once per opportunity (earliest touch).
    "collapse_by_campaign": False,
    "u_shaped": {"first": 0.4, "last": 0.4},
    "exclude_campaigns": [],
    # Only include opportunities that entered pipeline on or after this date (YYYY-MM-DD).
    "since": None,
    "api_version": "v60.0",
    "sf_org_alias": None,
    "models": ["first_touch", "last_touch", "linear", "u_shaped"],
}


def load_config(path=None):
    """Return DEFAULTS merged with the JSON file at `path` (if given)."""
    cfg = json.loads(json.dumps(DEFAULTS))
    if path:
        with open(path) as f:
            user = json.load(f)
        for k, v in user.items():
            if k.startswith("_"):
                continue
            if k not in DEFAULTS:
                raise KeyError(f"Unknown config key: {k}")
            cfg[k] = v
    if cfg["touch_scope"] not in ("contact_roles", "account_contacts", "both"):
        raise ValueError("touch_scope must be contact_roles, account_contacts or both")
    if cfg["touch_date_field"] not in ("CreatedDate", "FirstRespondedDate"):
        raise ValueError("touch_date_field must be CreatedDate or FirstRespondedDate")
    u = cfg["u_shaped"]
    if u["first"] < 0 or u["last"] < 0 or u["first"] + u["last"] > 1:
        raise ValueError("u_shaped weights must be >= 0 and sum to at most 1")
    return cfg
