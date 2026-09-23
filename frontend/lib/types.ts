export type User = { id: number; name: string; email: string };
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
    plan?: Plan;
    plans?: Plan[];
    event_id?: number;
    event?: Event;
    reminder_id?: number;
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
