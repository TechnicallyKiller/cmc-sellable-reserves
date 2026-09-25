"""Raw-response storage (gzip) with retention, per DECISIONS D5.

Layout: <root>/<kind>/<UTC timestamp>/<name>.json.gz
  kind = "quotes" or "exchanges"
Quotes: every refresh kept for the last hour, then one per hour.
"""
import gzip
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

TS_FORMAT = "%Y%m%dT%H%M%SZ"


def now_ts():
    return datetime.now(timezone.utc).strftime(TS_FORMAT)


class Store:
    def __init__(self, root):
        self.root = root

    def write(self, kind, ts, name, raw_bytes):
        d = os.path.join(self.root, kind, ts)
        os.makedirs(d, exist_ok=True)
        with gzip.open(os.path.join(d, f"{name}.json.gz"), "wb") as f:
            f.write(raw_bytes)
        return f"{kind}/{ts}/{name}.json"

    def read(self, rel_path):
        """rel_path as returned by write(); returns parsed JSON."""
        kind, ts, fname = rel_path.split("/")
        if not self._safe(kind, ts, fname):
            raise FileNotFoundError(rel_path)
        with gzip.open(os.path.join(self.root, kind, ts, fname + ".gz"), "rb") as f:
            return json.load(f)

    def runs(self, kind):
        d = os.path.join(self.root, kind)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def prune_quotes(self, now=None):
        now = now or datetime.now(timezone.utc)
        kept_hours = set()
        for ts in reversed(self.runs("quotes")):
            t = datetime.strptime(ts, TS_FORMAT).replace(tzinfo=timezone.utc)
            if now - t <= timedelta(hours=1):
                continue
            hour = ts[:11]
            if hour in kept_hours:
                shutil.rmtree(os.path.join(self.root, "quotes", ts))
            else:
                kept_hours.add(hour)

    @staticmethod
    def _safe(*parts):
        return all(p and "/" not in p and ".." not in p for p in parts)
