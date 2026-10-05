import unittest
from datetime import datetime

from pipeattr.attribution import (UNATTRIBUTED, attribute_opportunity, collapse_by_campaign,
                                  parse_dt, rollup, weights, window_touches)

ENTRY = datetime(2025, 3, 31, 12, 0, 0)


def touch(cid, channel, ts, contact="c1"):
    return {"campaign_id": cid, "campaign_name": f"camp-{cid}", "channel": channel,
            "ts": parse_dt(ts), "contact_id": contact}


class WeightTests(unittest.TestCase):
    def assertWeights(self, got, want):
        self.assertEqual(len(got), len(want))
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w)
        if want:
            self.assertAlmostEqual(sum(got), 1.0)

    def test_first_touch(self):
        self.assertWeights(weights("first_touch", 3), [1, 0, 0])

    def test_last_touch(self):
        self.assertWeights(weights("last_touch", 3), [0, 0, 1])

    def test_linear(self):
        self.assertWeights(weights("linear", 4), [0.25] * 4)

    def test_u_shaped_three(self):
        self.assertWeights(weights("u_shaped", 3), [0.4, 0.2, 0.4])

    def test_u_shaped_four(self):
        self.assertWeights(weights("u_shaped", 4), [0.4, 0.1, 0.1, 0.4])

    def test_u_shaped_two_and_one(self):
        self.assertWeights(weights("u_shaped", 2), [0.5, 0.5])
        self.assertWeights(weights("u_shaped", 1), [1.0])

    def test_u_shaped_custom(self):
        self.assertWeights(weights("u_shaped", 3, 0.3, 0.5), [0.3, 0.2, 0.5])
        self.assertWeights(weights("u_shaped", 2, 0.3, 0.5), [0.375, 0.625])

    def test_single_touch_gets_everything_in_every_model(self):
        for m in ("first_touch", "last_touch", "linear", "u_shaped"):
            self.assertWeights(weights(m, 1), [1.0])

    def test_empty_and_unknown(self):
        self.assertEqual(weights("linear", 0), [])
        with self.assertRaises(ValueError):
            weights("w_shaped", 3)


class ParseTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse_dt("2025-03-04T10:20:30.000+0000"), datetime(2025, 3, 4, 10, 20, 30))
        self.assertEqual(parse_dt("2025-03-04"), datetime(2025, 3, 4))
        self.assertEqual(parse_dt("2025-03-04", end_of_day=True), datetime(2025, 3, 4, 23, 59, 59))
        self.assertIsNone(parse_dt(None))


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.touches = [
            touch("old", "Email", "2024-01-01T00:00:00"),    # ~455 days before
            touch("mid", "Webinar", "2024-12-31T09:00:00"),  # 90 days before
            touch("same", "Ads", "2025-03-31T11:00:00"),     # same day, before entry
            touch("late", "Email", "2025-03-31T13:00:00"),   # after entry
            touch("next", "Email", "2025-04-02T00:00:00"),   # after entry
        ]

    def ids(self, got):
        return [t["campaign_id"] for t in got]

    def test_excludes_touches_after_entry(self):
        got = window_touches(self.touches, ENTRY)
        self.assertEqual(self.ids(got), ["old", "mid", "same"])

    def test_window_days_lower_bound(self):
        got = window_touches(self.touches, ENTRY, window_days=365)
        self.assertEqual(self.ids(got), ["mid", "same"])
        got = window_touches(self.touches, ENTRY, window_days=30)
        self.assertEqual(self.ids(got), ["same"])

    def test_boundary_is_inclusive(self):
        t = [touch("edge", "Email", "2025-03-31T12:00:00")]
        self.assertEqual(len(window_touches(t, ENTRY, 10)), 1)

    def test_sorted_oldest_first_with_stable_ties(self):
        a = touch("b", "Email", "2025-01-01T00:00:00")
        b = touch("a", "Email", "2025-01-01T00:00:00")
        c = touch("z", "Email", "2024-12-01T00:00:00")
        self.assertEqual(self.ids(window_touches([a, b, c], ENTRY)), ["z", "a", "b"])

    def test_missing_timestamp_is_dropped(self):
        t = touch("x", "Email", None)
        self.assertEqual(window_touches([t], ENTRY), [])

    def test_collapse_keeps_earliest_per_campaign(self):
        ts = [touch("a", "Email", "2025-01-01T00:00:00", "c1"),
              touch("a", "Email", "2025-02-01T00:00:00", "c2"),
              touch("b", "Ads", "2025-02-02T00:00:00")]
        got = collapse_by_campaign(window_touches(ts, ENTRY))
        self.assertEqual([(t["campaign_id"], t["contact_id"]) for t in got], [("a", "c1"), ("b", "c1")])


