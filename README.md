# Tempo

**Personalized AI Agent for Intelligent Scheduling and Context-Aware Reminders**

Tempo is a full-stack scheduling application built with Next.js, React, TypeScript, FastAPI, SQLAlchemy and Alembic. Users own their tasks, events, schedules, reminders and conversations. There are no seeded accounts, fabricated statistics or mock calendars in application code.

**An OpenAI API key is optional for installation.** Registration, login, task CRUD, the internal calendar, deterministic scheduling, proposal confirmation, rescheduling, reminders, preferences and history work without it. The assistant clearly reports that it is not configured until a backend key is supplied. Tests use model doubles only in `backend/tests`.

## Quick start on this Windows workspace

The project-local Python runtime and npm dependencies have already been installed under ignored directories. From the project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -SkipInstall
```

Open **http://localhost:3000** and register your own account. The script runs the API, reminder worker and frontend, and stops them when you press Ctrl+C. It copies environment templates only when the destination does not already exist. It never overwrites existing configuration.

Alternatively, use three terminals:

```powershell
# Terminal 1: backend (from project root)
cd backend
..\.runtime\python\python.exe -m alembic upgrade head
..\.runtime\python\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

```powershell
# Terminal 2: reminder worker (from project root)
cd backend
..\.runtime\python\python.exe -m app.worker
```

```powershell
# Terminal 3: frontend (from project root)
cd frontend
npm.cmd run dev
```

Use `localhost:3000` consistently rather than alternating with `127.0.0.1:3000`; the configured frontend origin must match. API documentation is available at `http://localhost:8000/docs`. Interactive documentation requests that mutate data need the `X-Requested-With: Tempo` header; the application client supplies it automatically.

### A fresh machine

Install Python 3.12 and Node.js 22. From the repository root:

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell, instead:
# .\.venv\Scripts\Activate.ps1

python -m pip install -r backend/requirements-lock.txt
cd frontend
npm ci
cd ..
```

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env.local`. Leave OpenAI and Google credentials blank. From `backend`, run `python -m alembic upgrade head`, then `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log`. In a second terminal with the same virtual environment, run `python -m app.worker` from `backend`. Run `npm run dev` from `frontend` in a third terminal.

### Docker with PostgreSQL

Copy the root `.env.example` to `.env` if it does not already exist. Set `POSTGRES_PASSWORD` to a strong, URL-safe password. Then:

```bash
docker compose up --build
```

Open `http://localhost:3000`. Compose runs PostgreSQL, the API, a separate reminder worker and Next.js. PostgreSQL uses a named volume. `docker compose down` preserves that volume; do not add `-v` unless you intend to erase the database. Docker files are supplied, but the local Docker engine was not running, so container startup has not been verified.

## Using Tempo without an API key

1. Register, then open **Settings**. Set your timezone, preferred working hours, session length and breaks.
2. Add fixed commitments in **Calendar**.
3. Create a task with its duration, priority and deadline in **Tasks**.
4. Select **Plan schedule**. Optionally set a start/end bound or a date to keep free.
5. Review the proposed sessions. A partial plan is explicitly labeled with its remaining minutes. Confirm or decline.
6. Confirmed sessions appear in Calendar; reminders and activity records are created in the same database transaction.
7. Select **Replan** to propose replacement sessions. The existing plan remains intact until confirmation. Mark individual sessions done or skipped in Calendar, or complete the entire task in Tasks.

The assistant becomes available after adding `OPENAI_API_KEY` to `backend/.env` and restarting the API. A model configured by `OPENAI_MODEL` must be available to your API account. Nothing in the frontend receives the key.

## Environment variables

Backend configuration is read from environment variables, or `backend/.env` when commands run from `backend`. The root `.env` is only for Docker Compose; it is not automatically loaded by the backend launched from `backend`.

