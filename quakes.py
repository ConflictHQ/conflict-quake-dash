"""Shared dataset plumbing for conflict-quake-dash.

Three processes read this: the web workload, the refresh cronjob, and the
agent. The SQLite file is the interchange format and S3 (the app's bound
``object_store``) is where it lives between them.
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import urllib.request

USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.csv"

# The object_store binding's env envelope (spec 05 §9.4).
BUCKET = os.environ.get("BUCKET_NAME", "")
BUCKET_REGION = os.environ.get("BUCKET_REGION") or os.environ.get("AWS_REGION", "us-west-2")
BUCKET_ENDPOINT = os.environ.get("BUCKET_ENDPOINT", "")

OBJECT_KEY = "quakes.db"
LOCAL_DB = os.environ.get("QUAKE_DB", "/tmp/quakes.db")
SEED_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seed-quakes.csv")

COLUMNS = ("time", "latitude", "longitude", "depth", "mag", "magType", "id", "place", "type")
NUMERIC = {"latitude", "longitude", "depth", "mag"}


def s3():
    """Client for the bound bucket, or None when nothing is bound.

    Returning None rather than raising is what lets the web workload boot from
    its seed on a cluster where the object_store binding is missing -- the
    dashboard degrades to stale data instead of crash-looping.
    """
    if not BUCKET:
        return None
    import boto3

    kwargs = {"region_name": BUCKET_REGION}
    if BUCKET_ENDPOINT:
        kwargs["endpoint_url"] = BUCKET_ENDPOINT
    return boto3.client("s3", **kwargs)


def _num(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def build_db(rows, path: str) -> int:
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.execute(
        """
        CREATE TABLE quakes (
            id TEXT PRIMARY KEY, time TEXT, latitude REAL, longitude REAL,
            depth REAL, mag REAL, magType TEXT, place TEXT, type TEXT
        )
        """
    )
    payload = [
        tuple(_num(r.get(c)) if c in NUMERIC else (r.get(c) or "").strip() for c in
              ("id", "time", "latitude", "longitude", "depth", "mag", "magType", "place", "type"))
        for r in rows
    ]
    # The feed revises events in place, so the same id can appear twice across
    # a refresh window; last write wins rather than aborting the build.
    db.executemany("INSERT OR REPLACE INTO quakes VALUES (?,?,?,?,?,?,?,?,?)", payload)
    db.execute("CREATE INDEX idx_time ON quakes(time)")
    db.execute("CREATE INDEX idx_mag ON quakes(mag)")
    db.commit()
    count = db.execute("SELECT count(*) FROM quakes").fetchone()[0]
    db.close()
    return count


def fetch_feed() -> list[dict]:
    with urllib.request.urlopen(USGS_FEED, timeout=90) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def seed_rows() -> list[dict]:
    with open(SEED_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def ensure_local_db() -> str:
    """The newest dataset available, preferring S3 and falling back to the
    seed baked into the image."""
    client = s3()
    if client is not None:
        try:
            client.download_file(BUCKET, OBJECT_KEY, LOCAL_DB)
            return "s3"
        except Exception:
            # No object yet (the cronjob has not run), or no access. Either
            # way the seed keeps the dashboard serving.
            pass
    build_db(seed_rows(), LOCAL_DB)
    return "seed"
