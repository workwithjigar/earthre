# SLA Monitoring Dashboard

Upload a CSV of health-check logs. A stateless serverless function (AWS Lambda) parses, validates and cleans it, and stores it in Postgres. A single-screen dashboard then shows SLA stats and the underlying check records.

| | URL |
|---|---|
| **App (upload + dashboard)** | `https://sla-monitor-aic.pages.dev/` |
| **API (AWS Lambda Function URL)** | `https://cok73ve4cbynh35ky6ypq7jc6q0mfyog.lambda-url.us-east-1.on.aws/` · health: `/api/health` · docs: `/docs` |
| **Last verified live** | 2026-09-26

**Stack:** React + TypeScript + Vite on **Cloudflare Pages** → Python **FastAPI** on **AWS Lambda** (Function URL, via Mangum) → **Neon Postgres**. Every piece is on a free tier.

### Requirements coverage

How each point in the assignment is met:

| Requirement | Where / how |
|---|---|
| **Upload UI**: a screen where the user uploads the CSV | `/` page ([UploadPage.tsx](frontend/src/pages/UploadPage.tsx)): drag-and-drop or file picker. After processing it shows the data-quality report for that file, plus the list of datasets uploaded so far. |
| **Stateless serverless processing**, deployed in the cloud | `POST /api/uploads` runs on **AWS Lambda** ([template.yaml](template.yaml), [lambda_handler.py](backend/lambda_handler.py)). Parsing, validation and cleaning live in [cleaning.py](backend/app/cleaning.py). Nothing is kept in memory between requests. |
| **Persistence**: cleaned data is re-queryable later | **Postgres (Neon)**: `uploads` and `checks` tables ([db.py](backend/app/db.py)). Each upload is written in one transaction. |
| **Single-screen dashboard**: a stats section that collapses/expands | `/dashboard/:id` ([DashboardPage.tsx](frontend/src/pages/DashboardPage.tsx), [StatsPanel.tsx](frontend/src/components/StatsPanel.tsx)). It shows a one-line summary when collapsed, and the collapsed/expanded state is remembered. The stats chosen and why are in §3. |
| **Logs view filterable by a single date or a date range** | [LogsView.tsx](frontend/src/components/LogsView.tsx) + [DateFilter.tsx](frontend/src/components/DateFilter.tsx): *All dates / Single date / Date range* (UTC). It can also filter by service, outcome, agent, and "changed by cleaner". |
| **Messy data found and handled** | §2: 11 issue types, each counted per file, with a validation script run against `dataset_incident_log.json` |
| **Free tier only** | Lambda (always-free: 1M requests per month), Lambda Function URL (free, no API Gateway), Neon free tier (no card), Cloudflare Pages free tier (no card) |
| **Deployed and live** | See the URLs above. §4 has local run + redeploy steps. |
| **Out of scope, deliberately not built** | Authentication / user accounts, multi-tenancy, CI pipelines |

### Repository layout

```
backend/
  app/
    cleaning.py        parse → validate → clean; returns records + data-quality report (no I/O)
    stats.py           slots, availability, error budget, incidents, latency percentiles, monthly credits
    db.py              schema (SQLAlchemy Core) + queries; SQLite locally, Postgres deployed
    main.py            FastAPI routes
    config.py          settings read from environment variables
    schemas.py         response models
  lambda_handler.py    Lambda entry point (Mangum wraps the FastAPI app)
  scripts/
    package_lambda.sh      builds dist/lambda.zip with Linux wheels (no Docker needed)
    validate_incidents.py  compares detected incidents with dataset_incident_log.json
  tests/               pytest: parsers, cleaning rules, stats, API end-to-end
frontend/
  src/pages/           UploadPage, DashboardPage
  src/components/      StatsPanel, LogsView, DateFilter, QualityReport
  src/api.ts           typed API client (base URL from VITE_API_URL)
template.yaml          AWS SAM: Lambda + Function URL
monitoring_checks_*.csv, dataset_incident_log.json   sample data provided with the assignment
```

---

## 1. Architecture

