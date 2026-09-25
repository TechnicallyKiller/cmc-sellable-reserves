"""MCP server: both protocol eras, header validation, error codes, and each tool,
run against a view built from real captured CMC responses."""
import gzip
import json
import os
import shutil
import tempfile
import unittest

from sellable import mcp
from sellable.live import Live
from sellable.store import Store

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, "fixtures")
EVIDENCE_MAP = os.path.join(HERE, "..", "evidence", "exchange", "map_top100_volume_2026-09-24.json")
NAMES = ("ourbit", "blockfinex", "bvox", "deepcoin")
ORIGIN = "https://sr.example"


def build_view():
    """Store layout the live server writes, filled with the fixture responses."""
    root = tempfile.mkdtemp()
    with open(EVIDENCE_MAP) as f:
        full = json.load(f)
    rows = [e for e in full["data"] if e["slug"] in NAMES]
    ex_dir, q_dir = os.path.join(root, "exchanges", "20260924T000000Z"), os.path.join(root, "quotes", "20260925T000000Z")
    os.makedirs(ex_dir), os.makedirs(q_dir)

    def put(path, obj):
        with gzip.open(path, "wt") as f:
            json.dump(obj, f)
    put(os.path.join(ex_dir, "map.json.gz"), {"status": full["status"], "data": rows})
    for e in rows:
        with open(os.path.join(FIX, f"assets_{e['slug']}_2026-09-24.json")) as f:
            put(os.path.join(ex_dir, f"assets_{e['id']}.json.gz"), json.load(f))
    with open(os.path.join(FIX, "quotes_v3_subset_2026-09-25.json")) as f:
        put(os.path.join(q_dir, "quotes_0.json.gz"), json.load(f))
    live = Live(Store(root))
    live.load_latest_from_store()
    view = live.build_view()
    shutil.rmtree(root)
    return view


VIEW = build_view()


