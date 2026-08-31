# conflict-quake-dash

A USGS seismic-activity dashboard whose **data tier is S3, not a database** —
and the APP+Agent shape: one repo carrying a service, a scheduled job, and an
agent, all reading the same bound object store.

## Topology

| | |
|---|---|
| Workloads | `web` (`deployment`, public) · `refresh` (`cronjob`, every 4h) · `brief` (`agent`, dispatched) |
| Managed services | `object_store` / `s3`, bound to all three |
| Storage | SQLite built by the cronjob, kept in the bucket, pulled by the web workload |
| Idle cost | one small pod, plus a few cents of S3 |

```
USGS feed ──▶ refresh (cronjob) ──▶ quakes.db ──▶ object_store (S3)
                                                        │
                                    web (deployment) ◀──┤  pulled at boot + every 15m
                                    brief (agent)    ◀──┘  read on dispatch
```

## Why earthquakes

The dataset actually changes, so the refresh schedule has something to do and
the web workload has a reason to re-read. A static archive would make the
cronjob decorative.

## Endpoints

| Path | Purpose |
|---|---|
| `/` | The dashboard |
| `/health` | Probe target |
| `/debug` | Pod identity, uptime, binding presence, dataset source and age |
| `/selftest` | **Really** exercises the bucket — put, get, delete — and reports `{ok, latency_ms, error}` |

`/selftest` is the one that matters here: it proves the `object_store` binding
works, not merely that the pod started.

## Degraded mode is deliberate

A trimmed seed CSV is baked into the image. If the bucket is unreachable or the
cronjob has not run yet, the web workload builds its dataset from that seed and
serves stale data with `dataset_source: seed`, rather than crash-looping. The
dashboard says which source it is on, in the sidebar and in `/debug`.

## Deploying

```sh
astro app register --project-id <demos-project-guid> \
  --source-repo ConflictHQ/conflict-quake-dash \
  --build-mode platform_build
astro app deploy --wait
astro agent dispatch brief          # the agent half
```

The platform creates the ECR repository, mints the build and runtime roles,
builds in-cluster with Kaniko and rolls out. Nothing is built locally.

## Charts

The categorical palette and sequential ramp were run through the palette
validator against the `#0A0A0A` panel surface and pass every check. Magnitude
and depth are *magnitudes*, so they get the single-hue sequential ramp rather
than competing categorical hues. Charts are hand-rolled inline SVG — a private
install should not reach a CDN to draw its own dashboard.

Data: [USGS Earthquake Hazards Program](https://earthquake.usgs.gov/earthquakes/feed/),
public domain.
