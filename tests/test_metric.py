"""Tests against real CMC responses captured 2026-09-24/25.

fixtures/assets_*.json            unmodified /v1/exchange/assets responses
fixtures/quotes_v3_subset_*.json  the records for the fixtures' tokens, taken
                                  unmodified from two /v3/cryptocurrency/quotes/latest responses
"""
import json
import os
import unittest

from sellable import cmc, metric

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


QUOTES = cmc.parse_quotes([load("quotes_v3_subset_2026-09-25.json")])


def rows(name):
    return load(f"assets_{name}_2026-09-24.json")["data"]


class Cleaning(unittest.TestCase):
    def test_evm_addresses_lowercased_other_formats_untouched(self):
        self.assertEqual(metric.normalise_address("0xF977814e90dA44bFA03b6295A0616a897441aceC"),
                         "0xf977814e90da44bfa03b6295a0616a897441acec")
        btc = "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo"
        self.assertEqual(metric.normalise_address(btc), btc)

    def test_case_variant_identical_rows_collapse(self):
        raw = rows("ourbit")
        kept, collapsed = metric.clean_rows(raw)
        self.assertEqual(len(raw), 31)
        self.assertEqual(collapsed, 7)
        keys = [(metric.normalise_address(r["wallet_address"]), r["platform"]["crypto_id"],
                 r["currency"]["crypto_id"], r["balance"]) for r in kept]
        self.assertEqual(len(keys), len(set(keys)))

    def test_same_key_different_balance_is_kept(self):
        a = rows("ourbit")[0]
        b = json.loads(json.dumps(a))
        b["balance"] = a["balance"] + 1
        kept, collapsed = metric.clean_rows([a, b])
        self.assertEqual((len(kept), collapsed), (2, 0))

    def test_wallet_claimed_by_two_exchanges(self):
        shared = metric.shared_wallets({"bvox": rows("bvox"), "deepcoin": rows("deepcoin")})
        self.assertEqual(shared, {"0xb8001c3ec9aa1985f6c747e25c28324e4a361ec1": ["bvox", "deepcoin"]})


class Metric(unittest.TestCase):
    def test_zero_volume_goes_to_no_market_not_sellable(self):
        res = metric.compute_exchange(metric.clean_rows(rows("blockfinex"))[0], QUOTES)
        usdz = next(h for h in res["holdings"] if h["symbol"] == "USDZ")
        self.assertEqual(usdz["volume_24h"], 0)
        self.assertIsNone(usdz["days_to_sell"])
        zero_vol = [h for h in res["holdings"] if h["volume_24h"] == 0]
        self.assertEqual(sorted(h["symbol"] for h in zero_vol), ["EMRL.D", "USDZ"])
        self.assertAlmostEqual(res["no_market_usd"], sum(h["usd"] for h in zero_vol))
        for n in metric.HORIZONS:
            self.assertLessEqual(res["sellable_usd"][n], res["reported_usd"] - res["no_market_usd"] + 1e-6)

    def test_zero_circulating_supply_gives_no_supply_share(self):
        res = metric.compute_exchange(metric.clean_rows(rows("blockfinex"))[0], QUOTES)
        usdz = next(h for h in res["holdings"] if h["symbol"] == "USDZ")
        self.assertEqual(QUOTES[usdz["token_id"]]["circulating_supply"], 0)
        self.assertIsNone(usdz["supply_share"])

    def test_sellable_is_capped_by_n_days_of_volume(self):
        res = metric.compute_exchange(metric.clean_rows(rows("ourbit"))[0], QUOTES)
        for n in metric.HORIZONS:
            expected = sum(min(h["usd"], n * h["volume_24h"]) for h in res["holdings"] if h["volume_24h"] > 0)
            self.assertAlmostEqual(res["sellable_usd"][n], expected)
        self.assertLessEqual(res["sellable_usd"][1], res["sellable_usd"][7])
        self.assertLessEqual(res["sellable_usd"][7], res["sellable_usd"][30])

    def test_token_missing_from_quotes_is_unpriced_not_zero(self):
        r = rows("ourbit")
        missing_id = r[0]["currency"]["crypto_id"]
        quotes = {k: v for k, v in QUOTES.items() if k != missing_id}
        res = metric.compute_exchange(metric.clean_rows(r)[0], quotes)
        self.assertIn(missing_id, [u["token_id"] for u in res["unpriced"]])
        self.assertNotIn(missing_id, [h["token_id"] for h in res["holdings"]])


