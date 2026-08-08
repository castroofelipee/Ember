export type Workspace = {
  id: string;
  name: string;
  role: "owner" | "member";
  created_at: string;
};

export type Calendar = {
  id: string;
  workspace_id: string;
  name: string;
  color: string;
  created_at: string;
};

/** Mirrors ember.models.calendar.DEFAULT_CALENDAR_COLOR. */
export const DEFAULT_CALENDAR_COLOR = "#4f46e5";

export type RecurrenceFreq = "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY";

/** Mirrors ember.schemas.events.RecurrenceRule. `by_weekday` is 0=Monday..6=Sunday
 * (weekly only); at most one of `count`/`until` is set, neither means "never ends". */
export type RecurrenceRule = {
  freq: RecurrenceFreq;
  interval: number;
  by_weekday: number[] | null;
  count: number | null;
  until: string | null;
};

export type EventItem = {
  id: string;
  calendar_id: string;
  title: string;
  description: string | null;
  location: string | null;
  start_at: string;
  end_at: string;
  all_day: boolean;
  color: string | null;
  attendees: string[];
  recurrence: RecurrenceRule | null;
};

export type PersonalItem = {
  id: string;
  kind: "reading" | "habit" | "vision";
  title: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

/** Habit schedule. "daily" = every day; number[] = weekdays 0=Mon..6=Sun,
 * matching RecurrenceRule.by_weekday. Legacy habits without a schedule are daily. */
export type HabitSchedule = "daily" | number[];

/** Shape stored in a habit PersonalItem's `data` JSONB. All fields except
 * `dates` are optional so pre-existing habits keep working. */
export type HabitData = {
  /** ISO YYYY-MM-DD completion dates. */
  dates: string[];
  schedule?: HabitSchedule;
  /** Per-habit accent hex; defaults to the violet system accent. */
  color?: string;
  /** Optional emoji glyph. */
  icon?: string;
  /** Optional motivation note. */
  description?: string;
};

export type EntityType =
  | "task"
  | "bug"
  | "idea"
  | "decision"
  | "rfc"
  | "event"
  | "meeting"
  | "email"
  | "customer_request"
  | "pr"
  | "incident"
  | "note"
  | "document";

export type ChecklistItem = {
  id: string;
  text: string;
  done: boolean;
};

export type Entity = {
  id: string;
  workspace_id: string;
  type: EntityType;
  title: string;
  content: string;
  properties: Record<string, unknown>;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeFolder = {
  id: string;
  workspace_id: string;
  parent_id: string | null;
  title: string;
  position: number;
  created_at: string;
  updated_at: string;
};

export type Relation = {
  id: string;
  workspace_id: string;
  from_entity_id: string;
  to_entity_id: string;
  relation_type: string;
  source: "manual" | "wiki_link" | "system";
  metadata: Record<string, unknown>;
  created_at: string;
};

export type RelatedEntity = {
  entity: Entity;
  relation: Relation;
  direction: "incoming" | "outgoing";
};

export type BoardColumn = {
  id: string;
  board_id: string;
  title: string;
  position: number;
  status_key: string | null;
};

export type BoardCard = {
  board_id: string;
  entity: Entity;
  column_id: string;
  position: number;
  created_at: string;
  updated_at: string;
};

export type Board = {
  id: string;
  workspace_id: string;
  title: string;
  description: string | null;
  label_options: string[];
  assignee_options: string[];
  /** Label name -> six-digit hex colour. Labels absent here use the default. */
  label_colors: Record<string, string>;
  created_at: string;
  updated_at: string;
  columns: BoardColumn[];
  cards: BoardCard[];
};

/** Whether this account has connected GitHub, and whether the server even
 * offers the integration (it is optional and off by default). */
export type GitHubStatus = {
  configured: boolean;
  connected: boolean;
  login: string | null;
  avatar_url: string | null;
  scopes: string | null;
  connected_at: string | null;
};

export type GitHubUser = {
  login: string;
  avatar_url: string | null;
  name: string | null;
};

/** `color` is six hex digits with no leading '#', as GitHub stores it. */
export type GitHubLabel = {
  name: string;
  color: string;
  description: string | null;
};

/** A repository the connected account can reach — an option in the picker. */
export type GitHubRepo = {
  id: number;
  owner: string;
  name: string;
  full_name: string;
  private: boolean;
  html_url: string;
  description: string | null;
  is_organization: boolean;
  open_issues_count: number;
  tracked: boolean;
};

/** A repository this workspace pulls issues from. */
export type GitHubTrackedRepo = {
  id: string;
  workspace_id: string;
  repo_id: number;
  owner: string;
  name: string;
  full_name: string;
  created_at: string;
};

/** Derived lane, not a GitHub field: GitHub issues are only open or closed, so
 * "in progress" means open *and* assigned (see services/github.py:issue_lane). */
export type GitHubLane = "open" | "in_progress" | "done";

export type GitHubIssue = {
  id: number;
  number: number;
  title: string;
  body: string | null;
  state: string;
  state_reason: string | null;
  html_url: string;
  lane: GitHubLane;
  assignees: GitHubUser[];
  labels: GitHubLabel[];
  comments: number;
  author: GitHubUser | null;
  milestone: string | null;
  repo_id: number;
  repo_full_name: string;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
};

/** One tracked repo that could not be read — surfaced per repo so a single
 * failure does not blank out the whole board. */
export type GitHubRepoError = {
  repo_id: number;
  full_name: string;
  message: string;
};

export type GitHubIssueList = {
  issues: GitHubIssue[];
  repo_errors: GitHubRepoError[];
};

/** Google-style named event colors. `value` is null for "calendar default". */
export const EVENT_COLORS = [
  { name: "Calendar default", value: null },
  { name: "Grape", value: "#7c3aed" },
  { name: "Flamingo", value: "#e11d48" },
  { name: "Tangerine", value: "#ea580c" },
  { name: "Banana", value: "#ca8a04" },
  { name: "Sage", value: "#16a34a" },
  { name: "Peacock", value: "#0891b2" },
  { name: "Blueberry", value: "#4f46e5" },
  { name: "Graphite", value: "#4b5563" },
] as const;

export type MailDomainStatus = "pending" | "active" | "disabled";

export type MailDomain = {
  id: string;
  workspace_id: string;
  domain: string;
  status: MailDomainStatus;
  stalwart_domain_id: string | null;
  provisioning_error: string | null;
  created_at: string;
};

export type MailAccountStatus = "active" | "suspended" | "disabled";

export type MailAccount = {
  id: string;
  workspace_id: string;
  domain_id: string;
  user_id: string | null;
  provider: "stalwart";
  provider_account_id: string;
  email: string;
  display_name: string | null;
  status: MailAccountStatus;
  created_at: string;
};

export type MailMessageSendResult = {
  email_id: string;
  submission_id: string;
};

export type MailFolder = "inbox" | "sent" | "drafts" | "archive" | "trash" | "junk";

export type MailAddress = {
  email: string;
  name: string | null;
};

export type MailMessageSummary = {
  account_id: string;
  account_email: string;
  id: string;
  thread_id: string;
  mailbox_ids: string[];
  keywords: string[];
  has_attachment: boolean;
  sender: MailAddress | null;
  subject: string;
  preview: string;
  received_at: string;
  size: number;
};

export type MailMessageDetail = MailMessageSummary & {
  to: MailAddress[];
  cc: MailAddress[];
  bcc: MailAddress[];
  reply_to: MailAddress[];
  text_body: string;
  html_body: string;
};

export type MailThreadPreview = {
  account_id: string;
  account_email: string;
  thread_id: string;
  subject: string;
  preview: string;
  participants: MailAddress[];
  latest_message: MailMessageSummary;
  message_count: number;
  unread_count: number;
  has_attachment: boolean;
  received_at: string;
};

export type MailThread = {
  account_id: string;
  account_email: string;
  thread_id: string;
  messages: MailMessageDetail[];
};

export type MailThreadPage = {
  items: MailThreadPreview[];
  has_more: boolean;
};

export type MailMarkReadResult = {
  marked: number;
};

export type TimeFormat = "12h" | "24h";

export type Preferences = {
  locale: string;
  timezone: string;
  /** 0 = Sunday .. 6 = Saturday. */
  week_starts_on: number;
  /** Whole-hour bounds [start, end) shaded as working time in the calendar. */
  work_day_start: number;
  work_day_end: number;
  time_format: TimeFormat;
};

export type HolidaySettings = {
  enabled: boolean;
  provider: "calendarific" | "openholidays";
  country: string;
  region: string;
  city: string;
  calendar_id: string | null;
  synced_events: number;
};

export const DEFAULT_HOLIDAY_SETTINGS: HolidaySettings = {
  enabled: false,
  provider: "openholidays",
  country: "BR",
  region: "",
  city: "",
  calendar_id: null,
  synced_events: 0,
};

export const DEFAULT_PREFERENCES: Preferences = {
  locale: "en-US",
  timezone: "UTC",
  week_starts_on: 0,
  work_day_start: 9,
  work_day_end: 17,
  time_format: "12h",
};
