"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Archive,
  ChevronLeft,
  Clock,
  FileText,
  Inbox,
  Mail,
  MailOpen,
  Menu,
  MoreVertical,
  Paperclip,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldAlert,
  Star,
  Trash2,
} from "lucide-react";

import { useRequireAuth } from "@/lib/auth-client";
import type { MailFolder, MailThread, MailThreadPreview } from "@/lib/types";

type Status = "loading" | "ready" | "not-found";

type FolderItem = {
  key: MailFolder;
  label: string;
  icon: typeof Inbox;
};

const FOLDERS: FolderItem[] = [
  { key: "inbox", label: "Inbox", icon: Inbox },
  { key: "sent", label: "Sent", icon: Send },
  { key: "drafts", label: "Drafts", icon: FileText },
  { key: "archive", label: "Archive", icon: Archive },
  { key: "junk", label: "Spam", icon: ShieldAlert },
  { key: "trash", label: "Trash", icon: Trash2 },
];

function threadsUrl(workspaceId: string, folder: MailFolder): string {
  return `/api/workspaces/${workspaceId}/mail/threads?folder=${folder}&limit=50`;
}

function threadUrl(workspaceId: string, accountId: string, threadId: string): string {
  return `/api/workspaces/${workspaceId}/mail/accounts/${accountId}/threads/${threadId}`;
}

function messageUrl(workspaceId: string, accountId: string, messageId: string): string {
  return `/api/workspaces/${workspaceId}/mail/accounts/${accountId}/messages/${messageId}`;
}

function displayAddress(address?: { email: string; name: string | null } | null): string {
  if (!address) return "Unknown sender";
  return address.name || address.email;
}

function displayParticipants(thread: MailThreadPreview): string {
  if (thread.participants.length === 0) {
    return displayAddress(thread.latest_message.sender);
  }
  return thread.participants.map(displayAddress).slice(0, 3).join(", ");
}

function formatMailDate(value: string): string {
  const date = new Date(value);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) {
    return new Intl.DateTimeFormat("en", { hour: "numeric", minute: "2-digit" }).format(date);
  }
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(date);
}

