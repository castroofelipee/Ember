"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type DragEvent,
  type SubmitEvent,
} from "react";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CircleDot,
  ExternalLink,
  GitBranch,
  Loader2,
  MessageSquare,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
  X,
} from "lucide-react";

import { apiFetch, useRequireAuth } from "@/lib/auth-client";
import type {
  GitHubIssue,
  GitHubIssueList,
  GitHubLabel,
  GitHubLane,
  GitHubRepo,
  GitHubStatus,
  GitHubTrackedRepo,
  GitHubUser,
} from "@/lib/types";

type LaneDefinition = {
  key: GitHubLane;
  title: string;
  /** Shown as a tooltip: these lanes are Ember's derivation, not GitHub state. */
  hint: string;
};

// GitHub tracks only open/closed. The middle lane is Ember's reading of
// "someone has picked this up", and says so rather than implying otherwise.
const LANES: LaneDefinition[] = [
  { key: "open", title: "Open", hint: "Open issues with nobody assigned yet." },
  {
    key: "in_progress",
    title: "In progress",
    hint: "Open issues with at least one assignee. GitHub has no in-progress state — Ember derives this from assignment.",
  },
  { key: "done", title: "Done", hint: "Closed issues." },
];

async function responseError(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      const details = (body.detail as unknown[])
        .map((item: unknown) => {
          if (!item || typeof item !== "object") return null;
          const candidate = item as { loc?: unknown[]; msg?: unknown };
          const message = typeof candidate.msg === "string" ? candidate.msg : null;
          const location = Array.isArray(candidate.loc) ? candidate.loc.join(".") : null;
          return message ? `${location ? `${location}: ` : ""}${message}` : null;
        })
        .filter(Boolean)
        .join("; ");
      if (details) return details;
    }
  } catch {
    return fallback;
  }
  return fallback;
}

async function jsonRequest<T>(input: string, init: RequestInit, fallback: string): Promise<T> {
  const response = await apiFetch(input, init);
  if (!response.ok) throw new Error(await responseError(response, fallback));
  return (await response.json()) as T;
}

/** Perceived-luminance pick between black and white text, so a label stays
 * readable on both GitHub's pale yellows and its dark reds. Same rule the
 * boards view uses for its own label chips. */
function labelTextColor(hex: string): string {
  const value = hex.replace("#", "");
  if (value.length !== 6) return "#0b1220";
  const r = parseInt(value.slice(0, 2), 16) / 255;
  const g = parseInt(value.slice(2, 4), 16) / 255;
  const b = parseInt(value.slice(4, 6), 16) / 255;
  const channel = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  return luminance > 0.5 ? "#0b1220" : "#ffffff";
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((Date.now() - then) / 1000);
  const units: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.35, "week"],
    [12, "month"],
  ];

  let value = seconds;
  let unit: Intl.RelativeTimeFormatUnit = "second";
  for (const [size, nextUnit] of units) {
    if (Math.abs(value) < size) break;
    value = Math.round(value / size);
    unit = nextUnit;
  }
  return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(-value, unit);
}