| Variable | Local default / purpose |
| --- | --- |
| `DATABASE_URL` | `sqlite:///./scheduler.db`; production: `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB` |
| `ENVIRONMENT` | `development`; set `production` when deployed |
| `SECRET_KEY` | Blank locally; generate 32+ characters for the production configuration guard. Sessions use random opaque tokens rather than signed JWTs. |
| `FRONTEND_URL` | `http://localhost:3000`; exact permitted origin, with no trailing slash |
| `COOKIE_SECURE` | `false` locally; must be `true` in production |
| `SESSION_HOURS` | `168`; session lifetime |
| `OPENAI_API_KEY` | Blank until you want the assistant enabled; backend only |
| `AI_ENABLED` | `true` by default; set `false` to disable model calls even if a key exists, especially on isolated test servers |
| `OPENAI_MODEL` | `gpt-4.1-mini`; configurable Responses API model |
| `AGENT_MAX_ITERATIONS` | `8`; bounded model/tool rounds |
| `GOOGLE_CLIENT_ID` | Optional Google OAuth web application client ID |
| `GOOGLE_CLIENT_SECRET` | Optional backend-only OAuth secret |
| `GOOGLE_REDIRECT_URI` | `http://localhost:3000/api/calendar/google/callback`; production must use your frontend HTTPS origin |
| `TOKEN_ENCRYPTION_KEY` | Fernet encryption key for Google tokens; required only when Google is configured |
| `RATE_LIMIT_PER_MINUTE` | `120`; general API limit. Authentication and agent requests have tighter limits. |
| `PREFERENCE_WEIGHT` | `100`; heuristic scheduling weight |
| `EARLY_WEIGHT` | `20`; heuristic early-completion weight |
| `FRAGMENTATION_WEIGHT` | `10`; heuristic short-session penalty |

Frontend: set **`BACKEND_URL`** in `frontend/.env.local` locally, or in Vercel's server-side environment. Local value: `http://127.0.0.1:8000`. This is resolved into the same-origin `/api/*` rewrite when Next.js starts/builds. Rebuild/redeploy after changing it. Do not introduce `NEXT_PUBLIC_OPENAI_API_KEY` or any other public secret.

Generate production secrets with Python, then store the output privately in the hosting provider's secret manager:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The first command provides a `SECRET_KEY`; the second provides `TOKEN_ENCRYPTION_KEY`. Do not replace a Google encryption key without a token migration, or users will need to reconnect. `.env*` files are ignored, except the placeholder `.env.example` templates.

## Architecture and technical reasoning

```text
Browser / Next.js / React
        | same-origin /api proxy, HttpOnly session cookie
FastAPI authentication + Pydantic validation
        |
        +-- ordinary REST routes ------------------+
        |                                         |
        +-- OpenAI Responses tool loop -> Registry |
                                      |           |
                                 Application services
                                      |
                    +-----------------+-----------------+
                    |                 |                 |
             Pure scheduler     SQLAlchemy ORM   CalendarService
                    |                 |           /           \
               proposals       SQLite / Postgres internal    Google OAuth
                    |
          explicit confirmation + locked revalidation
                    |
             sessions + reminders + history
                    |
           independent in-app reminder worker
```

The LLM interprets intent, extracts information, asks clarification questions and selects tools. It does not calculate calendar availability or write SQL. Tools are bound to an `Application` instance whose identity comes from the authenticated session, not from model arguments. Pydantic rejects extra `user_id` fields. IDs used in agent mutations must first have appeared in tool results, and every access is still checked for ownership.

The scheduling engine is deterministic and independent of the model, database and network. This permits repeatable testing and explainable decisions. Stored preferences provide explicit context, while activity history supports small, interpretable personalization heuristics. These weights and behavioral rules are engineering heuristics, **not scientifically validated measures of intelligence**.

### Scheduling algorithm

- Accept aware instants, convert to UTC, and interpret working hours using the user's IANA timezone.
- Enumerate candidate starts on a 15-minute UTC grid, within a maximum 90-day planning window. UTC stepping handles DST gaps and folds without inventing wall-clock times.
- Hard constraints: no task/event overlap, no session after the deadline, no excluded local dates, and no weekend sessions unless enabled. Work is bounded to 06:00–23:00 local time.
- All internal calendar event types are treated as occupied time. “Flexible” events are not silently moved.
- Merge occupied intervals expanded by the requested break length, then use binary search to find available boundaries.
- Split remaining work into sessions up to the preferred session length. Previously completed session minutes are subtracted; skipped minutes remain to be scheduled.
- Rank feasible candidates with `preference_weight * preferred_match + early_weight * priority_factor / (1 + days_away) - fragmentation_weight * shortfall_ratio`. Earlier start breaks a score tie. The priority factors are 0.5/1/1.5/2 for LOW/MEDIUM/HIGH/CRITICAL.
- Select the highest-scoring slot, reserve it, and repeat. This greedy strategy is transparent and bounded; it is not a global optimum guarantee. Short usable fragments below 15 minutes are omitted unless they finish the last few minutes of work.
- If allocation is incomplete, return actual allocated and remaining minutes. A partial plan may be confirmed explicitly; it is never presented as a complete schedule. Batch changes are only offered when every task is feasible.
- Batch scheduling sorts up to ten tasks by priority, deadline and ID, reserving each plan before calculating the next.

