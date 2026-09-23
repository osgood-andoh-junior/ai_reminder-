# Tempo notifications: implementation and demo

## Architecture

The existing `Reminder` model remains the source of truth. Scheduling creates reminders with deterministic times based on the user's existing default reminder offset. Creation is not delivery: the separate worker changes due `PENDING` or `SNOOZED` reminders to `SENT`, records activity and queues push deliveries in the same transaction. The frontend never decides when a reminder is due. No OpenAI request is involved in execution.

In-app notifications use the reminder itself, avoiding a second notification inbox. `SENT` means unread in-app; `READ`, `DISMISSED`, `SNOOZED`, `COMPLETED` and `CANCELLED` retain useful history. Snooze increments an occurrence generation and keeps the original reminder time. Push failure is tracked separately on `NotificationDelivery`, so it never turns a successfully published in-app notification into a failed reminder.

The bell polls unread count and recent deliveries every 15 seconds, refreshes on focus and after mutations, and responds to service-worker messages. The Reminders page has Upcoming, Unread, Snoozed, Past and All tabs. Bell and page actions use the same authenticated APIs.

## Reliability and boundaries

- Due publication uses the same user write locks as reminder mutations, with stable lock ordering. This works with SQLite and PostgreSQL. A unique outbox constraint prevents duplicate device/occurrence jobs.
- Workers claim push jobs with an atomic conditional update and a two-minute lease. Interrupted leases can be recovered after restart. Failed requests retry with exponential backoff, up to five attempts; expired 404/410 subscriptions become inactive.
- Read, dismissed, cancelled, rescheduled or newly snoozed reminders invalidate stale delivery jobs. Push failure never prevents other jobs or in-app publication.
- External delivery cannot offer transactional exactly-once semantics: a process can die after the push provider accepts a request but before committing its acknowledgement. Stable notification tags and a seven-day IndexedDB occurrence ledger suppress duplicate browser display across retries/restarts. Clearing browser storage resets that ledger.
- Provider acceptance is recorded as `REMINDER_PUSH_ACCEPTED`, not proof that an OS displayed the notification. Browser support, permission, connectivity, OS quiet modes and browser background policies still control presentation.
- The service worker receives only reminder/user IDs and generation, then fetches the reminder under the current session before displaying content. Logout removes the current device subscription; an expired or different account cannot retrieve the old reminder's content. Stay signed in for push delivery. The backend must remain reachable when the push arrives.
- In-app content is always available after delivery. The worker must be running; sleeping or shutting down the host prevents local execution until restart. Overdue reminders publish on the next worker pass.
- Email is explicitly disabled. `EmailNotificationChannel` is an extension point that raises a configuration error, never a fake success. A future provider should use a separate channel outbox with provider idempotency keys, retries and verified recipient addresses.

## Configuration

Existing environment secrets are preserved. New backend and worker settings:

| Variable | Purpose |
|---|---|
| `VAPID_PUBLIC_KEY` | Public application key supplied to authenticated browsers |
| `VAPID_PRIVATE_KEY` | Server-only private key, shared by API/worker deployment |
| `VAPID_SUBJECT` | `mailto:` or HTTPS contact URI for the application operator |
| `REMINDER_POLL_INTERVAL_SECONDS` | Worker polling interval; default 10, range 1–300 |

Generate keys once from `backend` using your Python environment:

```powershell
..\.runtime\python\python.exe configure_push.py --subject https://localhost
```

The helper appends missing local VAPID configuration to ignored `backend/.env`, never prints keys and refuses to replace an existing partial configuration. Production must use the operator's real contact URI, such as `mailto:admin@your-domain.example`. Keep the same private/public pair on API and worker; rotating it requires browsers to unsubscribe and enable again. Never prefix the private key with `NEXT_PUBLIC_`. No frontend environment variable is needed: the authenticated config endpoint exposes only the public key.

The current local installation has VAPID keys configured. Browser permission remains controlled by the person using the browser.

## Start locally

From the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

Use `-SkipInstall` after dependencies are installed. The launcher migrates SQLite and starts Next.js, FastAPI and the independent reminder worker, with logs in the project root. Or run `python -m app.worker` from `backend` in a separate terminal alongside the existing API/frontend commands. Use a terminal with outbound network access for OpenAI and browser push.

Open `http://localhost:3000` consistently; `localhost` and `127.0.0.1` are different browser origins. Use a supported normal browser such as Chrome, Edge or Firefox if an embedded browser cannot obtain a push subscription.

## Two-minute notification demo

1. Start Tempo and sign in. Open Settings → Notifications → **Enable browser notifications**, then allow the browser prompt. The page must say **On for this device**; granting permission alone is not enough if subscription registration fails.
2. Open Reminders → **New reminder**. Set title to “Professor demo,” add a short message, and choose a time one minute in the future in the displayed timezone. Submit.
3. Navigate to Overview, or minimize the browser while keeping the computer awake. Within the worker's 10-second poll after the chosen time, the reminder becomes unread in-app. The bell updates within another 15 seconds. The OS notification appears where supported and allowed.
4. Click the OS notification to open Tempo, or open the bell. Choose **Snooze**, then **Custom time** about one minute in the future. (Preset buttons offer 10 minutes, 30 minutes and one hour.)
5. Wait for the second occurrence. The unread count increases again; its generation differs from the first delivery, so duplicate suppression allows the snoozed notification.
6. Choose **Dismiss**. The unread count drops, and the reminder remains in **Past** with its dismissed status. Settings → Recent activity includes the sent/snoozed/dismissed actions.

