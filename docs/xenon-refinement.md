# Xenon brand and UX refinement

## What changed

The previous frontend used decorative headings ahead of practical page names, small secondary text, and a dashboard led by totals. Authentication retained a split marketing layout, mobile calendar weeks scrolled horizontally, and several settings messages exposed implementation details.

The product now uses **Xenon — Make time for what matters.** Shared semantic colors establish warm neutral surfaces, charcoal text, restrained indigo, readable metadata, and consistent focus/control states. A code-based Xenon mark is used in navigation, authentication, the assistant, and the favicon. Existing routes remain compatible; `/` and successful login now open `/dashboard` (Today).

Today shows timezone-aware greetings, current/next commitments, actual overlaps, overdue priorities, a chronological timeline, and reminders before task totals. Current time updates every minute; crossing the user's local date refreshes the day. The assistant retains editable dictation, text submission, playback, saved per-user voice preferences, and persisted proposal confirmation. Suggestions fill the existing composer. Tool receipts are collapsed under “How Xenon found this”. Proposal decisions still call the dedicated API; reminder values are presented as readable timing labels rather than JSON.

Tasks, Calendar, Reminders, and Settings retain their existing forms/actions. Changes include clearer labels, overdue text, explicit conflict labels, meaningful empty/loading states, retry controls, readable notification availability, and a link to existing voice options. Sign-in is a single focused form. Mobile navigation remains a drawer, the context panel hides at smaller widths, week calendars stack by day, and dialogs remain viewport-contained. Reduced-motion preferences are respected.

## Compatibility and branding audit

| Category | Decision |
| --- | --- |
| User-facing name | Xenon in frontend, metadata, favicon, push fallback/action label, new email subjects, API documentation title, launcher message, and product documentation. |
| Internal identifiers | Retain `tempo-scheduler`, `tempo-voice`, `tempo:voice-responses:<user-id>`, `tempo-notifications`, and push notification tags to avoid losing saved preferences or notification deduplication. |
| Environment variables | Retain `TEMPO_E2E` and all existing production configuration names. |
| Database values | No schema, migration, database name, user, historical conversation, or queued notification rewrite. Existing outbox payloads remain immutable. |
| API contracts | Retain `X-Requested-With: Tempo` in clients, worker, server, tests, and documentation. It is the CSRF contract, not visible branding. All endpoints unchanged. |
| OAuth | Keep credentials, redirect URIs, and external consent-screen configuration unchanged. UI refers to revoking “this app” because its Google console name is externally configured. |
| Deployment | Retain `tempo-api`, `tempo-reminders`, `tempo-db`, and Compose database names. No deployment performed. |
| Documentation | Product prose uses Xenon; operational command/configuration examples retain compatible names. |
| Test fixture | Existing `Tempo <reminders@example.com>` sender fixture remains: sender display names are configurable and the implementation must support existing settings. |
| Substring matches | `Temporal`, `@js-temporal/polyfill`, “temporarily”, and “Temporary” are unrelated and unchanged. |

No manifest was present. The existing favicon and browser metadata were updated without introducing a new PWA installation flow.

## Files changed

- `frontend/app/`: `globals.css`, `layout.tsx`, `page.tsx`, and `assistant/page.tsx`, `dashboard/page.tsx`, `tasks/page.tsx`, `calendar/page.tsx`, `reminders/page.tsx`, `settings/page.tsx`.
- `frontend/components/`: `auth-form.tsx`, `shell.tsx`, `ui.tsx`, `notification-settings.tsx`; new `xenon-mark.tsx` and `loading-state.tsx`.
- `frontend/lib/`: new `day-context.ts` and `reminder-labels.ts`.
- `frontend/public/`: `favicon.svg` and visible strings in `sw.js`.
- `frontend/tests/`: updated `voice.test.tsx` and `notifications.test.tsx`; added `brand-ux.test.tsx`, `settings-ux.test.tsx`, `brand-layout.cjs`.
- Backend branding only: `backend/app/main.py`, `backend/app/notifications/service.py`.
- Documentation/launcher: `README.md`, `docs/notifications.md`, `docs/verification.md`, `docs/voice-reminders.md`, this report, and `scripts/start-local.ps1`.

## Validation

Final results: **37 frontend tests passed**, **83 backend tests passed**, TypeScript passed, ESLint passed, Ruff passed, and the production Next.js build passed. All eight screens passed browser layout checks at three viewport widths (24 captures), with no browser runtime errors. The final authentication and notification layouts were visually inspected after corrections.

Existing non-failing notices: Vite's tsconfig-paths plugin deprecation, Starlette/httpx and AnyIO deprecations, and jsdom's unsupported full-document navigation notice. No production credentials or live-provider calls were used by these checks.

Run from `frontend`:

```powershell
npm test
npm run typecheck
npm run lint
npm run build
```

Run from `backend`:

```powershell
..\.runtime\python\python.exe -m pytest -q
..\.runtime\python\python.exe -m ruff check .
```

For layout checks, start the built frontend in one terminal, then run the browser check from another terminal, both in `frontend`:

```powershell
node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3211
node tests/brand-layout.cjs
```

The layout script uses installed Microsoft Edge through Playwright and intercepts all application API requests with test-only fixtures. It does not seed production or contact real providers. It visits eight screens at desktop (1440px), mobile (390px), and narrow mobile (320px), checks overflow/composer placement/navigation, and captures screenshots under `.runtime/xenon-ui` for visual review.

## Limits

- Dashboard data contains commitments and a capped priority list, not scheduler availability slots. No free-time totals or invented availability claims were added. Ask Xenon through the existing backend flow for scheduling availability.
- Live microphone hardware, live Google OAuth, live model calls, email delivery, and OS push delivery require deployment/device checks. Voice regression tests use browser API doubles.
- An externally configured email sender or Google consent-screen name can still say Tempo until the administrator changes it. Existing emails and conversations retain historical text.
- No commit, push, branch change, merge, migration, or production deployment was performed.
