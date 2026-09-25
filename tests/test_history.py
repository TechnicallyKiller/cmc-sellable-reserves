import unittest

from sellable import history


class HistoryRows(unittest.TestCase):
    def test_disabled_without_env(self):
        h = history.History(url="", key="")
        self.assertFalse(h.enabled)
        self.assertIsNone(h.series("lbank"))
        h.record({"quotes_fetched_at": "20260925T031451Z", "exchanges": []})  # no-op, no error

    def test_rows_from_view_skip_exchanges_without_data(self):
        view = {"quotes_fetched_at": "20260925T031451Z", "exchanges": [
            {"id": 333, "slug": "lbank", "name": "LBank", "has_data": True, "reported_usd": 5.5e8,
             "sellable_share": {1: 0.03, 7: 0.04, 30: 0.05}, "no_market_share": 0.0},
            {"id": 24, "slug": "kraken", "name": "Kraken", "has_data": False},
        ]}
        rows = history.History.rows_from_view(view)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fetched_at"], "2026-09-25T03:14:51+00:00")
        self.assertEqual((rows[0]["sellable_7d"], rows[0]["slug"]), (0.04, "lbank"))


if __name__ == "__main__":
    unittest.main()