To demonstrate scheduling integration, first set **Remind me before sessions · minutes** to 1 or 2 and save. Create a short task, select **Plan schedule**, review the real proposed start and confirm. A session reminder is created automatically. The scheduler uses 15-minute candidate boundaries, so this route may require longer than two minutes. For a custom relative reminder, tell the Assistant “Remind me one minute before [task name]”; it reads actual sessions and uses `minutes_before` in the reminder tool. If there are multiple sessions it asks which one.

The Assistant can also create “tomorrow at 08:00” using `local_date`/`local_time`, snooze via minutes and propose dismissal for confirmation. Application code resolves dates in the stored timezone; ambiguous/nonexistent DST times are rejected.

## Endpoints

Existing `GET/POST /api/reminders` and `PATCH /api/reminders/{id}` remain supported. New endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/reminders/unread-count` | Exact owned unread count |
| `GET /api/reminders/recent` | Latest 10 sent/read reminders |
| `GET /api/reminders/{id}` | Owned reminder and session/timezone context |
| `POST /api/reminders/{id}/read` | Mark delivered reminder read |
| `POST /api/reminders/{id}/dismiss` | Dismiss while retaining history |
| `POST /api/reminders/{id}/snooze` | `{minutes: 30}` or `{until: "offset timestamp"}` |
| `GET /api/reminders/{id}/deliveries` | Push attempts, status and safe error codes |
| `GET /api/notifications/config` | Configuration state and public VAPID key only |
| `POST /api/notifications/subscriptions` | Register the current user's device |
| `GET /api/notifications/subscriptions` | Owned device IDs and active state, no endpoint secrets |
| `POST /api/notifications/subscriptions/remove` | Remove current browser endpoint binding |
| `DELETE /api/notifications/subscriptions/{id}` | Deactivate an owned device |
| `PATCH /api/preferences/notifications` | Browser/deadline opt-in and default reminder offset |

Mutation routes retain cookie authentication, ownership checks and the `X-Requested-With: Tempo` CSRF header. Push endpoints allow known browser push providers only, validate encryption keys, block redirects and reject local/arbitrary HTTP targets. Raw endpoints/keys are never included in the subscription listing.

## Deployment

Migration `c7e2a901_notifications.py` extends reminders/preferences and creates `push_subscriptions` plus `notification_deliveries`. Apply `python -m alembic upgrade head` before starting updated services. SQLite was tested locally; production uses PostgreSQL with the same transaction model.

Docker Compose already has a worker; its shared environment now includes VAPID settings. Render's API and worker both require matching VAPID values. Use HTTPS on the public frontend, expose `/sw.js` at the origin root without caching, and allow worker outbound HTTPS to browser push providers. Run the worker as a persistent service, not a serverless request or cron tied to page loads. Start conservatively and monitor delivery failures and backlog before increasing volume.

Web Push references: [MDN Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API), [pywebpush transport](https://github.com/web-push-libs/pywebpush). iOS browser support has additional installed-web-app requirements; desktop Chrome/Edge/Firefox is the recommended demo environment.

## Troubleshooting

- **AI unavailable:** this installation's backend was started under a network-restricted execution environment. A normal network-enabled launch restored the connection, verified both directly and in the Assistant UI. `python diagnose_ai.py` checks the configured model/tool schemas without revealing secrets or reading user tasks. The app now distinguishes connection, authentication, quota/rate-limit and model access errors. See [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes).
- **No in-app notification:** check `worker-error.log`, confirm the worker is running against the same database, and inspect the reminder's timezone/time. A reminder is not delivered merely because its creation succeeded.
- **Permission denied:** allow notifications in the browser's site settings, then reload Settings. Tempo never repeatedly invokes permission prompts.
- **Permission granted but push off:** click Enable to register the device. Check VAPID configuration, push-provider access and browser support. Failed registration is shown as an error.
- **Embedded browser reports `jmt17.google.com`:** this is Chromium's old staging push endpoint, documented as deprecated in the [Chromium endpoint change](https://chromium.googlesource.com/chromium/src.git/+/40644b8cf2b03be542976e7d1192c653e389c14e). Use a regular supported browser for the OS notification demo. Do not rewrite subscription endpoints or disable endpoint validation.
- **Push accepted but no OS popup:** check OS notification settings/Focus Assist, browser background execution, session validity and connectivity to Tempo. Read delivery status through the owned deliveries endpoint. In-app notifications remain available.
- **`push_http_410` / `push_http_404`:** subscription expired. Enable notifications again. Persistent 401/403 errors usually indicate mismatched VAPID configuration; correct keys and resubscribe.
- **Email checkbox:** email is intentionally unavailable until a provider is implemented; enabling it via the preference API is rejected.

## File report

Created: migration `backend/alembic/versions/c7e2a901_notifications.py`; `backend/app/notifications/{service,push,email,strategies,timing}.py`; `backend/configure_push.py`; `backend/diagnose_ai.py`; backend notification tests; `frontend/components/{notification-bell,notification-settings,reminder-actions}.tsx`; `frontend/lib/notifications.ts`; `frontend/public/sw.js`; frontend notification component tests and Vitest configuration; this guide.

Modified: existing models, schemas, configuration, application services, API routes, agent tools/error handling/tests, worker and notification interface/in-app implementation; existing reminder/settings/task pages, shell, proposal UI, types/API client/styles/Next configuration; dependency manifests/locks, CI, environment templates, Compose, Render and README. The app's architecture and unrelated page design were preserved.

See [verification.md](verification.md) for executed checks and remaining verification boundaries.
