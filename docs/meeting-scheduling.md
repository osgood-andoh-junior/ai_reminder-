# Meeting scheduling

Xenon does not access attendees' calendars. External attendees participate through Google Calendar invitations.

## Architecture and confirmation

Both the Calendar meeting editor and allowlisted agent tools call `app/services/meetings.py`. It is bound to the authenticated `Application`, reuses `GoogleCalendarService` and existing encrypted OAuth credentials, and reads only `/calendar/v3/calendars/primary/events`. There is no attendee calendar lookup, free/busy endpoint, sharing request, attendee OAuth flow, Resend invitation, or separate invitation-email service.

The existing `TimeContext` and `TimeArguments` resolve relative dates with the authoritative server clock and the user's timezone. Meeting start timestamps require an explicit offset at HTTP boundaries. Application code calculates the end from duration and stores UTC instants. `meeting_slots` lives in the deterministic scheduler and finds contiguous slots within a bounded search window using the organizer's events and scheduled task sessions. These are available times for the organizer only, never a statement about attendee availability.

Creation and edits refresh Google before checking conflicts. A conflict returns alternatives without a final proposal. Missing/ambiguous contact names return questions instead of guessing emails. A recent unfinished agent request can be resumed from its user-owned, validated chat action for 30 minutes, preserving the originally resolved timestamp when the user supplies an email. Fresh relative-date requests still use the current server context.

The agent registry also rejects explicit email arguments unless the exact address appeared in recent user messages or an authenticated tool result. Name-only arguments can be resolved by the contact service. Email syntax is independently validated by the application schemas.

Invitations, adding/removing attendees (including the final attendee), changing time/title/description/location, and cancellation are persisted in the existing `proposals` table. New kinds are `meeting_create`, `meeting_update`, `meeting_cancel`, and `save_contact`. They expire after 30 minutes, require the existing authenticated `POST /api/proposals/{id}/decision` endpoint, and cannot be executed by any model flag or confirmation tool. Editing the UI review creates a new proposal and rejects the superseded review. The original proposal remains authoritative until rejection succeeds.

Confirmation takes the existing per-user database lock, refreshes availability, checks organizer permissions and the remote ETag, then calls Google. Patches/deletes use `If-Match`; stale changes require a fresh review. Calendar changes made by another external client after the final availability fetch cannot be reserved atomically with a Google mutation. There is no distributed transaction with Google.

## Google invitations, Meet and retries

- Insert/PATCH use `sendUpdates=all` and `conferenceDataVersion=1`. DELETE uses `sendUpdates=all`. Google manages invitations, updates, cancellations and Yes/Maybe/No responses. API success means Google accepted the event operation, not that an invitation was delivered or accepted.
- New events use a stable SHA-256 event ID derived from the authenticated user, persisted proposal and a server-generated UUID stored in that proposal. This also separates independent Xenon installations. Conference `createRequest.requestId` uses the same unique operation key and `conferenceSolutionKey.type=hangoutsMeet`.
- A private event property records the applied mutation. Retrying a proposal after remote success but local failure reads the organizer event and recovers it without resending the same mutation. Updates retain the remote event ID; they never create a replacement event. Repeated accepted decisions are rejected by the existing proposal lifecycle.
- Existing conference data is preserved with PATCH. Only links returned by Google are displayed. A pending conference shows a pending state; a failed conference leaves the successful event intact and offers opening Google Calendar to add a link. The frontend does not fabricate URLs.
- Cancellation of an event already removed in Google reconciles the local row and reports that it was already cancelled; it does not claim a new cancellation notification was delivered.
- Network/provider errors keep the proposal pending and return sanitized error text. A retry within the proposal lifetime is safe using the same proposal. If the proposal expires after an uncertain network result, sync/search Google before making another proposal.