def modern(method, params=None, headers=None, id_=1):
    params = dict(params or {})
    params["_meta"] = {"io.modelcontextprotocol/protocolVersion": mcp.MODERN,
                       "io.modelcontextprotocol/clientCapabilities": {},
                       "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "0"}}
    h = {"mcp-protocol-version": mcp.MODERN, "mcp-method": method}
    if method == "tools/call":
        h["mcp-name"] = params["name"]
    h.update(headers or {})
    return h, json.dumps({"jsonrpc": "2.0", "id": id_, "method": method, "params": params}).encode()


class Protocol(unittest.TestCase):
    def setUp(self):
        self.s = mcp.McpServer(lambda: VIEW)

    def call(self, headers, body, method="POST", origin=None):
        if origin:
            headers = {**headers, "origin": origin}
        return self.s.handle(method, headers, body, "1.2.3.4", ORIGIN, {ORIGIN})

    def test_modern_discover(self):
        st, _, p = self.call(*modern("server/discover"))
        self.assertEqual(st, 200)
        self.assertEqual(p["result"]["resultType"], "complete")
        self.assertIn(mcp.MODERN, p["result"]["supportedVersions"])
        self.assertIn("tools", p["result"]["capabilities"])
        self.assertEqual(p["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "sellable-reserves")

    def test_modern_header_mismatch_and_missing(self):
        h, b = modern("tools/list", headers={"mcp-method": "tools/call"})
        st, _, p = self.call(h, b)
        self.assertEqual((st, p["error"]["code"]), (400, -32020))
        h, b = modern("tools/list")
        del h["mcp-protocol-version"]
        self.assertEqual(self.call(h, b)[2]["error"]["code"], -32020)
        h, b = modern("tools/call", {"name": "list_exchanges", "arguments": {}}, headers={"mcp-name": "token_exposure"})
        self.assertEqual(self.call(h, b)[2]["error"]["code"], -32020)

    def test_mcp_name_base64_sentinel_is_decoded(self):
        h, b = modern("tools/call", {"name": "list_exchanges", "arguments": {}}, headers={"mcp-name": "=?base64?bGlzdF9leGNoYW5nZXM=?="})
        self.assertEqual(self.call(h, b)[0], 200)

    def test_unsupported_version(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": {
            "io.modelcontextprotocol/protocolVersion": "1900-01-01", "io.modelcontextprotocol/clientCapabilities": {}}}}).encode()
        st, _, p = self.call({"mcp-protocol-version": "1900-01-01", "mcp-method": "tools/list"}, body)
        self.assertEqual((st, p["error"]["code"]), (400, -32022))
        self.assertEqual(p["error"]["data"]["requested"], "1900-01-01")

    def test_missing_client_capabilities_is_invalid_params(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                           "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": mcp.MODERN}}}).encode()
        st, _, p = self.call({"mcp-protocol-version": mcp.MODERN, "mcp-method": "tools/list"}, body)
        self.assertEqual((st, p["error"]["code"]), (400, -32602))

    def test_unknown_method_is_404_modern(self):
        st, _, p = self.call(*modern("resources/list"))
        self.assertEqual((st, p["error"]["code"]), (404, -32601))

    def test_legacy_initialize_and_tools(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "old", "version": "1"}}}).encode()
        st, _, p = self.call({}, body)
        self.assertEqual(p["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("instructions", p["result"])
        self.assertEqual(self.call({}, json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode())[0], 202)
        st, _, p = self.call({"mcp-protocol-version": "2025-06-18"},
                             json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())
        self.assertEqual([t["name"] for t in p["result"]["tools"]],
                         ["get_exchange_reserves", "list_exchanges", "compare_exchanges", "token_exposure"])
        self.assertNotIn("resultType", p["result"])

    def test_legacy_unknown_version_falls_back_to_latest_legacy(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2024-01-01"}}).encode()
        self.assertEqual(self.call({}, body)[2]["result"]["protocolVersion"], mcp.LEGACY[0])

    def test_get_delete_405_and_bad_origin_403(self):
        self.assertEqual(self.call({}, b"", method="GET")[0], 405)
        self.assertEqual(self.call({}, b"", method="DELETE")[0], 405)
        self.assertEqual(self.call(*modern("tools/list"), origin="https://evil.example")[0], 403)
        self.assertEqual(self.call(*modern("tools/list"), origin=ORIGIN)[0], 200)

    def test_rate_limit(self):
        s = mcp.McpServer(lambda: VIEW)
        codes = [s.handle("POST", *modern("tools/list"), "9.9.9.9", ORIGIN, {ORIGIN})[0] for _ in range(mcp.PER_IP_PER_MIN + 1)]
        self.assertEqual(codes[-1], 429)
        self.assertTrue(all(c == 200 for c in codes[:-1]))


class Tools(unittest.TestCase):
    def setUp(self):
        self.s = mcp.McpServer(lambda: VIEW)

    def tool(self, name, args):
        st, _, p = self.s.handle("POST", *modern("tools/call", {"name": name, "arguments": args}), "5.5.5.5", ORIGIN, {ORIGIN})
        self.assertEqual(st, 200)
        return p["result"]

    def test_exchange_reserves_matches_view(self):
        r = self.tool("get_exchange_reserves", {"exchange": "Blockfinex"})
        d, ex = r["structuredContent"], VIEW["by_slug"]["blockfinex"]
        self.assertFalse(r["isError"])
        self.assertAlmostEqual(d["reported_usd"], ex["reported_usd"], places=1)
        self.assertIsNone(d["days_until_sellable"]["50_percent"])  # no-market tokens block it
        self.assertEqual(d["top_holdings"][0]["symbol"], "USDZ")
        self.assertIn("not solvency", d["limits"])
        self.assertTrue(d["receipts"]["assets"][0].startswith(ORIGIN + "/api/receipt?path="))
        self.assertIn("Limits:", r["content"][0]["text"])

    def test_shared_wallet_surfaces(self):
        d = self.tool("get_exchange_reserves", {"exchange": "bvox"})["structuredContent"]
        self.assertEqual(d["wallets_also_listed_by"], ["Deepcoin"])

    def test_unknown_exchange_is_tool_error_with_suggestion(self):
        r = self.tool("get_exchange_reserves", {"exchange": "Blockfinx"})
        self.assertFalse(r["isError"])  # a single close match resolves
        r = self.tool("get_exchange_reserves", {"exchange": "Nonexistent Exchange"})
        self.assertTrue(r["isError"])

    def test_list_filters_and_sort(self):
        d = self.tool("list_exchanges", {"filter": "no_market"})["structuredContent"]
        self.assertEqual([e["slug"] for e in d["exchanges"]], ["blockfinex"])
        d = self.tool("list_exchanges", {"sort": "size", "limit": 2})["structuredContent"]
        self.assertEqual(len(d["exchanges"]), 2)
        self.assertGreaterEqual(d["exchanges"][0]["reported_usd"], d["exchanges"][1]["reported_usd"])
        self.assertTrue(self.tool("list_exchanges", {"horizon_days": 3})["isError"])

    def test_compare(self):
        d = self.tool("compare_exchanges", {"exchanges": ["ourbit", "Blockfinex"], "horizon_days": 30})["structuredContent"]
        self.assertEqual([e["slug"] for e in d["exchanges"]], ["ourbit", "blockfinex"])
        self.assertTrue(self.tool("compare_exchanges", {"exchanges": ["ourbit"]})["isError"])

    def test_token_exposure(self):
        d = self.tool("token_exposure", {"symbol": "usdz"})["structuredContent"]
        self.assertEqual([h["slug"] for h in d["holders"]], ["blockfinex"])
        self.assertIsNone(d["holders"][0]["days_to_sell"])
        self.assertTrue(self.tool("token_exposure", {"symbol": "NOPE"})["isError"])

    def test_unknown_tool_is_protocol_error(self):
        st, _, p = self.s.handle("POST", *modern("tools/call", {"name": "delete_everything", "arguments": {}}), "6.6.6.6", ORIGIN, {ORIGIN})
        self.assertEqual(p["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