export function GitHubView() {
  const { status: authStatus } = useRequireAuth();
  const router = useRouter();
  const params = useParams<{ workspaceId: string }>();
  const workspaceId = params?.workspaceId ?? "";

  const [connection, setConnection] = useState<GitHubStatus | null>(null);
  const [trackedRepos, setTrackedRepos] = useState<GitHubTrackedRepo[]>([]);
  const [issues, setIssues] = useState<GitHubIssue[]>([]);
  const [repoErrors, setRepoErrors] = useState<GitHubIssueList["repo_errors"]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [showClosed, setShowClosed] = useState(false);
  const [selectedRepoIds, setSelectedRepoIds] = useState<number[]>([]);
  const [query, setQuery] = useState("");

  const [pickerOpen, setPickerOpen] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [movingIssueKey, setMovingIssueKey] = useState<string | null>(null);
  const [assigneePrompt, setAssigneePrompt] = useState<{
    issue: GitHubIssue;
    options: GitHubUser[];
    loading: boolean;
  } | null>(null);

  const loadConnection = useCallback(async () => {
    const status = await jsonRequest<GitHubStatus>(
      "/api/integrations/github/status",
      {},
      "Could not read the GitHub connection.",
    );
    setConnection(status);
    return status;
  }, []);

  const loadTrackedRepos = useCallback(async () => {
    if (!workspaceId) return [];
    const repos = await jsonRequest<GitHubTrackedRepo[]>(
      `/api/workspaces/${workspaceId}/github/repos`,
      {},
      "Could not load tracked repositories.",
    );
    setTrackedRepos(repos);
    return repos;
  }, [workspaceId]);

  const loadIssues = useCallback(async () => {
    if (!workspaceId) return;
    const search = new URLSearchParams({ state: showClosed ? "all" : "open" });
    for (const repoId of selectedRepoIds) search.append("repo_id", String(repoId));

    const body = await jsonRequest<GitHubIssueList>(
      `/api/workspaces/${workspaceId}/github/issues?${search.toString()}`,
      {},
      "Could not load issues from GitHub.",
    );
    setIssues(body.issues);
    setRepoErrors(body.repo_errors);
  }, [workspaceId, showClosed, selectedRepoIds]);

  // Initial load. The tracked-repo list decides whether an issue fetch is even
  // worth making, so these run in sequence rather than in parallel.
  useEffect(() => {
    if (authStatus !== "ready" || !workspaceId) return;
    let cancelled = false;

    (async () => {
      setLoading(true);
      try {
        const status = await loadConnection();
        if (cancelled) return;
        if (!status.connected) return;

        const repos = await loadTrackedRepos();
        if (cancelled || repos.length === 0) return;
        await loadIssues();
      } catch (error) {
        if (!cancelled) setErrorMessage((error as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // loadIssues intentionally omitted: filter changes are handled below, and
    // including it here would re-run the whole bootstrap on every toggle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus, workspaceId, loadConnection, loadTrackedRepos]);

  // Filter changes refetch issues only.
  useEffect(() => {
    if (authStatus !== "ready" || loading) return;
    if (!connection?.connected || trackedRepos.length === 0) return;
    let cancelled = false;

    (async () => {
      setRefreshing(true);
      try {
        await loadIssues();
      } catch (error) {
        if (!cancelled) setErrorMessage((error as Error).message);
      } finally {
        if (!cancelled) setRefreshing(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showClosed, selectedRepoIds]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setErrorMessage(null);
    try {
      await loadTrackedRepos();
      await loadIssues();
    } catch (error) {
      setErrorMessage((error as Error).message);
    } finally {
      setRefreshing(false);
    }
  }, [loadTrackedRepos, loadIssues]);

  async function connect() {
    try {
      const body = await jsonRequest<{ url: string }>(
        "/api/integrations/github/authorize",
        {},
        "Could not start the GitHub connection.",
      );
      // A full navigation, not a fetch: the user has to approve on github.com.
      window.location.assign(body.url);
    } catch (error) {
      setErrorMessage((error as Error).message);
    }
  }

  async function untrackRepo(repoId: number) {
    try {
      const response = await apiFetch(
        `/api/workspaces/${workspaceId}/github/repos/${repoId}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error(await responseError(response, "Could not untrack."));
      setSelectedRepoIds((ids) => ids.filter((id) => id !== repoId));
      await refresh();
    } catch (error) {
      setErrorMessage((error as Error).message);
    }
  }

  const issueKey = (issue: GitHubIssue) => `${issue.repo_id}-${issue.id}`;

  async function persistMove(issue: GitHubIssue, lane: GitHubLane, assignees: string[]) {
    if (issue.lane === lane || movingIssueKey === issueKey(issue)) return;
    const before = issues;
    const optimistic: GitHubIssue = {
      ...issue,
      lane,
      state: lane === "done" ? "closed" : "open",
      assignees:
        lane === "open"
          ? []
          : assignees.map(
              (login) => issue.assignees.find((user) => user.login === login) ?? {
                login,
                avatar_url: null,
                name: null,
              },
            ),
    };
    setMovingIssueKey(issueKey(issue));
    setIssues((current) => current.map((candidate) => issueKey(candidate) === issueKey(issue) ? optimistic : candidate));
    setErrorMessage(null);
    try {
      const updated = await jsonRequest<GitHubIssue>(
        `/api/workspaces/${workspaceId}/github/issues/${issue.repo_id}/${issue.number}`,
        { method: "PATCH", body: JSON.stringify({ lane, assignees }) },
        "Could not move the issue.",
      );
      setIssues((current) => current.map((candidate) => issueKey(candidate) === issueKey(issue) ? updated : candidate));
    } catch (error) {
      setIssues(before);
      setErrorMessage((error as Error).message);
    } finally {
      setMovingIssueKey(null);
    }
  }

  async function requestMove(issue: GitHubIssue, lane: GitHubLane) {
    if (issue.lane === lane) return;
    if (lane !== "in_progress" || issue.assignees.length > 0) {
      await persistMove(issue, lane, issue.assignees.map((user) => user.login));
      return;
    }

    setAssigneePrompt({ issue, options: [], loading: true });
    try {
      const options = await jsonRequest<GitHubUser[]>(
        `/api/workspaces/${workspaceId}/github/repos/${issue.repo_id}/assignees`,
        {},
        "Could not list repository assignees.",
      );
      setAssigneePrompt({ issue, options, loading: false });
    } catch (error) {
      setAssigneePrompt(null);
      setErrorMessage((error as Error).message);
    }
  }

  const visibleIssues = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return issues;
    return issues.filter(
      (issue) =>
        issue.title.toLowerCase().includes(needle) ||
        issue.repo_full_name.toLowerCase().includes(needle) ||
        String(issue.number).includes(needle) ||
        issue.assignees.some((user) => user.login.toLowerCase().includes(needle)) ||
        issue.labels.some((label) => label.name.toLowerCase().includes(needle)),
    );
  }, [issues, query]);

  const issuesByLane = useMemo(() => {
    const grouped: Record<GitHubLane, GitHubIssue[]> = {
      open: [],
      in_progress: [],
      done: [],
    };
    for (const issue of visibleIssues) grouped[issue.lane]?.push(issue);
    return grouped;
  }, [visibleIssues]);

  if (authStatus !== "ready") {
    return (
      <div className="github-page github-page--centered">
        <Loader2 className="github-spinner" size={22} />
      </div>
    );
  }

  return (
    <div className="github-page">
      <header className="github-toolbar">
        <div className="github-toolbar-leading">
          <button
            type="button"
            className="github-icon-button"
            aria-label="Back to workspace"
            onClick={() => router.push(`/workspace/${workspaceId}`)}
          >
            <ArrowLeft size={18} />
          </button>
          <GitBranch size={20} />
          <h1 className="github-title">GitHub issues</h1>
          {refreshing && <Loader2 className="github-spinner" size={16} />}
        </div>

        {connection?.connected && (
          <div className="github-toolbar-actions">
            <div className="github-search">
              <Search size={15} />
              <input
                type="search"
                className="github-search-input"
                placeholder="Filter issues"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <label className="github-toggle">
              <input
                type="checkbox"
                checked={showClosed}
                onChange={(event) => setShowClosed(event.target.checked)}
              />
              <span>Show closed</span>
            </label>
            <button
              type="button"
              className="github-icon-button"
              aria-label="Refresh"
              onClick={refresh}
            >
              <RefreshCw size={16} />
            </button>
            <button
              type="button"
              className="github-secondary-button"
              onClick={() => setPickerOpen(true)}
            >
              <Settings2 size={15} />
              Repositories
            </button>
            <button
              type="button"
              className="github-primary-button"
              onClick={() => setComposerOpen(true)}
              disabled={trackedRepos.length === 0}
            >
              <Plus size={15} />
              New issue
            </button>
          </div>
        )}
      </header>

      {errorMessage && (
        <div className="github-banner github-banner--error">
          <AlertTriangle size={16} />
          <span>{errorMessage}</span>
          <button type="button" onClick={() => setErrorMessage(null)} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      )}

      {repoErrors.length > 0 && (
        <div className="github-banner github-banner--warning">
          <AlertTriangle size={16} />
          <span>
            Could not read{" "}
            {repoErrors.map((failure) => `${failure.full_name} (${failure.message})`).join(", ")}
          </span>
          <button type="button" onClick={() => setRepoErrors([])} aria-label="Dismiss">
            <X size={14} />
          </button>
        </div>
      )}

      {loading ? (
        <div className="github-page--centered">
          <Loader2 className="github-spinner" size={22} />
        </div>
      ) : !connection?.connected ? (
        <ConnectPrompt configured={connection?.configured ?? false} onConnect={connect} />
      ) : trackedRepos.length === 0 ? (
        <EmptyRepos onPick={() => setPickerOpen(true)} />
      ) : (
        <>
          <RepoFilterBar
            repos={trackedRepos}
            selected={selectedRepoIds}
            onToggle={(repoId) =>
              setSelectedRepoIds((ids) =>
                ids.includes(repoId) ? ids.filter((id) => id !== repoId) : [...ids, repoId],
              )
            }
            onClear={() => setSelectedRepoIds([])}
          />
          <div className="github-lanes">
            {LANES.map((lane) => (
              <Lane
                key={lane.key}
                lane={lane}
                issues={issuesByLane[lane.key]}
                movingIssueKey={movingIssueKey}
                onMove={requestMove}
              />
            ))}
          </div>
        </>
      )}

      {pickerOpen && (
        <RepoPicker
          workspaceId={workspaceId}
          trackedRepos={trackedRepos}
          onClose={() => setPickerOpen(false)}
          onChanged={refresh}
          onUntrack={untrackRepo}
        />
      )}

      {composerOpen && (
        <IssueComposer
          workspaceId={workspaceId}
          repos={trackedRepos}
          onClose={() => setComposerOpen(false)}
          onCreated={refresh}
        />
      )}

      {assigneePrompt && (
        <AssigneePrompt
          prompt={assigneePrompt}
          suggestedLogin={connection?.login ?? null}
          onCancel={() => setAssigneePrompt(null)}
          onSelect={(login) => {
            const issue = assigneePrompt.issue;
            setAssigneePrompt(null);
            void persistMove(issue, "in_progress", [login]);
          }}
        />
      )}
    </div>
  );
}

function ConnectPrompt({
  configured,
  onConnect,
}: {
  configured: boolean;
  onConnect: () => void;
}) {
  return (
    <div className="github-empty">
      <GitBranch size={40} />
      <h2>Connect GitHub</h2>
      {configured ? (
        <>
          <p>
            See issues from your personal and organization repositories here, and file new ones
            without leaving Ember.
          </p>
          <button type="button" className="github-primary-button" onClick={onConnect}>
            <GitBranch size={16} />
            Connect GitHub
          </button>
          <p className="github-empty-note">
            Ember reads and creates issues. Moving cards updates assignment and status on GitHub.
          </p>
        </>
      ) : (
        <p>
          This server has no GitHub OAuth App configured. Set <code>GITHUB_OAUTH_CLIENT_ID</code>,{" "}
          <code>GITHUB_OAUTH_CLIENT_SECRET</code> and <code>GITHUB_TOKEN_ENCRYPTION_KEY</code>, then
          restart the API.
        </p>
      )}
    </div>
  );
}

function EmptyRepos({ onPick }: { onPick: () => void }) {
  return (
    <div className="github-empty">
      <CircleDot size={40} />
      <h2>No repositories tracked yet</h2>
      <p>Pick the repositories this workspace should pull issues from.</p>
      <button type="button" className="github-primary-button" onClick={onPick}>
        <Settings2 size={16} />
        Choose repositories
      </button>
    </div>
  );
}

function RepoFilterBar({
  repos,
  selected,
  onToggle,
  onClear,
}: {
  repos: GitHubTrackedRepo[];
  selected: number[];
  onToggle: (repoId: number) => void;
  onClear: () => void;
}) {
  return (
    <div className="github-repo-filter">
      <button
        type="button"
        className={`github-chip${selected.length === 0 ? " github-chip--on" : ""}`}
        onClick={onClear}
      >
        All repositories
      </button>
      {repos.map((repo) => (
        <button
          key={repo.repo_id}
          type="button"
          className={`github-chip${selected.includes(repo.repo_id) ? " github-chip--on" : ""}`}
          onClick={() => onToggle(repo.repo_id)}
        >
          {repo.full_name}
        </button>
      ))}
    </div>
  );
}

function Lane({
  lane,
  issues,
  movingIssueKey,
  onMove,
}: {
  lane: LaneDefinition;
  issues: GitHubIssue[];
  movingIssueKey: string | null;
  onMove: (issue: GitHubIssue, lane: GitHubLane) => void;
}) {
  const [dragOver, setDragOver] = useState(false);

  function acceptDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragOver(false);
    try {
      const issue = JSON.parse(event.dataTransfer.getData("application/json")) as GitHubIssue;
      onMove(issue, lane.key);
    } catch {
      // Ignore unrelated drags entering the board.
    }
  }

  return (
    <section
      className={`github-lane${dragOver ? " github-lane--drop-target" : ""}`}
      onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragOver(false);
      }}
      onDrop={acceptDrop}
    >
      <header className="github-lane-header" title={lane.hint}>
        <h2>{lane.title}</h2>
        <span className="github-lane-count">{issues.length}</span>
      </header>
      <div className="github-lane-body">
        {issues.length === 0 ? (
          <p className="github-lane-empty">Nothing here.</p>
        ) : (
          issues.map((issue) => (
            <IssueCard
              key={`${issue.repo_id}-${issue.id}`}
              issue={issue}
              moving={movingIssueKey === `${issue.repo_id}-${issue.id}`}
              onMove={onMove}
            />
          ))
        )}
      </div>
    </section>
  );
}

function IssueCard({
  issue,
  moving,
  onMove,
}: {
  issue: GitHubIssue;
  moving: boolean;
  onMove: (issue: GitHubIssue, lane: GitHubLane) => void;
}) {
  return (
    <article
      className={`github-card${moving ? " github-card--moving" : ""}`}
      draggable={!moving}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("application/json", JSON.stringify(issue));
      }}
    >
      <div className="github-card-top">
        <span className="github-card-repo">{issue.repo_full_name}</span>
        <a
          href={issue.html_url}
          target="_blank"
          rel="noreferrer noopener"
          className="github-card-link"
          aria-label={`Open issue #${issue.number} on GitHub`}
        >
          <ExternalLink size={13} />
        </a>
      </div>

      <h3 className="github-card-title">
        <span className="github-card-number">#{issue.number}</span> {issue.title}
      </h3>

      {issue.labels.length > 0 && (
        <div className="github-card-labels">
          {issue.labels.map((label) => (
            <LabelChip key={label.name} label={label} />
          ))}
        </div>
      )}

      <footer className="github-card-footer">
        <div className="github-card-assignees">
          {issue.assignees.length === 0 ? (
            <span className="github-card-unassigned">Unassigned</span>
          ) : (
            issue.assignees.map((user) => <Avatar key={user.login} user={user} />)
          )}
        </div>
        <div className="github-card-meta">
          {issue.comments > 0 && (
            <span className="github-card-comments">
              <MessageSquare size={12} /> {issue.comments}
            </span>
          )}
          <time dateTime={issue.updated_at}>{relativeTime(issue.updated_at)}</time>
        </div>
      </footer>
      <label className="github-card-move">
        <span className="sr-only">Move issue #{issue.number}</span>
        <select
          value={issue.lane}
          disabled={moving}
          onChange={(event) => onMove(issue, event.target.value as GitHubLane)}
          aria-label={`Move issue #${issue.number}`}
        >
          {LANES.map((lane) => <option key={lane.key} value={lane.key}>{lane.title}</option>)}
        </select>
      </label>
    </article>
  );
}

function AssigneePrompt({
  prompt,
  suggestedLogin,
  onCancel,
  onSelect,
}: {
  prompt: { issue: GitHubIssue; options: GitHubUser[]; loading: boolean };
  suggestedLogin: string | null;
  onCancel: () => void;
  onSelect: (login: string) => void;
}) {
  const options = [...prompt.options].sort((a, b) => {
    if (a.login === suggestedLogin) return -1;
    if (b.login === suggestedLogin) return 1;
    return a.login.localeCompare(b.login);
  });
  return (
    <div className="github-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="github-assignee-title">
      <div className="github-modal github-assignee-modal">
        <header className="github-modal-header">
          <div>
            <h2 id="github-assignee-title">Assign before starting</h2>
            <p>Choose who is taking issue #{prompt.issue.number}.</p>
          </div>
          <button type="button" className="github-icon-button" onClick={onCancel} aria-label="Cancel"><X size={16} /></button>
        </header>
        <div className="github-modal-body">
          {prompt.loading ? (
            <div className="github-page--centered"><Loader2 className="github-spinner" size={20} /></div>
          ) : options.length === 0 ? (
            <p className="github-lane-empty">No assignable users were returned by GitHub.</p>
          ) : (
            <div className="github-assignee-options">
              {options.map((user) => (
                <button key={user.login} type="button" onClick={() => onSelect(user.login)}>
                  <Avatar user={user} />
                  <span>{user.name || user.login}</span>
                  <small>@{user.login}{user.login === suggestedLogin ? " · You" : ""}</small>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function LabelChip({ label }: { label: GitHubLabel }) {
  const background = `#${label.color}`;
  return (
    <span
      className="github-label"
      style={{ background, color: labelTextColor(label.color) }}
      title={label.description ?? label.name}
    >
      {label.name}
    </span>
  );
}

function Avatar({ user }: { user: GitHubUser }) {
  if (user.avatar_url) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        className="github-avatar"
        src={user.avatar_url}
        alt={user.login}
        title={user.name ?? user.login}
        width={22}
        height={22}
      />
    );
  }
  return (
    <span className="github-avatar github-avatar--initials" title={user.login}>
      {user.login.slice(0, 2).toUpperCase()}
    </span>
  );
}

function RepoPicker({
  workspaceId,
  trackedRepos,
  onClose,
  onChanged,
  onUntrack,
}: {
  workspaceId: string;
  trackedRepos: GitHubTrackedRepo[];
  onClose: () => void;
  onChanged: () => Promise<void>;
  onUntrack: (repoId: number) => Promise<void>;
}) {
  const [repos, setRepos] = useState<GitHubRepo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const body = await jsonRequest<GitHubRepo[]>(
          `/api/integrations/github/repos?workspace_id=${workspaceId}`,
          {},
          "Could not list your GitHub repositories.",
        );
        if (!cancelled) setRepos(body);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const trackedIds = useMemo(
    () => new Set(trackedRepos.map((repo) => repo.repo_id)),
    [trackedRepos],
  );

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const filtered = needle
      ? repos.filter((repo) => repo.full_name.toLowerCase().includes(needle))
      : repos;
    // Organization repositories first — they are usually the shared work, and
    // are the harder ones to find in a long personal list.
    return [...filtered].sort((a, b) => {
      if (a.is_organization !== b.is_organization) return a.is_organization ? -1 : 1;
      return a.full_name.localeCompare(b.full_name);
    });
  }, [repos, search]);

  async function track(repo: GitHubRepo) {
    setPendingId(repo.id);
    setError(null);
    try {
      await jsonRequest(
        `/api/workspaces/${workspaceId}/github/repos`,
        {
          method: "POST",
          body: JSON.stringify({ repo_id: repo.id, owner: repo.owner, name: repo.name }),
        },
        "Could not track this repository.",
      );
      await onChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPendingId(null);
    }
  }

  async function untrack(repoId: number) {
    setPendingId(repoId);
    try {
      await onUntrack(repoId);
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="github-modal-backdrop" role="dialog" aria-modal="true">
      <div className="github-modal">
        <header className="github-modal-header">
          <h2>Tracked repositories</h2>
          <button type="button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div className="github-search github-search--block">
          <Search size={15} />
          <input
            type="search"
            className="github-search-input"
            placeholder="Search your repositories"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        {error && <p className="github-modal-error">{error}</p>}

        <div className="github-modal-body">
          {loading ? (
            <div className="github-page--centered">
              <Loader2 className="github-spinner" size={20} />
            </div>
          ) : visible.length === 0 ? (
            <p className="github-lane-empty">No repositories match.</p>
          ) : (
            <ul className="github-repo-list">
              {visible.map((repo) => {
                const tracked = trackedIds.has(repo.id);
                return (
                  <li key={repo.id} className="github-repo-row">
                    <div className="github-repo-info">
                      <span className="github-repo-name">{repo.full_name}</span>
                      <span className="github-repo-tags">
                        {repo.is_organization && (
                          <span className="github-tag">Organization</span>
                        )}
                        {repo.private && <span className="github-tag">Private</span>}
                        <span className="github-repo-issues">
                          {repo.open_issues_count} open
                        </span>
                      </span>
                    </div>
                    <button
                      type="button"
                      className={tracked ? "github-secondary-button" : "github-primary-button"}
                      disabled={pendingId === repo.id}
                      onClick={() => (tracked ? untrack(repo.id) : track(repo))}
                    >
                      {pendingId === repo.id ? (
                        <Loader2 className="github-spinner" size={14} />
                      ) : tracked ? (
                        <>
                          <Trash2 size={14} /> Untrack
                        </>
                      ) : (
                        <>
                          <Plus size={14} /> Track
                        </>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function IssueComposer({
  workspaceId,
  repos,
  onClose,
  onCreated,
}: {
  workspaceId: string;
  repos: GitHubTrackedRepo[];
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [repoId, setRepoId] = useState<number>(repos[0]?.repo_id ?? 0);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [labels, setLabels] = useState<string[]>([]);
  const [assignees, setAssignees] = useState<string[]>([]);
  const [labelOptions, setLabelOptions] = useState<GitHubLabel[]>([]);
  const [assigneeOptions, setAssigneeOptions] = useState<GitHubUser[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Labels and assignees are per repository, so they reload whenever the
  // target changes — a label from one repo does not exist on another.
  useEffect(() => {
    if (!repoId) return;
    let cancelled = false;
    // Clearing the previous repo's picks before its replacements arrive: a
    // label or assignee from the old repository would be rejected by GitHub.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLabels([]);
    setAssignees([]);

    (async () => {
      try {
        const [repoLabels, repoAssignees] = await Promise.all([
          jsonRequest<GitHubLabel[]>(
            `/api/workspaces/${workspaceId}/github/repos/${repoId}/labels`,
            {},
            "Could not load labels.",
          ),
          jsonRequest<GitHubUser[]>(
            `/api/workspaces/${workspaceId}/github/repos/${repoId}/assignees`,
            {},
            "Could not load assignees.",
          ),
        ]);
        if (cancelled) return;
        setLabelOptions(repoLabels);
        setAssigneeOptions(repoAssignees);
      } catch {
        // Non-fatal: an issue can still be filed with just a title and body.
        if (!cancelled) {
          setLabelOptions([]);
          setAssigneeOptions([]);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [workspaceId, repoId]);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim() || !repoId) return;

    setSubmitting(true);
    setError(null);
    try {
      await jsonRequest(
        `/api/workspaces/${workspaceId}/github/issues`,
        {
          method: "POST",
          body: JSON.stringify({
            repo_id: repoId,
            title: title.trim(),
            body: body.trim() || null,
            assignees,
            labels,
          }),
        },
        "Could not create the issue.",
      );
      await onCreated();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  function toggle(list: string[], value: string): string[] {
    return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
  }

  return (
    <div className="github-modal-backdrop" role="dialog" aria-modal="true">
      <form className="github-modal" onSubmit={submit}>
        <header className="github-modal-header">
          <h2>New issue</h2>
          <button type="button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div className="github-modal-body github-form">
          <label className="github-field">
            <span>Repository</span>
            <select
              value={repoId}
              onChange={(event) => setRepoId(Number(event.target.value))}
              required
            >
              {repos.map((repo) => (
                <option key={repo.repo_id} value={repo.repo_id}>
                  {repo.full_name}
                </option>
              ))}
            </select>
          </label>

          <label className="github-field">
            <span>Title</span>
            <input
              type="text"
              value={title}
              maxLength={256}
              required
              placeholder="Short summary"
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>

          <label className="github-field">
            <span>Description</span>
            <textarea
              value={body}
              rows={6}
              placeholder="Markdown is supported"
              onChange={(event) => setBody(event.target.value)}
            />
          </label>

          {assigneeOptions.length > 0 && (
            <div className="github-field">
              <span>Assignees</span>
              <div className="github-option-row">
                {assigneeOptions.map((user) => (
                  <button
                    key={user.login}
                    type="button"
                    className={`github-chip${assignees.includes(user.login) ? " github-chip--on" : ""}`}
                    onClick={() => setAssignees((list) => toggle(list, user.login))}
                  >
                    {user.login}
                  </button>
                ))}
              </div>
            </div>
          )}

          {labelOptions.length > 0 && (
            <div className="github-field">
              <span>Labels</span>
              <div className="github-option-row">
                {labelOptions.map((label) => (
                  <button
                    key={label.name}
                    type="button"
                    className={`github-chip${labels.includes(label.name) ? " github-chip--on" : ""}`}
                    style={
                      labels.includes(label.name)
                        ? {
                            background: `#${label.color}`,
                            color: labelTextColor(label.color),
                            borderColor: `#${label.color}`,
                          }
                        : undefined
                    }
                    onClick={() => setLabels((list) => toggle(list, label.name))}
                  >
                    {label.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {error && <p className="github-modal-error">{error}</p>}
        </div>

        <footer className="github-modal-footer">
          <button type="button" className="github-secondary-button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="github-primary-button"
            disabled={submitting || !title.trim()}
          >
            {submitting ? <Loader2 className="github-spinner" size={14} /> : <Plus size={14} />}
            Create issue
          </button>
        </footer>
      </form>
    </div>
  );
}
