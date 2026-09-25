"""Backfill Supabase history from locally stored raw CMC responses.

For each clock hour before the current one that has a stored quotes run, pair
the last quotes run of that hour with the newest exchanges run at or before it,
recompute with the same code the live server uses, and write one row per
exchange. Existing (slug, fetched_at) rows are left untouched.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python3 scripts/backfill_history.py [data_dir]
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sellable.history import History  # noqa: E402
from sellable.live import Live  # noqa: E402
from sellable.store import Store  # noqa: E402


def main():
    data = sys.argv[1] if len(sys.argv) > 1 else "data"
    store, history = Store(data), History()
    if not history.enabled:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    this_hour = datetime.now(timezone.utc).strftime("%Y%m%dT%H")
    ex_runs = store.runs("exchanges")
    last_per_hour = {}
    for q in store.runs("quotes"):
        if q[:11] < this_hour:
            last_per_hour[q[:11]] = q
    for hour, qts in sorted(last_per_hour.items()):
        ex = [e for e in ex_runs if e <= qts]
        if not ex:
            print(f"{hour}: no exchanges run at or before {qts}, skipped")
            continue
        live = Live(store)
        live.load_from_store(ex[-1], qts)
        view = live.build_view()
        history.record(view)
        print(f"{hour}: quotes {qts} + exchanges {ex[-1]} -> {len(History.rows_from_view(view))} rows")


if __name__ == "__main__":
    main()