Preferred hours/days are soft ranking preferences, so the engine can propose other reasonable hours to meet a deadline. Weekend permission and excluded dates remain hard constraints. Missing deadlines use a 14-day working horizon. Longer requested horizons are capped at 90 days.

### Confirmation and concurrency

Scheduling, rescheduling, significant event edits/deletions and permanent agent preference changes create database-backed proposals with 30-minute expiry. The model has no confirmation tool. Only the dedicated authenticated decision route can accept a proposal.

Acceptance obtains a per-user database write lock, recomputes availability and compares the proposed slots with the new result. If anything material changed, it returns HTTP 409 and requires a fresh proposal. Sessions, reminders, task status, proposal state and history are then committed together. Duplicate acceptance is rejected. All application calendar/schedule writers use the same user lock; SQLite serializes writers and PostgreSQL locks the user's row.

For batches, every plan is recomputed before any plan is applied, and the whole batch commits atomically. Confirmation of one independent proposal can invalidate another; that is intentional. External Google changes can still happen after a fetch, so there is no claim of a distributed transaction across Google and the local database.

### Personalization

Within a 60-day activity window, at least three distinct tasks moved from before 18:00 to 18:00 or later trigger a suggested 19:00–22:00 preference. One action never changes permanent preferences. Settings lets the user review and save the suggestion. Personalization can be disabled. This deliberately narrow heuristic is an extension point for richer models.

### Reminder delivery

`python -m app.worker` polls every 10 seconds (configurable). Transactional publication makes due and snoozed reminders available in-app, records activity and queues device deliveries in a durable Web Push outbox. Leases, retries and browser occurrence deduplication handle restarts and duplicate execution. The bell and inbox poll every 15 seconds. Browser push requires permission and VAPID configuration; email remains disabled. See [notification setup, architecture and two-minute demo](docs/notifications.md).

## Database models and code layout

| Model | Purpose |
| --- | --- |
| `User`, `AuthSession` | Account, Argon2id hash, revocable hashed session token |
| `UserPreference` | IANA zone, working preferences, breaks and personalization opt-in |
| `Task` | Duration, deadline, priority, status and completion timestamp |
| `CalendarEvent` | Owned internal or imported provider event |
| `ScheduledTask` | Individual task session and completion/skip state |
| `Reminder` | Task/session-linked or standalone in-app reminder |
| `UserActivity` | Bounded-query audit/activity history |
| `Proposal` | Server-calculated actions, expiry and decision state |
| `ChatMessage` | Persistent conversation plus structured tool receipts |
| `GoogleCalendarConnection`, `OAuthState` | Encrypted OAuth credentials and single-use state |

Foreign keys cascade task deletion to sessions/reminders and user deletion to owned rows. Activity and proposal JSON use historical IDs intentionally and are not foreign keys. Indexed ownership/time/status fields support isolation and lookup. Datetimes are stored as UTC values; the SQLAlchemy type restores UTC awareness when SQLite reads them. Naive incoming datetimes are rejected. Browser datetime entry uses Temporal with `disambiguation: reject`, requiring the user to choose another time when a wall time is ambiguous or nonexistent.

```text
backend/
  app/api/routes.py              authenticated REST routes
  app/core/                     settings and authentication helpers
  app/db/                       engine, UTC type, ORM models
  app/schemas.py                validated request contracts
  app/services/application.py  ownership, lifecycle, proposals, personalization
  app/services/calendar.py      provider interface and internal implementation
  app/scheduling/scheduler.py   pure scheduler and conflict operations
  app/agent/                    prompt, bounded Responses loop, tool registry
  app/integrations/             Google OAuth and calendar adapter
  app/notifications/            delivery channel interface and in-app publisher
  app/worker.py                 reminder process
  alembic/                      schema migrations
  tests/                        scheduler, API, security, agent and provider tests
frontend/
  app/                          all eight requested pages and global styles
  components/                   auth provider, shell, forms, shared proposal cards
  lib/                          centralized API client, types, timezone conversions
scripts/start-local.ps1         Windows startup helper
compose.yaml                   local PostgreSQL deployment
render.yaml                    Render API/database/worker blueprint
.github/workflows/ci.yml        backend and frontend verification
```

### Agent tools

`get_user_profile`, `get_user_preferences`, `update_user_preference`, `get_tasks`, `get_task`, `create_task`, `update_task`, `complete_task`, `get_calendar_events`, `create_calendar_event`, `update_calendar_event`, `delete_calendar_event`, `find_available_time`, `detect_conflicts`, `schedule_task`, `reschedule_task`, `reschedule_multiple_tasks`, `create_reminder`, `get_reminders`, `get_activity_history`.

