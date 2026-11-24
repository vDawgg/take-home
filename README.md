# Almedia Take Home

A FastAPI service that returns app offers a user has not installed yet.

The seeded dataset contains 20,000 users and 1,000,000 installs over an app
universe of 200 apps. Installs are stored in a read-optimized table with one
row per user and an `INTEGER[]` of app IDs. The endpoint filters a fixed list
of 100 candidate app IDs loaded from `app_ids.json`, with a small local async
cache in front of the database.

## Requirements

- Docker and Docker Compose
- [uv](https://docs.astral.sh/uv/) for running scripts locally
- Python 3.13 (uv will install/manage it if needed)

## Quick start

Start the whole stack:

```bash
docker compose up -d --build --wait
```

This starts Postgres, runs the one-shot seed service, then starts the API.
The API is available at:

- `http://localhost:8000/offers?user_id=1`
- Interactive docs: `http://localhost:8000/docs`

Example request:

```bash
curl "http://localhost:8000/offers?user_id=1"
```

Response shape:

```json
{"user_id": 1, "app_ids": [6, 10, 12, 13, 15]}
```

`app_ids` contains the filtered candidate list, so a real response usually
contains several dozen IDs.

## Configuration

Local defaults live in `.env`:

```dotenv
POSTGRES_USER=postgres
POSTGRES_PASSWORD=pass
POSTGRES_DB=postgres
DATABASE_URL=postgresql://postgres:pass@localhost:5432/postgres

UVICORN_WORKERS=1
DB_POOL_MIN_SIZE=1
DB_POOL_MAX_SIZE=10
```

- `DATABASE_URL` is used by scripts run from the host.
- Docker Compose overrides the database host with the `postgres` service name.
- Each Uvicorn worker creates its own asyncpg pool.
- Keep `UVICORN_WORKERS * DB_POOL_MAX_SIZE` below Postgres `max_connections`
  (100). For example, 8 workers with a pool of 10 uses 80 connections.
- The local cache is per worker, bounded to 1,024 entries, with a 10-second TTL.
- `app_ids.json` defines the 100 candidate app IDs. Reseed if you change it.

To use more server workers:

```bash
UVICORN_WORKERS=4 docker compose up -d --force-recreate --wait app
```

## Seeding

Seeding happens automatically through the `seed` Compose service. It is
idempotent: if `user_installs` already has 20,000 users and 1,000,000 installs,
it exits without writing anything.

## Load testing

Install dependencies and run the load generator:

```bash
uv sync
uv run python scripts/load_test.py --requests 1000 --rate 100
```

Options:

- `--requests` — total requests (default: `1000`)
- `--rate` — target arrival rate in req/s (default: `100`)
- `--users` — user pool size (default: `1000`, maximum: `20,000`)
- `--seed` — RNG seed for repeatable user IDs (default: `42`)
- `--url` — offers endpoint URL
- `--timeout` — per-request timeout in seconds

`--users` controls cache reuse:

- `--users >= --requests` samples unique users.
- Lower `--users` values reuse users more often. Use `--users 1` for an
  all-hot-cache run.

Example cache comparison:

The generator splits the target rate across worker processes automatically
(roughly 250 req/s per worker). Each run writes a CSV to `results/`, named with
the timestamp, request count, rate, and user pool, for example:

```
results/latency_23-11-2026_15-22_1000req_1000rps_1users.csv
```

## Visualizations

Generate a latency chart for every CSV in `results/`:

```bash
uv run python scripts/visualize_latency.py
```

Each CSV gets a matching PDF chart containing:

- latency over time
- target rate and user-pool size
- average, p50, p95, and p99
- DB calls and cache hit rate when captured

Generate a comparison heatmap for the base/index/read-model experiments:

```bash
uv run python scripts/compare_runs.py
```

The heatmap script reads `base_latency_*`, `index_latency_*`, and
`read_model_latency_*` CSVs across their tested request rates and writes
`results/comparison_p99.pdf` by default.

`results/` is gitignored; generated CSVs and charts are local artifacts.

## Project layout

```text
base/            asyncpg pool setup
core/            request schema, routes, cache and offer logic
main.py          FastAPI application and lifespan
seed.py          dataset generator
app_ids.json     fixed list of 100 candidate app IDs
scripts/         load test and visualization tools
docker-compose.yml
Dockerfile
```