function stripHtml(value: string): string {
  if (!value) return "";
  return value
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function MailView() {
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { status: authStatus, accessToken } = useRequireAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [folder, setFolder] = useState<MailFolder>("inbox");
  const [threads, setThreads] = useState<MailThreadPreview[]>([]);
  const [selected, setSelected] = useState<MailThreadPreview | null>(null);
  const [thread, setThread] = useState<MailThread | null>(null);
  const [loadingThread, setLoadingThread] = useState(false);
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadThreads(nextFolder = folder) {
    if (authStatus !== "ready") return;
    setRefreshing(true);
    setError(null);
    const response = await fetch(threadsUrl(workspaceId, nextFolder), {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (response.status === 404) {
      setStatus("not-found");
      setRefreshing(false);
      return;
    }
    if (!response.ok) {
      const detail = await response
        .json()
        .then((body) => (typeof body?.detail === "string" ? body.detail : null))
        .catch(() => null);
      setError(detail ?? "Could not load mail.");
      setStatus("ready");
      setRefreshing(false);
      return;
    }
    const items: MailThreadPreview[] = await response.json();
    setThreads(items);
    setSelected((current) => {
      if (!current) return items[0] ?? null;
      return items.find((item) => item.thread_id === current.thread_id) ?? items[0] ?? null;
    });
    setStatus("ready");
    setRefreshing(false);
  }

  useEffect(() => {
    if (authStatus !== "ready") return;
    void loadThreads(folder);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus, accessToken, workspaceId, folder]);

  useEffect(() => {
    if (authStatus !== "ready" || !selected) {
      setThread(null);
      return;
    }
    let cancelled = false;
    setLoadingThread(true);
    fetch(threadUrl(workspaceId, selected.account_id, selected.thread_id), {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled) return;
      if (response.ok) {
        const loaded: MailThread = await response.json();
        setThread(loaded);
        const unreadMessages = loaded.messages.filter((message) => !message.keywords.includes("$seen"));
        await Promise.all(
          unreadMessages.map((message) =>
            fetch(messageUrl(workspaceId, loaded.account_id, message.id), {
              method: "PATCH",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${accessToken}`,
              },
              body: JSON.stringify({ seen: true }),
            }),
          ),
        );
        if (unreadMessages.length > 0) {
          setThreads((items) =>
            items.map((item) =>
              item.thread_id === loaded.thread_id ? { ...item, unread_count: 0 } : item,
            ),
          );
        }
      }
      setLoadingThread(false);
    });
    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken, workspaceId, selected]);

  const filteredThreads = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return threads;
    return threads.filter((item) => {
      const haystack = [
        item.subject,
        item.preview,
        item.account_email,
        item.latest_message.sender?.email,
        item.latest_message.sender?.name,
        ...item.participants.flatMap((participant) => [participant.email, participant.name]),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(normalized);
    });
  }, [threads, query]);

  const activeFolder = FOLDERS.find((item) => item.key === folder) ?? FOLDERS[0];
  const selectedIsVisible =
    selected && filteredThreads.some((item) => item.thread_id === selected.thread_id);

  if (authStatus !== "ready" || status === "loading") {
    return (
      <div className="mail-app mail-app--center">
        <p className="mail-empty-title">Loading mail...</p>
      </div>
    );
  }

  if (status === "not-found") {
    return (
      <div className="mail-app mail-app--center">
        <p className="mail-empty-title">Workspace not found</p>
        <button className="link-button" onClick={() => router.push("/calendars")}>
          Back to workspaces
        </button>
      </div>
    );
  }

  return (
    <div className="mail-app">
      <aside className={`mail-rail${sidebarOpen ? "" : " mail-rail--closed"}`}>
        <div className="mail-rail-top">
          <button
            type="button"
            className="mail-icon-button"
            aria-label={sidebarOpen ? "Collapse mail sidebar" : "Expand mail sidebar"}
            onClick={() => setSidebarOpen((value) => !value)}
          >
            <Menu size={20} />
          </button>
          {sidebarOpen && <span className="mail-brand">Ember Mail</span>}
        </div>

        <button
          type="button"
          className="mail-compose-main"
          onClick={() => router.push(`/workspace/${workspaceId}/mail/accounts`)}
        >
          <Mail size={18} />
          {sidebarOpen && <span>Compose</span>}
        </button>

        <nav className="mail-folder-list" aria-label="Mail folders">
          {FOLDERS.map((item) => {
            const Icon = item.icon;
            const active = item.key === folder;
            return (
              <button
                key={item.key}
                type="button"
                className={`mail-folder-button${active ? " mail-folder-button--active" : ""}`}
                onClick={() => {
                  setFolder(item.key);
                  setSelected(null);
                  setThread(null);
                }}
              >
                <Icon size={18} />
                {sidebarOpen && <span>{item.label}</span>}
              </button>
            );
          })}
        </nav>

        {sidebarOpen && (
          <div className="mail-admin-links">
            <button type="button" onClick={() => router.push(`/workspace/${workspaceId}/mail/accounts`)}>
              <Settings size={16} />
              Accounts
            </button>
            <button type="button" onClick={() => router.push(`/workspace/${workspaceId}/mail/domains`)}>
              <Settings size={16} />
              Domains
            </button>
          </div>
        )}
      </aside>

      <main className="mail-workbench">
        <header className="mail-topbar">
          <button
            type="button"
            className="mail-icon-button mail-topbar-menu"
            aria-label="Back to calendar"
            onClick={() => router.push(`/workspace/${workspaceId}`)}
          >
            <ChevronLeft size={20} />
          </button>
          <div className="mail-searchbox">
            <Search size={18} />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search mail"
            />
          </div>
          <button
            type="button"
            className="mail-icon-button"
            aria-label="Refresh mail"
            onClick={() => void loadThreads(folder)}
            disabled={refreshing}
          >
            <RefreshCw size={18} />
          </button>
        </header>

        <section className="mail-panel">
          <div className="mail-list-pane">
            <div className="mail-list-head">
              <div>
                <p className="mail-list-kicker">{activeFolder.label}</p>
                <h1>{activeFolder.label}</h1>
              </div>
              <span>{filteredThreads.length}</span>
            </div>

            {error && <p className="form-error form-error--summary">{error}</p>}

            <div className="mail-thread-list">
              {filteredThreads.map((item) => {
                const active = selected?.thread_id === item.thread_id;
                const unread = item.unread_count > 0;
                return (
                  <button
                    type="button"
                    key={`${item.account_id}:${item.thread_id}`}
                    className={`mail-thread-row${active ? " mail-thread-row--active" : ""}${unread ? " mail-thread-row--unread" : ""}`}
                    onClick={() => setSelected(item)}
                  >
                    <span className="mail-thread-star" aria-hidden="true">
                      <Star size={16} />
                    </span>
                    <span className="mail-thread-sender">{displayParticipants(item)}</span>
                    <span className="mail-thread-content">
                      <span className="mail-thread-subject">
                        {item.subject || "(no subject)"}
                      </span>
                      <span className="mail-thread-preview">{item.preview}</span>
                    </span>
                    {item.has_attachment && <Paperclip size={15} className="mail-thread-attach" />}
                    {unread && <span className="mail-thread-count">{item.unread_count}</span>}
                    <span className="mail-thread-date">{formatMailDate(item.received_at)}</span>
                  </button>
                );
              })}
              {filteredThreads.length === 0 && (
                <div className="mail-empty-state">
                  <MailOpen size={32} />
                  <p className="mail-empty-title">No messages here</p>
                </div>
              )}
            </div>
          </div>

          <article className={`mail-reader${selectedIsVisible ? "" : " mail-reader--empty"}`}>
            {!selectedIsVisible || !selected ? (
              <div className="mail-empty-state mail-empty-state--reader">
                <MailOpen size={36} />
                <p className="mail-empty-title">Select a conversation</p>
              </div>
            ) : loadingThread || !thread ? (
              <div className="mail-empty-state mail-empty-state--reader">
                <Clock size={32} />
                <p className="mail-empty-title">Loading conversation...</p>
              </div>
            ) : (
              <>
                <div className="mail-reader-head">
                  <div>
                    <p className="mail-list-kicker">{thread.account_email}</p>
                    <h2>{selected.subject || "(no subject)"}</h2>
                  </div>
                  <button type="button" className="mail-icon-button" aria-label="More actions">
                    <MoreVertical size={18} />
                  </button>
                </div>

                <div className="mail-message-stack">
                  {thread.messages.map((message) => {
                    const body = message.text_body || stripHtml(message.html_body);
                    return (
                      <section key={message.id} className="mail-message-card">
                        <div className="mail-message-meta">
                          <div className="mail-avatar">
                            {displayAddress(message.sender).slice(0, 1).toUpperCase()}
                          </div>
                          <div>
                            <p className="mail-message-from">{displayAddress(message.sender)}</p>
                            <p className="mail-message-to">
                              to {message.to.map(displayAddress).join(", ") || thread.account_email}
                            </p>
                          </div>
                          <time>{formatMailDate(message.received_at)}</time>
                        </div>
                        <pre className="mail-message-body">{body || message.preview}</pre>
                      </section>
                    );
                  })}
                </div>
              </>
            )}
          </article>
        </section>
      </main>
    </div>
  );
}