```
 Browser (static hosting)       AWS Lambda (python3.12)                    Neon Postgres (free tier)
┌────────────────────┐        ┌────────────────────────────────────┐     ┌──────────────────────┐
│ React SPA          │ POST   │ Function URL → Mangum → FastAPI    │ SQL │ uploads  1 per file  │
│  /           upload│───────▶│  cleaning.py  parse/validate/clean │────▶│ checks   1 per       │
│  /dashboard/:id    │◀───────│  stats.py     SLA, incidents       │◀────│   reading, indexed   │
│                    │ JSON   │  db.py        SQLAlchemy Core      │     │   by upload + time   │
└────────────────────┘        └────────────────────────────────────┘     └──────────────────────┘
```

| Piece | Where it runs | Why |
|---|---|---|
| **Frontend**: React + TypeScript + Vite | **Cloudflare Pages**. Build output is plain static files. | No server needed. The free tier (unlimited bandwidth, no card) doesn't expire, and deploying is one CLI command. Single-page app routes work without extra config. |
| **API + processing**: Python FastAPI | **AWS Lambda** behind a **Function URL**, adapted by [Mangum](https://mangum.io) | The function holds no state between requests: every request reads or writes the DB. Function URLs are free and need no API Gateway. The Lambda free tier (1M requests / 400k GB-s per month) never expires. |
| **Database**: Postgres | **Neon** free tier (no credit card) | Stats need date-range scans and grouping, and uploads are bulk inserts. SQL does both easily. DynamoDB's free 25 WCU would throttle a 15k-row upload, and every aggregation would need its own index design. SQLite inside Lambda is not persistent. |

**Request flow**
1. The upload page posts the file as `multipart/form-data` to `POST /api/uploads`.
2. The Lambda runs `cleaning.clean_csv()`. This is a pure function (bytes in, clean records + data-quality report out) with no I/O, which keeps it unit-testable.
3. The upload row and all check records are written in **one transaction**, so a failed upload leaves nothing half-written.
4. The dashboard calls `GET /api/uploads/{id}/stats?start&end` and `GET /api/uploads/{id}/checks?start&end&service_id&outcome&agent&flagged_only&page`. Stats are computed on request from stored rows. At this data size (≤16k rows per upload) that takes about 150 ms, and it avoids precomputed tables going stale.

**Why one Lambda, not two** (one for processing, one for queries): both jobs are stateless. Splitting them would double the deployment surface without any benefit at this scale. The processing logic is still an isolated module (`cleaning.py`) that could move into its own S3-triggered function unchanged. See §5.

### API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/uploads` | Upload a CSV (field `file`). Returns the dataset + data-quality report. `422` for unusable files, `413` if too big. |
| `GET` | `/api/uploads` | List datasets |
| `GET` | `/api/uploads/{id}` | One dataset + its data-quality report |
| `DELETE` | `/api/uploads/{id}` | Remove a dataset |
| `GET` | `/api/uploads/{id}/stats?start=YYYY-MM-DD&end=YYYY-MM-DD` | Overview, per-service SLA, incidents, daily grid, monthly credits |
| `GET` | `/api/uploads/{id}/checks?...` | Paginated, filterable check records |
| `GET` | `/api/health` | Liveness |

Interactive docs are at `/docs` (FastAPI / Swagger).

---

## 2. Data findings

All five sample files share the same set of problems (they come from one generator with different seeds). The pipeline does not rely on that: every rule below is generic and reports what it found in each upload.

| Issue | 9d | 12d | 14d | 21d | 30d | How it's handled |
|---|---|---|---|---|---|---|
| **Latency in seconds**: `search-api` always reports `latency_unit = s` (e.g. `0.717`), the rest use `ms` | 924 | 1227 | 1433 | 2147 | 3090 | Multiplied by 1000. Without this, search-api's p95 would read as "0.7 ms" and it would look like the fastest service. |
| **Unix-epoch timestamps** (`1747909800`) mixed with ISO | 70 | 93 | 109 | 163 | 233 | Parsed as UTC seconds (13-digit values as ms) |
| **Timestamps with `+05:30` offset**: IST, the local time of `ap-south-1` agents | 32 | 43 | 50 | 76 | 109 | Converted to UTC. Treating them as UTC would move the check 5.5 h and create a fake gap plus a fake duplicate. |
| **Blank latency** | 56 | 74 | 87 | 130 | 186 | Latency stored as `NULL` and left out of latency percentiles. **The status still counts** for availability: a reading with no latency still reports up or down. |
| **Exact duplicate rows** | 6 | 8 | 10 | 18 | 24 | Dropped, one copy kept |
| **Same reading written twice in different formats**: same service, same slot, same agent, once as ISO and once as epoch/offset (sometimes one copy has a blank latency) | 1 | 2 | 2 | 0 | 1 | Merged into one record. Preference order: valid status, then has a latency, then fewest normalisations. If copies disagreed on up/down (not seen), the failing copy would win. |
| **Status code `999`**: not a valid HTTP status | 1 | 1 | 1 | 1 | 1 | Kept in logs as `invalid`, with the raw 999 visible. It counts as neither up nor down. In the 14d file another agent saw that slot as 200, so the slot still counts as up. Otherwise the slot is *unknown* and left out of the denominator. |
| **Negative latency** (e.g. `-296 ms`) | 1 | 1 | 1 | 1 | 1 | Latency nulled; the status (200) still counts |
| **Second monitoring agent**: `agent-2` re-checks ~7% of slots | 345 | 460 | 537 | 806 | 1152 | **Not duplicates.** These are independent observations: both are kept and shown in the logs. For SLA purposes a slot is DOWN if *any* valid reading failed. Once the 999 is discarded, agents disagree on up/down in **0** slots, so this rule doesn't change any number today. |
| **Rows not in time order** | yes | yes | yes | yes | yes | Sorted on ingest |
| **Slow but "successful" checks**: HTTP 200 with 1.3–3 s latency, only during incidents (normal max is ~860 ms) | | | | | | Still count as *up* for availability (the SLA is about availability). They count as "bad" for **incident detection** and in the "slow checks" stat, because they are the start of every real outage in the data. |

Things checked and **not** found in these files, but handled because real feeds contain them: missing 15-minute checks (coverage report; gaps are *not* counted as downtime), off-grid timestamps (snapped to the nearest slot), timestamps with no timezone (assumed UTC), malformed rows, blank lines, repeated header rows, missing or unknown latency units, `service_name` values that disagree with their `service_id`, and wrong or missing columns (the whole file is rejected with a clear 422 message).

After cleaning, every file has a complete grid: 96 slots × days × 5 services, and the detected date range matches the incident log's day count exactly (9, 12, 14, 21, 30).

**Validation against `dataset_incident_log.json`**: `backend/scripts/validate_incidents.py` runs the pipeline on every sample file and compares detected incidents to the log. **All 8 logged incidents are detected**, with matching start and end times (within one 15-min slot). It also reports 3 extra short error bursts in `reports-api`/`search-api` that are not in the log. For example, 9d `search-api` 2025-05-16 has three consecutive 5xx checks: 45 minutes of real downtime. An on-call engineer would want to see that, so the detector reports it.

---

## 3. Assumptions & decisions

**Availability and SLA**
- **A check stands for its 15-minute window.** One failed check = 15 minutes of downtime. This is the only reading the data allows. It makes the 99.9% SLA very strict: a 30-day month allows 43.2 minutes of downtime, which is **fewer than 3 failed checks**. As a result, *every service breaches in every sample file*. The background error rate alone (e.g. reports-api fails ~3% of checks) is enough. That is a real finding about the data, not a bug.
- **Up = HTTP 1xx–3xx; down = 4xx/5xx.** A health endpoint returning 4xx is failing its check. Only 200 and 5xx appear in the samples.
- **Availability = up / (up + down).** *Unknown* slots (only an invalid status) and *missing* slots are left out of both sides rather than counted as downtime. Customer-favourable billing might instead count missing data as down. I chose not to invent failures, and coverage gaps are reported separately so they stay visible.
- **Multi-agent rule: down if any valid reading failed.** This is customer-favourable. The alternative ("down only if all agents agree") is more provider-favourable. It changes nothing on this data (0 disagreements) and is a single line in `stats.build_slots` if billing policy disagrees.
- **SLA is per calendar month (UTC).** The monthly table always uses the whole dataset and ignores the date filter: an SLA over an arbitrary date range isn't something anyone gets billed on. Months the data doesn't fully cover are labelled *partial*, e.g. the 30-day file covers 25 days of April and 5 of May. Their figures are provisional: the rest of the month could still add downtime.
- **Credit tiers are illustrative:** `<99.9% → 10%`, `<99.0% → 25%`, `<95.0% → 100%` (the shape of the AWS / GCP SLAs). The spec only gives the 99.9% threshold. Tiers, target and slow threshold are all config (`SLA_TARGET`, `SLOW_THRESHOLD_MS`, `StatsConfig`).
- **Everything is UTC**, and the UI labels it. The date filter selects UTC calendar days.

**Incidents**: a run of "bad" checks (down, or slower than 1000 ms) where up to 2 healthy checks inside the run don't split it (outages flap: the samples have 200s in the middle of 5xx bursts). A run counts as an incident only with **≥3** bad checks. One or two scattered 5xx are counted in availability but don't page anyone. These thresholds came from comparing against the incident log. With a minimum of 2 bad checks, pairs of random failures showed up as ~15 false incidents.

**Which stats, and why.** Two audiences, one screen:
- *Billing / support:* "Did we breach, and what do we owe?" → per-service **availability vs target**, **SLA met/breached**, **downtime vs allowed downtime**, **error budget used**, and the **monthly table with credit %**.
- *On-call:* "What broke, when, and is it still going on?" → **incidents list** (start, end, duration, failed vs slow checks, peak latency, status codes), a **service × day grid of failed checks** to spot patterns at a glance, and **p50 / p95 / p99 latency** (p95 moves early when a service degrades).
- *Trust in the numbers:* **slow** and **unknown** check counts, and the full **data-quality report** for the upload, so the person reading an SLA number can see what the cleaner changed to produce it.
- Grid cells and incidents are **clickable**: they set the date and service filters and scroll to the matching logs. Going from a number to its raw evidence takes one click.
- The stats panel is **collapsible**, and it remembers its state across visits. When collapsed, it still shows a one-line summary ("5/5 breaching · 2 incidents · worst svc-reports").
- The page-level date filter applies to the stats and the logs together, so the two always describe the same period.

**Uploads are separate datasets.** Each upload gets its own id, and the dashboard has a dataset picker. The five sample files overlap in time (April–May 2025) for the same service ids. Merging them would double-count checks, and the spec gives no rule for which file is correct.

**Logs show cleaned records, not raw rows.** Each record carries chips for what the cleaner did to it (`s → ms`, `epoch → UTC`, `duplicate merged`, …) and keeps the raw timestamp. A "records the cleaner changed" toggle filters down to those. Exact duplicates are counted in the report but not stored.

**Upload size**: the upload is capped at 4 MB. A Lambda sync payload is limited to 6 MB, and base64 encoding adds ~33%. The largest sample is 1.2 MB.

---

## 4. Live URL, running locally & deploying

**Live URL:** see the table at the top. Every component is on a free tier that does not expire (Lambda always-free, Neon free, Cloudflare Pages free), so the app should stay up. The one caveat is that Neon's free database pauses when idle and needs a second or two to wake. If the app ever goes down, the redeploy steps below bring it back in a few minutes.

### Prerequisites
Python 3.10+ (Lambda runs 3.12), Node 20+. For deploying: AWS SAM CLI and AWS credentials, plus a free Neon project.

### Local (no cloud needed; uses SQLite)
```bash
# API on http://localhost:8000  (docs at /docs), from the repo root
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# Frontend on http://localhost:5173 (second terminal, from the repo root)
cd frontend
npm install
npm run dev          # VITE_API_URL defaults to http://localhost:8000
```
To run locally against Postgres, set `DATABASE_URL=postgresql+psycopg2://…` before starting uvicorn. Tables are created automatically on first use.

### Tests
```bash
cd backend
pytest                                       # 38 tests: parsers, cleaning rules, stats, API end-to-end
python -m scripts.validate_incidents ..      # compare detected incidents with dataset_incident_log.json
```

### Configuration

Everything is read from environment variables ([config.py](backend/app/config.py)). **No secrets are in the repo:** the database URL goes to Lambda as a CloudFormation parameter (`NoEcho`), and `samconfig.toml` / `.env` are gitignored.

| Variable | Default | Used for |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./local.db` | SQLAlchemy URL. Deployed: Neon, `postgresql+psycopg2://…?sslmode=require` |
| `CORS_ORIGINS` | `*` | Comma-separated browser origins allowed to call the API |
| `SLA_TARGET` | `99.9` | Availability target, % |
| `SLOW_THRESHOLD_MS` | `1000` | Latency above which a check counts as slow (for incidents) |
| `MAX_UPLOAD_BYTES` | `4194304` | Upload size cap |
| `VITE_API_URL` (frontend, build time) | `http://localhost:8000` | API base URL, no trailing slash |

### Deploy (redeploy on demand)

Prerequisites: an AWS account with CLI credentials (`aws configure`), AWS SAM CLI, and free accounts on [Neon](https://neon.tech) and [Cloudflare](https://dash.cloudflare.com).

**1. Database (Neon)**: create a project in the same region as the Lambda (`us-east-1`) and copy its connection string. Change the start from `postgresql://` to `postgresql+psycopg2://`. Tables are created automatically on the first request.

**2. API (AWS Lambda)**: keep the URL in a shell variable so it never ends up in a file:
```bash
export NEON_URL='postgresql+psycopg2://USER:PASSWORD@HOST/neondb?sslmode=require'

cd backend && source .venv/bin/activate && ./scripts/package_lambda.sh && cd ..
sam deploy \
  --stack-name sla-monitor --region us-east-1 \
  --capabilities CAPABILITY_IAM --resolve-s3 --confirm-changeset \
  --parameter-overrides "DatabaseUrl=\"$NEON_URL\" CorsOrigins=\"*\""
```
The stack output **`ApiUrl`** is the Function URL. Check it with `curl <ApiUrl>api/health` → `{"status":"ok"}`.

**3. Frontend (Cloudflare Pages)**:
```bash
cd frontend
VITE_API_URL=https://<id>.lambda-url.us-east-1.on.aws npm run build     # no trailing slash
npx wrangler login                                                       # first time only
npx wrangler pages deploy dist --project-name sla-monitor
```
It prints the site URL (`https://sla-monitor.pages.dev`).

**4. Restrict CORS to the frontend**: re-run the `sam deploy` from step 2 with `CorsOrigins=\"https://sla-monitor.pages.dev\"`.

| To redeploy… | Run |
|---|---|
| Backend changes | Step 2 (package + `sam deploy`) |
| Frontend changes | Step 3 (`npm run build` + `wrangler pages deploy`) |
| Tear everything down | `sam delete --stack-name sla-monitor`, then delete the Pages project and the Neon project |

**Troubleshooting**
- *"Could not reach the API" in the UI*: `VITE_API_URL` was wrong or missing at build time. Vite bakes it into the build, so rebuild and redeploy.
- *CORS error in the browser console*: `CorsOrigins` must exactly match the Pages URL (scheme included, no trailing slash).
- *Upload returns 500*: check `sam logs --stack-name sla-monitor --tail`. It's usually a bad `DATABASE_URL`: it needs the `+psycopg2` prefix and `sslmode=require`.
- *Slow first request*: Neon's free compute suspends when idle. The first request after a quiet period takes ~1–2 s longer.

---

## 5. What I'd do differently with more time

- **Upload via S3 presigned URL + S3-triggered processing Lambda.** This removes the 6 MB payload limit, lets processing run asynchronously with a status the UI polls, and makes "processing function" and "query API" separate deployables.
- **Idempotent uploads**: hash the file and warn if the same content was already uploaded.
- **Migrations** (Alembic) instead of `create_all`. A `COPY`-based bulk insert for much larger files.
- **Precompute slot-level rollups at ingest** once datasets grow past the size where computing stats on request is fine.
- **Configurable billing policy in the UI**: multi-agent rule, treatment of missing data, credit tiers. These are policy questions for the business, not engineering constants.
- **Charts**: availability-over-time and latency sparklines per service. Right now the day grid covers the "when" question.
- Frontend tests (component tests for the filter logic) and a Playwright smoke test against the deployed URL.
- Structured logging + request ids in the Lambda. A CloudWatch alarm on processing errors.

