"""The agent workload: reads the current dataset and writes a short brief.

Registered as kind=agent, so it spawns as a Job on dispatch rather than
standing up a Deployment. It shares quakes.py with the web and cronjob
workloads, which is the point of the fixture: one repo, an app and an agent
side by side, reading the same bound object_store.
"""

import json
import os
import sqlite3
import sys
import time


def brief(db_path: str) -> dict:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        totals = dict(db.execute(
            "SELECT count(*) AS events, max(mag) AS max_mag, "
            "round(avg(depth), 1) AS avg_depth FROM quakes"
        ).fetchone())
        notable = [dict(r) for r in db.execute(
            "SELECT place, mag, time, depth FROM quakes "
            "WHERE mag IS NOT NULL ORDER BY mag DESC LIMIT 5"
        )]
        significant = db.execute(
            "SELECT count(*) AS n FROM quakes WHERE mag >= 4.5"
        ).fetchone()["n"]
    finally:
        db.close()

    headline = (
        f"{totals['events']} events on file; {significant} at M4.5 or above. "
        f"Strongest: {notable[0]['place']} at M{notable[0]['mag']}."
        if notable else f"{totals['events']} events on file."
    )
    return {
        "app": "conflict-quake-dash",
        "workload": "agent",
        "kind": "agent",
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline": headline,
        "totals": totals,
        "significant_m45_plus": significant,
        "notable": notable,
    }


def main() -> int:
    import quakes

    source = quakes.ensure_local_db()
    result = brief(quakes.LOCAL_DB)
    result["dataset_source"] = source
    result["bindings"] = {"object_store": "present" if quakes.BUCKET else "absent"}
    # stdout is the agent's result surface: the dispatch layer captures it and
    # `astro agent logs` replays it.
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