class Sentences(unittest.TestCase):
    def test_no_market_sentence(self):
        res = metric.compute_exchange(metric.clean_rows(rows("blockfinex"))[0], QUOTES)
        s = metric.sentence("Blockfinex", res)
        self.assertIn("USDZ, which had no trading at all in the last 24 hours", s)
        self.assertNotIn("About 0%", s)

    def test_no_reserves_sentence(self):
        self.assertEqual(metric.sentence("X", {"reported_usd": 0}),
                         "X does not publish any reserves that CoinMarketCap tracks.")

    def test_duration(self):
        self.assertEqual(metric.duration(1.25), "1.2 days")
        self.assertEqual(metric.duration(18.4), "18 days")
        self.assertEqual(metric.duration(21645), "about 59 years")


if __name__ == "__main__":
    unittest.main()


class Milestones(unittest.TestCase):
    def _liquid(self, name):
        res = metric.compute_exchange(metric.clean_rows(rows(name))[0], QUOTES)
        return res, [h for h in res["holdings"] if h["volume_24h"] > 0]

    def test_days_to_reach_matches_brute_force(self):
        res, liquid = self._liquid("ourbit")
        for f in (0.1, 0.5, 0.9, 0.99):
            target = f * res["reported_usd"]
            d = metric.days_to_reach(liquid, target)
            self.assertIsNotNone(d)
            # exact: sellable at d hits the target, and a hair earlier it doesn't
            self.assertAlmostEqual(metric.sellable_at(liquid, d), target, delta=target * 1e-9)
            self.assertLess(metric.sellable_at(liquid, d * (1 - 1e-6)), target)

    def test_unreachable_when_no_market_blocks_it(self):
        res, liquid = self._liquid("blockfinex")
        self.assertLess(res["ceiling_share"], 0.5)
        self.assertIsNone(res["days_to_share"]["50"])
        self.assertIsNone(res["days_to_share"]["90"])

    def test_curve_is_monotone_and_capped_by_ceiling(self):
        res, _ = self._liquid("ourbit")
        shares = [s for _, s in res["curve"]]
        self.assertEqual(shares, sorted(shares))
        self.assertLessEqual(shares[-1], res["ceiling_share"] + 1e-12)
        self.assertEqual(res["curve"][0][0], 1)
        self.assertEqual(res["curve"][-1][0], 365)


class Anatomy(unittest.TestCase):
    def test_buckets_partition_reserves(self):
        for name in ("ourbit", "blockfinex"):
            res = metric.compute_exchange(metric.clean_rows(rows(name))[0], QUOTES)
            self.assertAlmostEqual(sum(b["usd"] for b in res["buckets"]), res["reported_usd"], places=2)
            self.assertAlmostEqual(res["buckets"][metric.NO_MARKET_BUCKET]["usd"], res["no_market_usd"], places=2)

    def test_bucket_edges(self):
        self.assertEqual([metric.bucket_of(d) for d in (0.5, 1, 6.9, 7, 29, 364, 365, 5000, None)],
                         [0, 1, 1, 2, 2, 3, 4, 4, metric.NO_MARKET_BUCKET])

    def test_chains_sum_to_reported(self):
        res = metric.compute_exchange(metric.clean_rows(rows("ourbit"))[0], QUOTES)
        self.assertAlmostEqual(sum(c["usd"] for c in res["chains"]), res["reported_usd"], places=2)

    def test_concentration(self):
        res = metric.compute_exchange(metric.clean_rows(rows("blockfinex"))[0], QUOTES)
        c = res["concentration"]
        self.assertGreater(c["top1_share"], 0.95)
        self.assertLess(c["effective_tokens"], 1.1)  # effectively one token
        self.assertLessEqual(c["top1_share"], c["top5_share"])