The Responses API tool loop uses JSON Schema from Pydantic. Optional/default parameters use `strict: false` in the provider schema and are validated locally before execution. At most eight model rounds execute; calls are sequential. Conversation context is limited to recent messages, and activity retrieval is capped at 30 entries. Successful actions are committed individually and returned as structured receipts, so a later provider outage cannot conceal earlier saved actions. Errors are also returned as receipts. The model's explanatory text is not a substitute for these receipts or schedule cards.

Reference: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).

## API summary

All private routes require the HttpOnly `session` cookie. Mutations require `X-Requested-With: Tempo` and reject an unexpected Origin.

- `/api/auth/register`, `/login`, `/me`, `/logout`
- `/api/tasks` and `/api/tasks/{id}`: list/create/read/update/delete
- `/api/events` and `/api/events/{id}`: list/create/update/delete
- `/api/preferences`, `/api/preferences/suggestions`
- `/api/reminders`, `/api/reminders/{id}`
- `/api/calendar`, `/api/calendar/plan`, `/api/calendar/plan-batch`, `/api/calendar/sessions/{id}`
- `/api/proposals`, `/api/proposals/{id}/decision`
- `/api/agent/chat`, `/api/agent/history`
- `/api/dashboard`, `/api/activity`, `/api/health`
- `/api/calendar/google/status`, `/connect`, `/callback`, `/sync`, `/disconnect`

Agent response: `{message, actions, requires_confirmation, proposals}`. A plan response includes `feasible`, `slots`, `scheduled_minutes`, `unscheduled_minutes` and an optional persisted proposal. Errors use a `detail` field; validation errors omit rejected input values.

## Database migrations

From `backend`, with the correct environment activated:

```bash
python -m alembic upgrade head
python -m alembic current
python -m alembic check
# After intentional model edits:
python -m alembic revision --autogenerate -m "describe the schema change"
```

Review generated migrations before applying them. For `UTCDateTime`, generated migrations may require conversion to `sa.DateTime()` (the underlying storage type). The initial migration contains explicit schema operations and does not import live model metadata. Back up production databases before migration. `python -m alembic downgrade -1` is available for development, but the initial downgrade drops application data.

## Google Calendar setup

1. Create/select a Google Cloud project, enable the Google Calendar API and configure the OAuth consent screen.
2. Create an OAuth **Web application** client. Register the exact redirect URI `http://localhost:3000/api/calendar/google/callback` for local use and `https://YOUR_FRONTEND/api/calendar/google/callback` for production.
3. Add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` and a generated `TOKEN_ENCRYPTION_KEY` to the backend environment.
4. Restart the backend. In Settings, select **Connect Google**, grant the calendar permission and then **Sync now**.

OAuth state is random, hashed, single-use, time-limited and bound to the authenticated user. Access and refresh tokens are Fernet-encrypted before persistence. Refresh is server-side; secrets are never exposed in API responses. Provider request failures produce safe errors and do not report synchronization success.

The adapter imports the primary calendar from 30 days in the past to 90 days in the future, follows all pages, expands recurring instances, handles all-day dates in the provider's timezone, and removes deleted imported events within that window. Transparent/declined events do not block time. Connected calendars refresh before scheduling/confirmation; a failed refresh blocks the operation rather than silently using stale data. Sync reports conflicts with existing task sessions without moving them automatically.

The provider class implements remote create/update/delete operations behind `CalendarService`. The current product UI edits imported events in Google and keeps generated task sessions local; automatic bidirectional task export is not enabled. Disconnect removes locally stored credentials and imported events. Users may additionally revoke access through Google account permissions.

Reference: [Google Calendar events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list).

## Tests and verification

```powershell
# This workspace, from root
cd backend
..\.runtime\python\python.exe -m pytest -q
..\.runtime\python\python.exe -m ruff check .
..\.runtime\python\python.exe -m alembic check
cd ..\frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

On a normal virtual environment, replace the runtime path with `python`; on non-Windows systems use `npm` rather than `npm.cmd`.

Tests cover password hashing/session revocation, validation/CSRF, ownership across resources and proposals, task lifecycle, cascading deletion, fixed-event conflicts, deadline failure, task splitting, preferred/fallback hours, weekends, DST/timezones, stale/expired/replayed confirmations, rescheduling, batch atomicity, completed-session accounting, reminder worker idempotency, personalization thresholds, bounded tool loops, ID retrieval, structured receipts, provider failure after a successful action, OAuth state and encrypted token failure, paginated/all-day Google import.

The scripted-model end-to-end test follows the requested networking assignment scenario and verifies task creation, preference/calendar retrieval, split proposals, untouched meeting, confirmation and saved sessions. These tests verify orchestration independently of live model quality. Live OpenAI and Google account tests require your credentials and were not performed.

