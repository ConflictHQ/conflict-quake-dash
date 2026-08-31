"""conflict-quake-dash — a dashboard whose data tier is S3, not a database.

The dataset is a SQLite file the refresh cronjob builds from the USGS feed and
uploads to the app's bound object_store. This workload pulls it at boot and on
a timer. Storage costs pennies a month and there is no database to pay for.
"""

import json
import os
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import quakes

PORT = int(os.environ.get("PORT", "8080"))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
REFRESH_SECONDS = int(os.environ.get("DATASET_REFRESH_SECONDS", "900"))
BOOT = time.time()
APP = "conflict-quake-dash"
VERSION = os.environ.get("GIT_SHA", "dev")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}

_state = {"source": "none", "loaded_at": None}
_lock = threading.Lock()


def load_dataset():
    with _lock:
        source = quakes.ensure_local_db()
        _state["source"] = source
        _state["loaded_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return source


def refresh_loop():
    while True:
        time.sleep(REFRESH_SECONDS)
        try:
            source = load_dataset()
            print(json.dumps({"app": APP, "msg": "dataset reloaded", "source": source}), flush=True)
        except Exception as exc:  # a failed reload must not kill the server
            print(json.dumps({"app": APP, "msg": "dataset reload failed", "error": str(exc)}), flush=True)


def q(sql, args=()):
    db = sqlite3.connect(quakes.LOCAL_DB)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql, args).fetchall()]
    finally:
        db.close()


def summary():
    row = q(
        "SELECT count(*) AS events, max(mag) AS max_mag, "
        "round(avg(depth), 1) AS avg_depth, min(time) AS first_time, max(time) AS last_time "
        "FROM quakes"
    )[0]
    row["significant"] = q("SELECT count(*) AS n FROM quakes WHERE mag >= 4.5")[0]["n"]
    strongest = q(
        "SELECT place, mag FROM quakes WHERE mag IS NOT NULL ORDER BY mag DESC LIMIT 1"
    )
    row["strongest_place"] = strongest[0]["place"] if strongest else None
    row["dataset_source"] = _state["source"]
    return row


def by_day():
    return q(
        "SELECT substr(time, 1, 10) AS day, count(*) AS n FROM quakes "
        "WHERE time != '' GROUP BY day ORDER BY day"
    )


def by_magnitude():
    """Half-magnitude buckets. Magnitude is ordinal, so this is a distribution,
    not a set of categories competing for hues."""
    return q(
        "SELECT CAST(mag * 2 AS INTEGER) / 2.0 AS bucket, count(*) AS n "
        "FROM quakes WHERE mag IS NOT NULL GROUP BY bucket ORDER BY bucket"
    )


def depth_scatter():
    return q(
        "SELECT place, mag, depth, time FROM quakes "
        "WHERE mag IS NOT NULL AND depth IS NOT NULL AND mag > 0 "
        "ORDER BY mag DESC LIMIT 2500"
    )


def top_regions():
    """The feed's place strings end in a region name after the last comma."""
    return q(
        "SELECT trim(substr(place, instr(place, ',') + 1)) AS region, "
        "count(*) AS n, round(max(mag), 1) AS max_mag "
        "FROM quakes WHERE place LIKE '%,%' GROUP BY region "
        "ORDER BY n DESC LIMIT 12"
    )


def strongest(limit=10):
    return q(
        "SELECT place, mag, depth, time, magType FROM quakes "
        "WHERE mag IS NOT NULL ORDER BY mag DESC LIMIT ?",
        (limit,),
    )


def debug_payload():
    seen = sorted(
        k for k in os.environ
        if not any(s in k.upper() for s in ("SECRET", "PASSWORD", "TOKEN", "KEY"))
    )
    size = os.path.getsize(quakes.LOCAL_DB) if os.path.exists(quakes.LOCAL_DB) else 0
    return {
        "app": APP,
        "version": VERSION,
        "kind": "deployment",
        "hostname": socket.gethostname(),
        "uptime_s": round(time.time() - BOOT, 1),
        "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "env_seen": seen,
        "bindings": {"object_store": "present" if quakes.BUCKET else "absent"},
        "dataset": {
            "source": _state["source"],
            "loaded_at": _state["loaded_at"],
            "bytes": size,
            "refresh_seconds": REFRESH_SECONDS,
        },
    }


def selftest():
    """Actually exercises the bound object_store -- put, get, delete -- rather
    than reporting that the pod started."""
    checks = []

    t0 = time.time()
    try:
        n = q("SELECT count(*) AS n FROM quakes")[0]["n"]
        checks.append({"service": "sqlite (local cache)", "ok": n > 0,
                       "latency_ms": round((time.time() - t0) * 1000, 2),
                       "detail": f"{n} events from {_state['source']}", "error": None})
    except Exception as exc:
        checks.append({"service": "sqlite (local cache)", "ok": False,
                       "latency_ms": round((time.time() - t0) * 1000, 2),
                       "detail": None, "error": str(exc)})

    client = quakes.s3()
    if client is None:
        checks.append({"service": "object_store", "ok": False, "latency_ms": None,
                       "detail": None, "error": "BUCKET_NAME unset -- no object_store bound"})
    else:
        key = f"selftest/{socket.gethostname()}-{int(time.time())}"
        t0 = time.time()
        try:
            client.put_object(Bucket=quakes.BUCKET, Key=key, Body=b"astrolift-selftest")
            body = client.get_object(Bucket=quakes.BUCKET, Key=key)["Body"].read()
            client.delete_object(Bucket=quakes.BUCKET, Key=key)
            checks.append({"service": "object_store", "ok": body == b"astrolift-selftest",
                           "latency_ms": round((time.time() - t0) * 1000, 2),
                           "detail": f"put/get/delete on {quakes.BUCKET}", "error": None})
        except Exception as exc:
            checks.append({"service": "object_store", "ok": False,
                           "latency_ms": round((time.time() - t0) * 1000, 2),
                           "detail": None, "error": str(exc)})

    return {"app": APP, "ok": all(c["ok"] is not False for c in checks), "checks": checks}


ROUTES = {
    "/api/summary": summary,
    "/api/by-day": by_day,
    "/api/by-magnitude": by_magnitude,
    "/api/scatter": depth_scatter,
    "/api/regions": top_regions,
    "/api/strongest": strongest,
    "/debug": debug_payload,
    "/selftest": selftest,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._send(200, {"status": "ok"})
        if path in ROUTES:
            try:
                return self._send(200, ROUTES[path]())
            except Exception as exc:
                return self._send(500, {"error": str(exc)})
        if path == "/":
            path = "/index.html"
        target = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if target.startswith(STATIC) and os.path.isfile(target):
            with open(target, "rb") as fh:
                return self._send(200, fh.read(),
                                  MIME.get(os.path.splitext(target)[1], "application/octet-stream"))
        return self._send(404, {"error": "not found", "path": path})

    def log_message(self, fmt, *args):
        print(json.dumps({"app": APP, "msg": fmt % args,
                          "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}), flush=True)


if __name__ == "__main__":
    source = load_dataset()
    print(json.dumps({
        "app": APP, "version": VERSION, "port": PORT,
        "dataset_source": source,
        "bindings": {"object_store": "present" if quakes.BUCKET else "absent"},
        "msg": "listening",
    }), flush=True)
    threading.Thread(target=refresh_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
