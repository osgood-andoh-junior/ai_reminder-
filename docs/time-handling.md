# Current time and relative scheduling

`app.core.clock.utcnow()` is the server wall-clock source. `Application` captures
one aware UTC instant per API request; `chat()` refreshes it for every new chat
request, even if its caller reuses an application instance. Preferences supply
the authenticated user's IANA timezone. Never take the user's current date from
the model, chat history, an import-time constant, or a browser clock.

Every model call in a turn receives the same UTC instant, local date and time,
weekday, timezone, UTC offset, today/tomorrow dates, and server-resolved references
extracted from the current user message. The request snapshot also drives
availability searches, batch scheduling, reminders, dashboard day bounds, and
the external calendar search horizon. The scheduler remains a pure function of
explicit aware inputs. Database instants remain UTC; API datetimes require offsets.

Relative day arithmetic takes place in the user's timezone. Day windows run from
local midnight to the next local midnight, including 23/25-hour DST days. Elapsed
minutes/hours advance UTC instants. Ambiguous or nonexistent local clock times
are rejected; the user can provide an explicit offset. “Later today” searches
from the request instant until local midnight and needs a clock time for a fixed
event or reminder.

The agent may select a server-issued reference, but it cannot submit a computed
relative ISO timestamp. `time_window` restricts searches to a target day;
`deadline_reference` searches from now through the due day. Both availability
and proposal tools use the same adapter. Unsupported relative expressions require
clarification. Explicit absolute inputs and authenticated retrieved instants are
still supported. Proposals store resolved timestamps, not relative strings;
confirmation through the dedicated API rechecks current availability without
reinterpreting “tomorrow.”

The frontend synchronizes with authenticated, uncached `/api/time`, then advances
the sample using `performance.now()` elapsed time. It resynchronizes every minute
and on focus/visibility restoration, and refreshes day views on local date changes.
Device date changes do not determine today's date. Before the first successful
sample the UI shows a loading state; synchronization failures are visible.

Tests freeze `app.core.clock.utcnow` and cover September 29 → 30, local/UTC date
differences, midnight/year boundaries, DST, elapsed minutes, stale history,
availability/proposal agreement, and confirmation after midnight. No fixed test
dates are used by production paths.
