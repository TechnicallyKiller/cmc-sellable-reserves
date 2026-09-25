"""Sellable Reserves server.

  python3 server.py                  # live: needs CMC_KEY, refreshes from CMC
  python3 server.py --replay         # no key: serves the newest stored responses

API:
  GET /api/status
  GET /api/exchanges
  GET /api/exchange/<slug>
  GET /api/receipt?path=<kind/ts/name.json>   raw CMC response behind a number
  GET /api/history/<slug>                     hourly sellable shares (Supabase), if enabled
  POST /api/ask {question, slug}              LLM answer, or {"fallback": true}
  GET /e/<slug>                               share link: preview tags, then the exchange page
  POST /mcp                                   MCP server (Streamable HTTP), read-only tools for AI agents
Static files are served from ./web if it exists.
"""
import argparse
import html
import json
import logging
import os
import threading
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from sellable.ask import MODELS, Asker
from sellable.cmc import Client
from sellable.history import History
from sellable.metric import money_label, pct_label
from sellable.live import Live, dumps
from sellable.mcp import McpServer
from sellable.store import Store

HERE = os.path.dirname(os.path.abspath(__file__))


# Extra browser origins allowed to call /mcp (e.g. a web-based MCP client), comma-separated.
# Non-browser clients send no Origin header and are unaffected.
MCP_ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()}

SITE_DESC = ("Of the reserves your crypto exchange shows you, how much could actually be sold "
             "within a week? Live data from the CoinMarketCap API.")


def page_with_meta(title, desc, url, image):
    """index.html with Open Graph / Twitter card tags filled in."""
    with open(os.path.join(HERE, "web", "index.html"), encoding="utf-8") as f:
        page = f.read()
    e = html.escape
    tags = (f'<meta property="og:type" content="website">\n'
            f'<meta property="og:title" content="{e(title)}">\n'
            f'<meta property="og:description" content="{e(desc)}">\n'
            f'<meta property="og:url" content="{e(url)}">\n'
            f'<meta property="og:image" content="{e(image)}">\n'
            f'<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:title" content="{e(title)}">\n'
            f'<meta name="twitter:description" content="{e(desc)}">\n'
            f'<meta name="twitter:image" content="{e(image)}">\n')
    return page.replace("</head>", tags + "</head>", 1)


