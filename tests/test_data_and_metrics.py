import os
import unittest
from datetime import datetime

from pipeattr import metrics
from pipeattr.analyze import analyze
from pipeattr.attribution import attribute_opportunity
from pipeattr.config import load_config
from pipeattr.data import (build_touches_by_opp, load_offline, normalise_opportunities,
                           normalise_touch)
from pipeattr.report import render_html

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample_data")


def member(mid, contact, account, campaign, ctype, created, responded=False):
    return {"Id": mid, "ContactId": contact, "Contact": {"AccountId": account},
            "CampaignId": campaign, "Campaign": {"Name": f"name-{campaign}", "Type": ctype},
            "CreatedDate": created, "FirstRespondedDate": created if responded else None,
            "HasResponded": responded}


OPP = {"Id": "o1", "Name": "Deal", "AccountId": "a1", "Account": {"Name": "Acme"}, "Amount": 100,
       "StageName": "Closed Won", "IsClosed": True, "IsWon": True,
       "CreatedDate": "2025-03-31T12:00:00.000+0000", "CloseDate": "2025-05-10", "LeadSource": "Web"}


class ConfigTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        cfg = load_config()
        self.assertEqual(cfg["entry_date_field"], "CreatedDate")
        self.assertEqual(cfg["channel_field"], "Type")

    def test_example_config_loads(self):
        load_config(os.path.join(os.path.dirname(__file__), "..", "config.example.json"))


class TouchBuildingTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()
        self.opps, _ = normalise_opportunities([OPP], self.cfg)
        self.roles = [{"OpportunityId": "o1", "ContactId": "c1"}]
        self.members = [
            member("m1", "c1", "a1", "k1", "Webinar", "2025-01-10T00:00:00.000+0000", True),
            member("m2", "c2", "a1", "k2", "Email", "2025-02-10T00:00:00.000+0000"),   # account-only contact
            member("m3", "c9", "a9", "k3", "Email", "2025-02-10T00:00:00.000+0000"),   # unrelated
        ]

    def campaigns(self, cfg):
        t = build_touches_by_opp(self.opps, self.roles, self.members, cfg)["o1"]
        return sorted(x["campaign_id"] for x in t)

    def test_scope_contact_roles(self):
        self.assertEqual(self.campaigns(self.cfg), ["k1"])

    def test_scope_account_contacts(self):
        self.cfg["touch_scope"] = "account_contacts"
        self.assertEqual(self.campaigns(self.cfg), ["k1", "k2"])

    def test_scope_both_does_not_double_count(self):
        self.cfg["touch_scope"] = "both"
        self.assertEqual(self.campaigns(self.cfg), ["k1", "k2"])

    def test_responded_only(self):
        self.cfg["touch_scope"] = "account_contacts"
        self.cfg["responded_only"] = True
        self.assertEqual(self.campaigns(self.cfg), ["k1"])

    def test_channel_map_and_exclusions(self):
        self.cfg["channel_map"] = {"Webinar": "Events"}
        t = normalise_touch(self.members[0], self.cfg)
        self.assertEqual(t["channel"], "Events")
        self.cfg["exclude_campaigns"] = ["name-k1"]
        self.assertIsNone(normalise_touch(self.members[0], self.cfg))

    def test_date_only_entry_includes_touch_on_same_day(self):
        cfg = load_config()
        cfg["entry_date_field"] = "Entered__c"
        opp = dict(OPP, Entered__c="2025-03-31")
        opps, _ = normalise_opportunities([opp], cfg)
        same_day = member("m4", "c1", "a1", "k4", "Email", "2025-03-31T18:00:00.000+0000")
        t = normalise_touch(same_day, cfg)
        credits = attribute_opportunity([t], opps[0]["entry"], "linear")
        self.assertEqual(len(credits), 1)

    def test_missing_entry_date_excluded(self):
        cfg = load_config()
        cfg["entry_date_field"] = "Entered__c"
        opps, excluded = normalise_opportunities([dict(OPP, Entered__c=None)], cfg)
        self.assertEqual((opps, excluded), ([], 1))


def mk(stage_cat, entry, close, amount, stage="x", source="s"):
    return {"stage_cat": stage_cat, "entry": datetime.fromisoformat(entry),
            "close": datetime.fromisoformat(close) if close else None,
            "amount": amount, "stage": stage, "source": source, "stage_dates": {}}


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.opps = [
            mk("won", "2025-01-05", "2025-02-04", 100),    # 30 days
            mk("won", "2025-01-20", "2025-04-10", 300),    # 80 days
            mk("lost", "2025-02-01", "2025-03-01", 200),
            mk("open", "2025-04-02", "2025-06-01", 50),
        ]

    def test_labels_and_created(self):
        self.assertEqual(metrics.quarter_label(datetime(2025, 4, 1)), "2025-Q2")
        self.assertEqual(metrics.created_by_period(self.opps, "month"),
                         [("2025-01", 2, 400.0), ("2025-02", 1, 200.0), ("2025-04", 1, 50.0)])
        self.assertEqual(metrics.created_by_period(self.opps, "quarter"),
                         [("2025-Q1", 3, 600.0), ("2025-Q2", 1, 50.0)])

    def test_win_rate(self):
        w = metrics.win_rate(self.opps)
        self.assertEqual((w["won"], w["lost"]), (2, 1))
        self.assertAlmostEqual(w["rate_by_count"], 2 / 3)
        self.assertAlmostEqual(w["rate_by_amount"], 400 / 600)

    def test_win_rate_by_close_quarter(self):
        self.assertEqual(metrics.win_rate_by_quarter(self.opps),
                         [("2025-Q1", 1, 1, 0.5), ("2025-Q2", 1, 0, 1.0)])

    def test_cycle_time(self):
        c = metrics.cycle_time(self.opps)
        self.assertEqual(c["count"], 2)
        self.assertAlmostEqual(c["average"], 55.0)
        self.assertAlmostEqual(c["median"], 55.0)
        self.assertEqual(metrics.cycle_time_by_quarter(self.opps), [("2025-Q1", 1, 30), ("2025-Q2", 1, 80)])

    def test_empty(self):
        self.assertIsNone(metrics.win_rate([])["rate_by_count"])
        self.assertIsNone(metrics.cycle_time([])["median"])


class OfflineSampleTests(unittest.TestCase):
    def test_sample_runs_and_reconciles(self):
        cfg = load_config(os.path.join(SAMPLE, "sample_config.json"))
        res = analyze(load_offline(SAMPLE), cfg)
        total = res["dashboard"]["total_amount"]
        for model in cfg["models"]:
            for level in ("channel", "campaign"):
                got = sum(b["total_amount"] for b in res["attribution"][model][level].values())
                self.assertAlmostEqual(got, total, places=4)
        html = render_html(res, cfg)
        self.assertIn("<svg", html)
        self.assertNotIn("<script", html)


if __name__ == "__main__":
    unittest.main()
