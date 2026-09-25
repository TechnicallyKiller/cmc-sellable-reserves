"""Sellable Reserves server.

  python3 server.py                  # live: needs CMC_KEY, refreshes from CMC
  python3 server.py --replay         # no key: serves the newest stored responses

API:
  GET /api/status
  GET /api/exchanges
  GET /api/exchange/<slug>
  GET /api/receipt?path=<kind/ts/name.json>   raw CMC response behind a number
Static files are served from ./web if it exists.
"""
import argparse
import logging
import os
import threading
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from sellable.cmc import Client
from sellable.live import Live, dumps
from sellable.store import Store

HERE = os.path.dirname(os.path.abspath(__file__))


def make_handler(live: Live):
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

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
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
            if url.path == "/api/receipt":
                path = urllib.parse.parse_qs(url.query).get("path", [""])[0]
                try:
                    return self._json(200, live.store.read(path))
                except (FileNotFoundError, ValueError):
                    return self._json(404, {"error": "no such receipt"})
            return self._json(404, {"error": "not found"})

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
    if args.replay:
        live = Live(store)
        live.load_latest_from_store()
        live.build_view()
    else:
        live = Live(store, Client(os.environ.get("CMC_KEY")))
        threading.Thread(target=live.run_forever, args=(stop,), daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(live))
    logging.info("serving on http://localhost:%d (%s)", args.port, "replay" if args.replay else "live")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()


if __name__ == "__main__":
    main()