Browser QA uses a separate ignored `.runtime/browser-tests.db`; it is not the application's `backend/scheduler.db`. See `docs/verification.md` for the final run results and manual browser checks.

## Deployment: Vercel + Render + PostgreSQL

Deployment is configured, not published automatically. You must supply your hosting accounts and domain values.

1. Push this repository to your own Git provider. Ensure no `.env*` secret files are staged.
2. In Render, create a Blueprint from `render.yaml`, or create a PostgreSQL database, a Python web service and a background worker manually. Select plans appropriate to your account; the blueprint provisions paid resources.
3. Web service root: `backend`; Python: `3.12`; build: `pip install -r requirements-lock.txt`; pre-deploy: `python -m alembic upgrade head`; start: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log`; health: `/api/health`.
4. Set the API's `DATABASE_URL` to the private PostgreSQL connection string. Both `postgres://` and `postgresql://` are normalized to the installed psycopg 3 driver. Set `ENVIRONMENT=production`, `COOKIE_SECURE=true`, a random 32+ character `SECRET_KEY`, and `FRONTEND_URL=https://YOUR_FRONTEND` with no trailing slash.
5. Worker root: `backend`; same dependency build; start: `python -m app.worker`; same `DATABASE_URL`. Start it after the initial migration has completed. The worker retries safely if the schema is not ready.
6. In Vercel, import the repository and select **`frontend` as Root Directory** and the Next.js preset. Install: `npm ci`; build: `npm run build`; use the default Next.js output handling. Set server-side `BACKEND_URL=https://YOUR_RENDER_API` before building.
7. Deploy Vercel, update Render's exact `FRONTEND_URL` if necessary, and restart the API. Browser requests stay on the frontend origin through the Next.js rewrite, so HttpOnly SameSite=Lax cookies remain first-party. Do not expose a public browser API URL or store bearer tokens in localStorage.
8. Optional: add backend OpenAI credentials. Optional Google setup uses the frontend HTTPS callback URL so the OAuth callback retains the same session cookie.
9. Register a real account through the deployed frontend. Verify tasks, calendar, planning/confirmation and worker-delivered in-app reminders. Configure managed database backups, monitoring and restore testing before broad use.

For AWS, use the supplied backend image for an ECS/Fargate service and worker, an RDS PostgreSQL instance, HTTPS behind an ALB, private database networking and Secrets Manager. Run `alembic upgrade head` as a one-off deployment task before starting the new service version. Set the same production variables and point Vercel's `BACKEND_URL` to the API's HTTPS domain.

## Security and operational limits

- Argon2id password hashes; random, revocable, server-side sessions stored only as hashes; HttpOnly/SameSite cookies; HTTPS/Secure required in production.
- Ownership checks at service boundaries, ORM queries, strict input schemas, fixed tool allowlist, retrieved-ID checks and no raw database/model execution tools.
- Exact CORS origin, custom-header CSRF boundary, safe error responses, request IDs, token-free application logs and SQL parameter hiding. Keep Uvicorn access logs disabled in production to avoid logging OAuth callback query codes.
- Per-process in-memory rate limiting is suitable for a small single-instance deployment. Add gateway/distributed throttling, body-size limits and centralized monitoring before scaling horizontally. Set provider budgets and quotas separately.
- No password-reset email, verified-email onboarding, MFA, account export/deletion UI or shared/team calendars yet. Plan those before inviting a broad public audience.
- List views currently cap results at 500 recent records; activity and chat context are more tightly bounded. The scheduler's conflict queries and dashboard counts are not truncated. Add cursor pagination and date-window loading for large long-lived accounts.
- Local recurring-event creation is explicitly rejected. Google recurrence is expanded during import. Day and week views are implemented; month view is not.
- Calendar snapshots cannot guarantee protection against changes made concurrently in external Google clients after the final fetch. The app does not claim to reserve time externally.
- The heuristic scheduler can return an incomplete allocation even where a more complex optimizer could find a solution; it always reports what it actually allocated. Future work can add OR-Tools without changing agent authorization boundaries.
- Notifications require the worker process. Browser push requires a supported browser, permission, a valid session, VAPID configuration and network access; provider acceptance does not guarantee OS presentation. Email and location sensing are not implemented.
- LLM-generated explanatory text remains probabilistic. Authoritative action receipts, IDs, proposals and calendar state come from server tools, and mutation success is never inferred by the frontend from prose.

This repository is a deployable implementation with production-oriented safeguards, not a claim of an independently audited or load-tested production service.