Google references: [event creation and notifications](https://developers.google.com/workspace/calendar/api/guides/create-events), [events.insert and conference parameters](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert), [ETag conditional mutations](https://developers.google.com/calendar/api/guides/version-resources).

## Contacts and RSVP

`Contact` is owned by `user_id`, with name, normalized email and timestamps. A unique `(user_id, email)` constraint prevents duplicate addresses. Exact, case-insensitive names resolve only if unambiguous. Contact saves require a review; sending an invitation never silently saves a contact. Users can review and delete contacts in Settings. Deleting a contact does not alter any invitation or meeting.

The nullable `CalendarEvent.meeting_metadata` JSON stores organizer-event attendees, response status, organizer, location, conference data/status, returned links and ETag. Existing sync refreshes this metadata. Calendar's **Refresh responses** and the agent's `get_meeting` fetch the organizer's event on demand; there is no polling loop. Display labels map accepted/tentative/declined/needsAction to Accepted/Tentative/Declined/Awaiting response. RSVP is not an availability signal.

## API and tools

All routes require the existing authentication and mutation CSRF protection. IDs are local, user-owned IDs; external IDs are resolved on the server.

| Method | Endpoint | Behavior |
|---|---|---|
| GET | `/api/contacts?query=` | Review/search own contacts |
| POST | `/api/contacts/propose` | Propose saving a contact |
| DELETE | `/api/contacts/{id}` | Explicit manual contact deletion |
| GET | `/api/meetings?query=` | Refresh/search primary calendar; signal multiple matches |
| GET | `/api/meetings/{id}` | Refresh the owned event and RSVP metadata |
| POST | `/api/meetings/availability` | Organizer slots for start/end/duration |
| POST | `/api/meetings/propose` | Validate and propose an invitation |
| POST | `/api/meetings/{id}/propose` | Propose a complete edited meeting |
| POST | `/api/meetings/{id}/cancel` | Propose cancellation |
| POST | `/api/proposals/{id}/decision` | Existing dedicated confirmation API, extended to meetings/contacts |

Agent tools: `find_contact`, `save_contact`, `get_pending_meeting_request`, `find_meetings`, `get_meeting`, `find_my_availability`, `propose_meeting`, `reschedule_meeting`, `cancel_meeting`. Creation is intentionally a proposal-only tool. Existing event tools still cannot directly modify imported Google events. Multiple matches require selection; the agent must retrieve an ID before using it.

## Migration and deployment

Alembic `a12e93b4` follows the already-local integration migration `f81a2c90`. It adds `contacts` and nullable `calendar_events.meeting_metadata`. No token tables, encryption keys, existing events or existing proposals are rewritten. Upgrade/downgrade are SQLite/PostgreSQL-compatible. Include the existing uncommitted integration migration when deploying this working tree.

From `backend`, with the project's Python dependencies installed:

```powershell
python -m alembic upgrade head
```

No new environment variables or dependencies are required, so `.env.example` does not change. Do not rotate `TOKEN_ENCRYPTION_KEY` when deploying.

### Google Cloud Console

For an already-working Calendar integration: no Console change is required. The existing scope is `https://www.googleapis.com/auth/calendar.events`; it authorizes event reads, inserts, updates, deletes, attendees and conference data. No scope is added. Gmail's separately configured integration/scopes are unchanged.

For a new setup: enable **Google Calendar API** in the existing project; configure the OAuth consent screen with `calendar.events`; use an OAuth **Web application** client and register the exact callback `http://localhost:3000/api/calendar/google/callback` locally or `https://YOUR_FRONTEND/api/calendar/google/callback` in production. If the consent app is in Testing, add the organizer's Google account as a test user. External invitees do not need OAuth access or to be consent-screen test users. The organizer's Google/Workspace account must permit Meet creation; administrator restrictions may prevent it. You do not need a Google Meet API enablement or a free/busy scope.

### Render and Vercel

Render: keep existing `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `TOKEN_ENCRYPTION_KEY`, `DATABASE_URL`, `FRONTEND_URL`, authentication and optional AI settings. The existing `render.yaml` pre-deploy command runs `python -m alembic upgrade head`. Verify it runs successfully before serving the new code. No reminder worker, Resend or extra service is needed for invitations.

Vercel: no new variables. Preserve the server-side `BACKEND_URL` rewrite and existing HTTPS frontend origin/callback configuration. Never put Google OAuth secrets in `NEXT_PUBLIC_*`. Redeploy the frontend with the new UI after the backend migration.

## Tests and real-attendee checklist

Automated meeting tests mock Google; they never send real invitations. The transport fixture asserts that every calendar request targets the primary event collection/resource and rejects free/busy and attendee-calendar URLs. Backend tests cover contacts/ownership, confirmation, multiple attendees, conflict checks, time references/timezones, Google Meet, retries, rescheduling/cancellation, RSVP, ambiguity, API/token errors and user isolation. Frontend tests cover proposals, editing, notifications/cancellation, multiple attendees, Meet, missing emails, RSVP, loading/errors and contacts. Existing migration tests upgrade through head, check schema equivalence, downgrade/re-upgrade SQLite and generate PostgreSQL SQL.

```powershell
# From backend
python -m pytest -q
python -m ruff check .
# From frontend
npm test
npm run lint
npm run typecheck
npm run build
```

Before testing with a real attendee:

1. Back up your database, apply migrations, and restart backend/frontend. Set the organizer's timezone in Settings.
2. Connect Google Calendar in Settings and sync it. Reconnect only if credentials are expired/revoked or the existing Calendar permission is missing.
3. Choose an attendee address you are authorized to invite. Use Calendar → **New meeting**, or ask the assistant for a timed meeting (AI needs the selected backend provider configuration; see [AI providers](ai-providers.md)).
4. Supply missing emails and duration. Enable Google Meet if wanted. Check the organizer time, timezone, attendee addresses and proposed notifications.
5. Click **Confirm & Send**. Verify the event in the organizer's primary Google Calendar and the invitation received by the attendee. No invitation should exist before this click.
6. Have the attendee RSVP, then click **Refresh responses** or sync. Check the returned Meet link, including a possible pending state.
7. Test a time change and cancellation with their respective confirmation cards and verify Google's update/cancellation notifications.

## Limitations

- Primary calendar only; no attendee availability, other calendars, shared-calendar organizer delegation, or automatic time negotiation.
- Meeting creation/availability is bounded to 89 days, inside the existing 90-day synchronization horizon. Durations are 5–1440 minutes; at most 100 attendees. Suggested slots use a 15-minute grid, stay contiguous and may include evenings/weekends when the requested window permits them; task-splitting preferences are not applied to meetings.
- Recurring and all-day meeting mutations must be made in Google Calendar. Existing recurring/all-day synchronization remains supported.
- Existing conference links are preserved. Conference removal/retry after Google's failure is handled in Google Calendar.
- Attendee response synchronization is on demand/existing sync; no push subscription or aggressive polling. Google and recipient settings control invitation delivery and visibility.
- No real Google invitation or live-model end-to-end test is performed by the automated suite. There is no atomic reservation against concurrent external calendar changes.
- Chat clarifications retain validated meeting intent for 30 minutes; older requests require fresh details. Confirmation expiry still applies after a remote timeout.