def make_handler(live: Live, asker: Asker, history: History):
    mcp = McpServer(lambda: live.view)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=os.path.join(HERE, "web"), **kw)

        def _json(self, code, obj):
            body = dumps(obj)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _origin(self):
            proto = self.headers.get("X-Forwarded-Proto", "http")
            return f"{proto}://{self.headers.get('Host', 'localhost')}"

        def _html(self, body):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            origin = self._origin()
            if url.path == "/mcp":
                return self._mcp("GET")
            if url.path in ("/", "/index.html"):
                return self._html(page_with_meta("Sellable Reserves", SITE_DESC, origin + "/", origin + "/og.png"))
            if url.path.startswith("/e/"):
                slug = url.path[3:].strip("/")
                ex = live.view["by_slug"].get(slug)
                if not ex:
                    return self._html(page_with_meta("Sellable Reserves", SITE_DESC, origin + "/", origin + "/og.png"))
                if ex.get("has_data"):
                    title = (f"{ex['name']}: {pct_label(ex['sellable_share'][7])} of {money_label(ex['reported_usd'])} "
                             f"in reserves could be sold within a week")
                    desc = ex["sentences"][7]
                else:
                    title, desc = f"{ex['name']} publishes no reserves", ex["sentence"]
                page = page_with_meta(title, desc, f"{origin}/e/{slug}", origin + "/og.png")
                # Humans land on the exchange page; crawlers read the tags above.
                page = page.replace("<script>", f"<script>if(!location.hash)history.replaceState(null,'','/#/exchange/{slug}');</script>\n<script>", 1)
                return self._html(page)
            if not url.path.startswith("/api/"):
                return super().do_GET()
            view = live.view
            if url.path == "/api/status":
                return self._json(200, {**live.status(), "coverage": view.get("coverage")})
            if url.path == "/api/exchanges":
                return self._json(200, {
                    "exchanges": view["exchanges"],
                    "exchanges_fetched_at": view.get("exchanges_fetched_at"),
                    "quotes_fetched_at": view.get("quotes_fetched_at"),
                    "coverage": view.get("coverage"),
                    "receipts": view.get("receipts", {}),
                    "mode": "live" if live.client else "replay",
                })
            if url.path.startswith("/api/exchange/"):
                slug = url.path.rsplit("/", 1)[-1]
                ex = view["by_slug"].get(slug)
                return self._json(200, ex) if ex else self._json(404, {"error": f"unknown exchange '{slug}'"})
            if url.path.startswith("/api/history/"):
                slug = url.path.rsplit("/", 1)[-1]
                if not history.enabled:
                    return self._json(200, {"enabled": False, "points": []})
                pts = history.series(slug)
                return self._json(200, {"enabled": True, "points": pts or []})
            if url.path == "/api/receipt":
                path = urllib.parse.parse_qs(url.query).get("path", [""])[0]
                try:
                    return self._json(200, live.store.read(path))
                except (FileNotFoundError, ValueError):
                    return self._json(404, {"error": "no such receipt"})
            return self._json(404, {"error": "not found"})

        def _mcp(self, http_method):
            length = int(self.headers.get("Content-Length") or 0)
            if length > 65536:
                return self._json(413, {"error": "request too large"})
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
            origin = self._origin()
            status, ctype, payload = mcp.handle(http_method, headers, body, ip, origin, {origin} | MCP_ALLOWED_ORIGINS)
            if payload is None:
                self.send_response(status)
                if status == 405:
                    self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return self._json(status, payload)

        def do_DELETE(self):
            if urllib.parse.urlparse(self.path).path == "/mcp":
                return self._mcp("DELETE")
            return self._json(405, {"error": "method not allowed"})

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path == "/mcp":
                return self._mcp("POST")
            if urllib.parse.urlparse(self.path).path != "/api/ask":
                return self._json(404, {"error": "not found"})
            length = int(self.headers.get("Content-Length") or 0)
            if length > 4096:
                return self._json(413, {"error": "request too large"})
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"error": "invalid JSON"})
            # Behind Render's proxy the client address is the first X-Forwarded-For entry.
            ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
            slug = req.get("slug") or None
            answer, detail = asker.ask(live.view, req.get("question"), slug, ip)
            if answer is None:
                logging.getLogger("ask").info("fallback: %s", detail)
                return self._json(200, {"fallback": True, "reason": detail})
            return self._json(200, {"answer": answer, "model": detail})

        def log_message(self, fmt, *args):
            logging.getLogger("http").debug(fmt, *args)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--data", default=os.path.join(HERE, "data"))
    ap.add_argument("--replay", action="store_true", help="serve stored responses; no API key needed")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    store = Store(args.data)
    stop = threading.Event()
    history = History()
    logging.info("history: %s", "enabled (Supabase)" if history.enabled else "disabled (no SUPABASE_URL / SUPABASE_SERVICE_KEY)")
    if args.replay:
        live = Live(store)
        live.load_latest_from_store()
        live.build_view()
    else:
        live = Live(store, Client(os.environ.get("CMC_KEY")), history)
        threading.Thread(target=live.run_forever, args=(stop,), daemon=True).start()

    asker = Asker()
    logging.info("ask panel LLM: %s", f"enabled ({', '.join(MODELS)})" if asker.enabled else "disabled (no LLM_API_KEY), rule-based answers only")
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(live, asker, history))
    logging.info("serving on http://localhost:%d (%s)", args.port, "replay" if args.replay else "live")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()


if __name__ == "__main__":
    main()
