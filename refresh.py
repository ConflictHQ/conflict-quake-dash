"""The refresh cronjob: USGS feed -> SQLite -> the app's object_store bucket.

This is the workload that makes the earthquake dataset worth having. Unlike a
static archive it actually changes, so the schedule has something to do and the
web workload has a reason to re-read.
"""

import json
import os
import sys
import time

import quakes


def main() -> int:
    started = time.time()
    client = quakes.s3()
    if client is None:
        # Fail loudly: a refresh with nowhere to write is a misconfigured
        # binding, not a no-op worth exiting 0 over.
        print(json.dumps({
            "app": "conflict-quake-dash", "job": "refresh", "ok": False,
            "error": "BUCKET_NAME is unset -- no object_store bound to this workload",
        }), flush=True)
        return 1

    rows = quakes.fetch_feed()
    path = "/tmp/refresh-quakes.db"
    count = quakes.build_db(rows, path)
    client.upload_file(path, quakes.BUCKET, quakes.OBJECT_KEY)

    print(json.dumps({
        "app": "conflict-quake-dash", "job": "refresh", "ok": True,
        "events": count,
        "bucket": quakes.BUCKET,
        "key": quakes.OBJECT_KEY,
        "bytes": os.path.getsize(path),
        "elapsed_s": round(time.time() - started, 2),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
