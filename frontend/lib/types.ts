export type User = {
  id: number;
  name: string;
  email: string;
  email_verified_at?: string | null;
  email_reminders_opted_in_at?: string | null;
  verification_message?: string;
};
export type Task = {
  id: number;
  title: string;
  description: string;
  priority: string;
  estimated_duration_minutes: number;
  deadline: string | null;
  status: string;
};
export type Event = {
  id: number;
  title: string;
  description: string;
  start_time: string;
  end_time: string;
  event_type: string;
  source: string;
  is_recurring: boolean;
  meeting_metadata?: MeetingMetadata | null;
};
export type Attendee = { name: string; email?: string | null; response_status?: string };
export type Contact = { id: number; name: string; email: string };
export type MeetingMetadata = {
  all_day?: boolean;
  attendees: Attendee[];
  organizer?: { self?: boolean; email?: string };
  location?: string;
  meet_url?: string | null;
  calendar_url?: string | null;
  conference_status?: string | null;
};
export type MeetingDraft = {
  title: string;
  description: string;
  start_time: string;
  duration_minutes: number;
  attendees: Attendee[];
  location: string;
  google_meet: boolean;
};
export type MeetingReview = MeetingDraft & { end_time: string; timezone: string };
export type MeetingResult = {
  proposal: Proposal | null;
  message?: string;
  missing_contacts?: { name: string; reason: string }[];
  alternatives?: { start: string; end: string }[];
};
export type Session = {
  id: number;
  task_id: number;
  start_time: string;
  end_time: string;
  status: string;
};
export type Reminder = {
  id: number;
  task_id: number | null;
  scheduled_task_id: number | null;
  message: string;
  reminder_time: string;
  status: string;
  title: string;
  user_id: number;
  sent_at: string | null;
  read_at: string | null;
  dismissed_at: string | null;
  snoozed_until: string | null;
  generation: number;
};
export type Preferences = {
  reminder_stages: string[];
  in_app_notifications_enabled: boolean;
  timezone: string;
  preferred_start_time: string;
  preferred_end_time: string;
  preferred_days: number[];
  default_reminder_minutes: number;
  preferred_task_length: number;
  break_preference: number;
  allow_weekend_scheduling: boolean;
  personalization_enabled: boolean;
  browser_notifications_enabled: boolean;
  email_notifications_enabled: boolean;
  deadline_reminders_enabled: boolean;
};
export type Slot = { start: string; end: string; minutes: number; score: number };
export type Plan = {
  task_id: number;
  title: string;
  feasible: boolean;
  slots: Slot[];
  scheduled_minutes: number;
  unscheduled_minutes: number;
  explanation: string;
  proposal?: Proposal;
};
export type Proposal = {
  id: number;
  kind: string;
  status: string;
  expires_at: string;
  payload: {
    meeting?: MeetingReview;
    before?: { title: string; start_time: string; end_time: string; attendees: Attendee[] };
    name?: string;
    email?: string;
    plan?: Plan;
    plans?: Plan[];
    event_id?: number;
    event?: Event;
    reminder_id?: number;
    commitment_id?: number;
    task?: { title: string; deadline?: string | null; estimated_duration_minutes: number };
    review?: { action: string; title: string };
  } & Partial<Preferences>;
};
export type Action = { tool: string; ok: boolean; result: unknown };
export type Message = { id?: number; role: string; content: string; actions: Action[] };
export type Calendar = {
  events: Event[];
  sessions: Session[];
  reminders: Reminder[];
  timezone: string;
};
export type Dashboard = {
  tasks: Task[];
  events: Event[];
  sessions: Session[];
  reminders: Reminder[];
  summary: { total: number; active: number; completed: number; scheduled: number };
  timezone: string;
};

export type Integration = {
  id: string;
  name: string;
  configured: boolean;
  state: "connected" | "not_connected" | "needs_attention" | "coming_soon";
  synced_at?: string | null;
  account?: string | null;
  error?: string | null;
};
export type Commitment = {
  id: number;
  revision: number;
  title: string;
  type: string;
  source: "gmail";
  deadline: string | null;
  start_time: string | null;
  end_time: string | null;
  estimated_duration_minutes: number | null;
  confidence: number;
  reason: string;
  unresolved: string[];
  status: string;
  subject: string;
  sender: string;
  snippet: string;
  source_message_id: string;
  received_at: string | null;
};
export type CommitmentReview = {
  action: "task" | "event" | "schedule" | "dismiss";
  revision: number;
  title: string;
  deadline?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  estimated_duration_minutes?: number | null;
};
