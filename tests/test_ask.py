"""Ask panel fallbacks: every failure path must return None so the frontend
uses its rule-based answers."""
import unittest

from sellable import ask


class AskFallback(unittest.TestCase):
    def test_no_key_falls_back(self):
        self.assertEqual(ask.Asker(key="").ask({}, "what is UMM?", None, "1.1.1.1"), (None, "no_llm"))

    def test_empty_question_falls_back(self):
        self.assertEqual(ask.Asker(key="k").ask({}, "   ", None, "1.1.1.1"), (None, "empty"))

    def test_per_ip_limit(self):
        rl = ask.RateLimiter()
        results = [rl.allow("1.1.1.1") for _ in range(ask.IP_PER_MIN + 1)]
        self.assertEqual(results, [True] * ask.IP_PER_MIN + [False])
        self.assertTrue(rl.allow("2.2.2.2"))

    def test_global_limit(self):
        rl = ask.RateLimiter()
        allowed = sum(rl.allow(f"10.0.0.{i}") for i in range(ask.GLOBAL_PER_MIN + 5))
        self.assertEqual(allowed, ask.GLOBAL_PER_MIN)


if __name__ == "__main__":
    unittest.main()