class RollupTests(unittest.TestCase):
    def setUp(self):
        self.touches = [touch("1", "Email", "2025-01-01T00:00:00"),
                        touch("2", "Ads", "2025-02-01T00:00:00"),
                        touch("3", "Email", "2025-03-01T00:00:00"),
                        touch("4", "Webinar", "2025-03-20T00:00:00")]
        self.opp = {"id": "o1", "amount": 1000.0, "stage_cat": "won", "entry": ENTRY}

    def channel_rollup(self, model):
        credits = attribute_opportunity(self.touches, ENTRY, model)
        return rollup([(self.opp, credits)], lambda t: t["channel"])

    def test_linear_by_channel(self):
        r = self.channel_rollup("linear")
        self.assertAlmostEqual(r["Email"]["won_amount"], 500.0)
        self.assertAlmostEqual(r["Ads"]["won_amount"], 250.0)
        self.assertAlmostEqual(r["Webinar"]["won_amount"], 250.0)
        self.assertAlmostEqual(r["Email"]["opps"], 0.5)

    def test_u_shaped_by_channel(self):
        r = self.channel_rollup("u_shaped")
        self.assertAlmostEqual(r["Email"]["total_amount"], 500.0)   # 0.4 + 0.1
        self.assertAlmostEqual(r["Ads"]["total_amount"], 100.0)
        self.assertAlmostEqual(r["Webinar"]["total_amount"], 400.0)

    def test_first_and_last_touch(self):
        self.assertEqual(list(self.channel_rollup("first_touch")), ["Email"])
        self.assertEqual(list(self.channel_rollup("last_touch")), ["Webinar"])

    def test_by_campaign(self):
        credits = attribute_opportunity(self.touches, ENTRY, "linear")
        r = rollup([(self.opp, credits)], lambda t: t["campaign_name"])
        self.assertEqual(sorted(r), ["camp-1", "camp-2", "camp-3", "camp-4"])
        self.assertAlmostEqual(r["camp-3"]["total_amount"], 250.0)

    def test_untouched_opportunity_is_unattributed_and_totals_reconcile(self):
        lost = {"id": "o2", "amount": 500.0, "stage_cat": "lost", "entry": ENTRY}
        openo = {"id": "o3", "amount": 200.0, "stage_cat": "open", "entry": ENTRY}
        attributed = [(self.opp, attribute_opportunity(self.touches, ENTRY, "u_shaped")),
                      (lost, []),
                      (openo, attribute_opportunity(self.touches[:1], ENTRY, "linear"))]
        r = rollup(attributed, lambda t: t["channel"])
        self.assertAlmostEqual(r[UNATTRIBUTED]["lost_amount"], 500.0)
        self.assertAlmostEqual(r["Email"]["open_amount"], 200.0)
        self.assertAlmostEqual(sum(b["total_amount"] for b in r.values()), 1700.0)
        self.assertAlmostEqual(sum(b["opps"] for b in r.values()), 3.0)

    def test_touch_after_entry_gets_no_credit(self):
        late = touch("9", "Ads", "2025-04-15T00:00:00")
        credits = attribute_opportunity(self.touches + [late], ENTRY, "last_touch")
        self.assertEqual(credits[0][0]["channel"], "Webinar")


if __name__ == "__main__":
    unittest.main()
