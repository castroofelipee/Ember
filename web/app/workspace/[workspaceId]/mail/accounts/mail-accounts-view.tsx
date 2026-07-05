"use client";

import { useEffect, useMemo, useState, type SubmitEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { Ban, Check, Pencil, Plus, RotateCcw, Send, Trash2, X } from "lucide-react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRequireAuth } from "@/lib/auth-client";
import type {
  MailAccount,
  MailAccountStatus,
  MailDomain,
  MailMessageSendResult,
} from "@/lib/types";

import { MailNav } from "../mail-nav";

type Status = "loading" | "ready" | "not-found";

const STATUS_FILTER_OPTIONS: { value: MailAccountStatus | "all"; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "suspended", label: "Suspended" },
  { value: "disabled", label: "Disabled" },
];

function accountsUrl(workspaceId: string, accountId?: string): string {
  const base = `/api/workspaces/${workspaceId}/mail/accounts`;
  return accountId ? `${base}/${accountId}` : base;
}

function sendMessageUrl(workspaceId: string, accountId: string): string {
  return `${accountsUrl(workspaceId, accountId)}/messages/send`;
}

function domainsUrl(workspaceId: string): string {
  return `/api/workspaces/${workspaceId}/mail/domains`;
}

function parseRecipients(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((recipient) => recipient.trim())
    .filter(Boolean);
}

export function MailAccountsView() {
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { status: authStatus, accessToken } = useRequireAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [domains, setDomains] = useState<MailDomain[]>([]);
  const [accounts, setAccounts] = useState<MailAccount[]>([]);

  const [filterDomainId, setFilterDomainId] = useState("all");
  const [filterStatus, setFilterStatus] = useState<MailAccountStatus | "all">("all");
  const [search, setSearch] = useState("");

  const [newDomainId, setNewDomainId] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);

  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);

  const [composeAccountId, setComposeAccountId] = useState<string | null>(null);
  const [composeTo, setComposeTo] = useState("");
  const [composeCc, setComposeCc] = useState("");
  const [composeBcc, setComposeBcc] = useState("");
  const [composeSubject, setComposeSubject] = useState("");
  const [composeText, setComposeText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [sendResult, setSendResult] = useState<MailMessageSendResult | null>(null);

  useEffect(() => {
    if (authStatus !== "ready") return;
    let cancelled = false;

    Promise.all([
      fetch(accountsUrl(workspaceId), {
        headers: { Authorization: `Bearer ${accessToken}` },
      }),
      fetch(domainsUrl(workspaceId), {
        headers: { Authorization: `Bearer ${accessToken}` },
      }),
    ]).then(async ([accountsRes, domainsRes]) => {
      if (cancelled) return;
      if (accountsRes.status === 404) {
        setStatus("not-found");
        return;
      }
      if (accountsRes.ok) setAccounts(await accountsRes.json());
      if (domainsRes.ok) {
        const domainList: MailDomain[] = await domainsRes.json();
        setDomains(domainList);
        if (domainList.length > 0) setNewDomainId(domainList[0].id);
      }
      setStatus("ready");
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken, workspaceId]);

  const domainName = (domainId: string) =>
    domains.find((d) => d.id === domainId)?.domain ?? domainId;

  const activeAccounts = useMemo(
    () => accounts.filter((account) => account.status === "active"),
    [accounts],
  );
  const selectedComposeAccountId =
    composeAccountId && activeAccounts.some((account) => account.id === composeAccountId)
      ? composeAccountId
      : (activeAccounts[0]?.id ?? null);

  const filteredAccounts = useMemo(() => {
    const query = search.trim().toLowerCase();
    return accounts.filter((account) => {
      if (filterDomainId !== "all" && account.domain_id !== filterDomainId) return false;
      if (filterStatus !== "all" && account.status !== filterStatus) return false;
      if (!query) return true;
      return (
        account.email.toLowerCase().includes(query) ||
        (account.display_name ?? "").toLowerCase().includes(query)
      );
    });
  }, [accounts, filterDomainId, filterStatus, search]);

  async function handleCreate(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newEmail.trim() || !newDomainId) return;
    setCreating(true);
    setCreateError(null);

    const response = await fetch(accountsUrl(workspaceId), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({
        domain_id: newDomainId,
        email: newEmail.trim(),
        display_name: newDisplayName.trim() || undefined,
      }),
    });

    if (response.status === 503) {
      setCreateError("Mail is not configured on this server yet.");
      setCreating(false);
      return;
    }
    // 409 covers both "already registered" and "domain not set up on the mail
    // server"; 422 covers address/domain mismatch. Surface the server's own
    // detail so the right one shows, with a sensible fallback.
    if (response.status === 409 || response.status === 422) {
      const detail = await response
        .json()
        .then((body) => (typeof body?.detail === "string" ? body.detail : null))
        .catch(() => null);
      setCreateError(detail ?? "Could not create the account. Please check the details.");
      setCreating(false);
      return;
    }
    if (response.status === 502) {
      const detail = await response
        .json()
        .then((body) => (typeof body?.detail === "string" ? body.detail : null))
        .catch(() => null);
      setCreateError(detail ?? "Could not reach the mail server. Please try again.");
      setCreating(false);
      return;
    }
    if (!response.ok) {
      setCreateError("Could not create the account. Please try again.");
      setCreating(false);
      return;
    }

    const account: MailAccount = await response.json();
    setAccounts((prev) => [...prev, account]);
    setNewEmail("");
    setNewDisplayName("");
    setCreating(false);
  }

  function startEditing(account: MailAccount) {
    setEditingId(account.id);
    setEditDisplayName(account.display_name ?? "");
    setEditError(null);
  }

  function cancelEditing() {
    setEditingId(null);
    setEditError(null);
  }

  async function saveEditing(accountId: string) {
    setSavingId(accountId);
    setEditError(null);

    const response = await fetch(accountsUrl(workspaceId, accountId), {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ display_name: editDisplayName.trim() || null }),
    });

    if (!response.ok) {
      setEditError("Could not save changes. Please try again.");
      setSavingId(null);
      return;
    }

    const updated: MailAccount = await response.json();
    setAccounts((prev) => prev.map((a) => (a.id === accountId ? updated : a)));
    setSavingId(null);
    setEditingId(null);
  }

  async function toggleSuspend(account: MailAccount) {
    setTogglingId(account.id);
    setRowError(null);
    const nextStatus: MailAccountStatus = account.status === "active" ? "suspended" : "active";

    const response = await fetch(accountsUrl(workspaceId, account.id), {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ status: nextStatus }),
    });

    if (!response.ok) {
      setRowError({ id: account.id, message: "Could not update the account. Please try again." });
      setTogglingId(null);
      return;
    }

    const updated: MailAccount = await response.json();
    setAccounts((prev) => prev.map((a) => (a.id === account.id ? updated : a)));
    setTogglingId(null);
  }

  async function handleDelete(accountId: string) {
    setDeletingId(accountId);
    setRowError(null);

    const response = await fetch(accountsUrl(workspaceId, accountId), {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (response.status === 502) {
      setRowError({
        id: accountId,
        message: "Could not delete the account on the mail server. Please try again.",
      });
      setDeletingId(null);
      return;
    }
    if (!response.ok) {
      setRowError({ id: accountId, message: "Could not delete the account. Please try again." });
      setDeletingId(null);
      return;
    }

    setAccounts((prev) => prev.filter((a) => a.id !== accountId));
    setDeletingId(null);
  }

  async function handleSend(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedComposeAccountId) return;
    const to = parseRecipients(composeTo);
    if (to.length === 0 || !composeText.trim()) return;

    setSending(true);
    setSendError(null);
    setSendResult(null);

    const response = await fetch(sendMessageUrl(workspaceId, selectedComposeAccountId), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({
        to,
        cc: parseRecipients(composeCc),
        bcc: parseRecipients(composeBcc),
        subject: composeSubject,
        text: composeText,
      }),
    });

    if (!response.ok) {
      const detail = await response
        .json()
        .then((body) => (typeof body?.detail === "string" ? body.detail : null))
        .catch(() => null);
      setSendError(detail ?? "Could not send the message. Please try again.");
      setSending(false);
      return;
    }

    const result: MailMessageSendResult = await response.json();
    setSendResult(result);
    setComposeTo("");
    setComposeCc("");
    setComposeBcc("");
    setComposeSubject("");
    setComposeText("");
    setSending(false);
  }

  if (authStatus !== "ready" || status === "loading") {
    return (
      <div className="hub-page">
        <div className="hub-header">
          <h1 className="auth-title">Ember</h1>
        </div>
        <p className="auth-subtitle">Loading…</p>
      </div>
    );
  }

  if (status === "not-found") {
    return (
      <div className="hub-page">
        <div className="hub-header">
          <h1 className="auth-title">Ember</h1>
          <p className="auth-subtitle">Workspace not found</p>
        </div>
        <button className="link-button" onClick={() => router.push("/calendars")}>
          Back to workspaces
        </button>
      </div>
    );
  }

  return (
    <div className="hub-page">
      <div className="hub-header">
        <h1 className="auth-title">Mail accounts</h1>
        <p className="auth-subtitle">Email accounts provisioned on this workspace&apos;s domains</p>
      </div>
      <div className="hub-content hub-content--wide">
        <MailNav workspaceId={workspaceId} active="accounts" />

        <section className="settings-section">
          {domains.length === 0 ? (
            <p className="settings-section-hint">
              Add a domain before creating accounts — switch to the Domains tab above.
            </p>
          ) : (
            <>
              <div className="mail-accounts-toolbar">
                <div className="form-field">
                  <Label htmlFor="filter-domain" className="form-label">
                    Domain
                  </Label>
                  <Select value={filterDomainId} onValueChange={setFilterDomainId}>
                    <SelectTrigger id="filter-domain" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All domains</SelectItem>
                      {domains.map((domain) => (
                        <SelectItem key={domain.id} value={domain.id}>
                          {domain.domain}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="form-field">
                  <Label htmlFor="filter-status" className="form-label">
                    Status
                  </Label>
                  <Select
                    value={filterStatus}
                    onValueChange={(value) => setFilterStatus(value as MailAccountStatus | "all")}
                  >
                    <SelectTrigger id="filter-status" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {STATUS_FILTER_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="form-field">
                  <Label htmlFor="filter-search" className="form-label">
                    Search
                  </Label>
                  <input
                    className="form-input"
                    id="filter-search"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Email or name"
                  />
                </div>
              </div>

              {filteredAccounts.length > 0 && (
                <div className="mail-accounts-table-wrap">
                  <table className="mail-accounts-table">
                    <thead>
                      <tr>
                        <th>Email</th>
                        <th>Name</th>
                        <th>Domain</th>
                        <th>Status</th>
                        <th aria-label="Actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {filteredAccounts.map((account) => {
                        const isEditing = editingId === account.id;
                        return (
                          <tr key={account.id}>
                            <td>{account.email}</td>
                            <td>
                              {isEditing ? (
                                <input
                                  className="form-input"
                                  value={editDisplayName}
                                  onChange={(event) => setEditDisplayName(event.target.value)}
                                  maxLength={120}
                                  autoFocus
                                />
                              ) : (
                                (account.display_name ?? "—")
                              )}
                              {editError && isEditing && (
                                <p className="form-error">{editError}</p>
                              )}
                            </td>
                            <td>{domainName(account.domain_id)}</td>
                            <td>
                              <span
                                className={`mail-account-status mail-account-status--${account.status}`}
                              >
                                {account.status}
                              </span>
                              {rowError?.id === account.id && (
                                <p className="form-error">{rowError.message}</p>
                              )}
                            </td>
                            <td>
                              <div className="mail-domain-actions">
                                {isEditing ? (
                                  <>
                                    <button
                                      type="button"
                                      className="event-detail-icon"
                                      aria-label="Save"
                                      onClick={() => saveEditing(account.id)}
                                      disabled={savingId === account.id}
                                    >
                                      <Check size={16} />
                                    </button>
                                    <button
                                      type="button"
                                      className="event-detail-icon"
                                      aria-label="Cancel"
                                      onClick={cancelEditing}
                                      disabled={savingId === account.id}
                                    >
                                      <X size={16} />
                                    </button>
                                  </>
                                ) : (
                                  <>
                                    <button
                                      type="button"
                                      className="event-detail-icon"
                                      aria-label="Edit display name"
                                      onClick={() => startEditing(account)}
                                    >
                                      <Pencil size={16} />
                                    </button>
                                    <button
                                      type="button"
                                      className="event-detail-icon"
                                      aria-label={
                                        account.status === "active"
                                          ? "Suspend account"
                                          : "Reactivate account"
                                      }
                                      onClick={() => toggleSuspend(account)}
                                      disabled={togglingId === account.id}
                                    >
                                      {account.status === "active" ? (
                                        <Ban size={16} />
                                      ) : (
                                        <RotateCcw size={16} />
                                      )}
                                    </button>
                                    <button
                                      type="button"
                                      className="event-detail-icon"
                                      aria-label="Delete account"
                                      onClick={() => handleDelete(account.id)}
                                      disabled={deletingId === account.id}
                                    >
                                      <Trash2 size={16} />
                                    </button>
                                  </>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {filteredAccounts.length === 0 && (
                <p className="settings-section-hint">No accounts match these filters.</p>
              )}

              <form className="mail-compose" onSubmit={handleSend}>
                <div className="mail-compose-header">
                  <div>
                    <h2 className="settings-section-title">Compose</h2>
                    <p className="settings-section-hint">
                      Send a plain text message from an active workspace account.
                    </p>
                  </div>
                  <button
                    className="button-primary"
                    type="submit"
                    disabled={
                      sending ||
                      !selectedComposeAccountId ||
                      parseRecipients(composeTo).length === 0 ||
                      !composeText.trim()
                    }
                  >
                    <Send size={16} />
                    {sending ? "Sending..." : "Send"}
                  </button>
                </div>

                {activeAccounts.length === 0 ? (
                  <p className="settings-section-hint">
                    Activate an account before sending mail.
                  </p>
                ) : (
                  <div className="mail-compose-grid">
                    <div className="form-field">
                      <Label htmlFor="compose-from" className="form-label">
                        From
                      </Label>
                      <Select
                        value={selectedComposeAccountId ?? undefined}
                        onValueChange={setComposeAccountId}
                      >
                        <SelectTrigger id="compose-from" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {activeAccounts.map((account) => (
                            <SelectItem key={account.id} value={account.id}>
                              {account.email}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="form-field">
                      <Label htmlFor="compose-to" className="form-label">
                        To
                      </Label>
                      <input
                        className="form-input"
                        id="compose-to"
                        value={composeTo}
                        onChange={(event) => setComposeTo(event.target.value)}
                        placeholder="name@example.com, team@example.com"
                      />
                    </div>

                    <div className="form-field">
                      <Label htmlFor="compose-cc" className="form-label">
                        Cc
                      </Label>
                      <input
                        className="form-input"
                        id="compose-cc"
                        value={composeCc}
                        onChange={(event) => setComposeCc(event.target.value)}
                      />
                    </div>

                    <div className="form-field">
                      <Label htmlFor="compose-bcc" className="form-label">
                        Bcc
                      </Label>
                      <input
                        className="form-input"
                        id="compose-bcc"
                        value={composeBcc}
                        onChange={(event) => setComposeBcc(event.target.value)}
                      />
                    </div>

                    <div className="form-field mail-compose-subject">
                      <Label htmlFor="compose-subject" className="form-label">
                        Subject
                      </Label>
                      <input
                        className="form-input"
                        id="compose-subject"
                        value={composeSubject}
                        onChange={(event) => setComposeSubject(event.target.value)}
                        maxLength={998}
                      />
                    </div>

                    <div className="form-field mail-compose-body">
                      <Label htmlFor="compose-text" className="form-label">
                        Message
                      </Label>
                      <textarea
                        className="event-dialog-input mail-compose-textarea"
                        id="compose-text"
                        value={composeText}
                        onChange={(event) => setComposeText(event.target.value)}
                        rows={8}
                      />
                    </div>
                  </div>
                )}

                {sendError && <p className="form-error form-error--summary">{sendError}</p>}
                {sendResult && (
                  <p className="auth-success">
                    Message submitted ({sendResult.submission_id}).
                  </p>
                )}
              </form>

              <form className="settings-grid" onSubmit={handleCreate}>
                <div className="form-field">
                  <Label htmlFor="new-account-domain" className="form-label">
                    Domain
                  </Label>
                  <Select value={newDomainId ?? undefined} onValueChange={setNewDomainId}>
                    <SelectTrigger id="new-account-domain" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {domains.map((domain) => (
                        <SelectItem key={domain.id} value={domain.id}>
                          {domain.domain}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="form-field">
                  <Label htmlFor="new-account-email" className="form-label">
                    Email
                  </Label>
                  <input
                    className="form-input"
                    id="new-account-email"
                    value={newEmail}
                    onChange={(event) => setNewEmail(event.target.value)}
                    placeholder={`user@${newDomainId ? domainName(newDomainId) : "example.com"}`}
                    maxLength={320}
                  />
                </div>

                <div className="form-field">
                  <Label htmlFor="new-account-name" className="form-label">
                    Display name (optional)
                  </Label>
                  <input
                    className="form-input"
                    id="new-account-name"
                    value={newDisplayName}
                    onChange={(event) => setNewDisplayName(event.target.value)}
                    maxLength={120}
                  />
                </div>

                {createError && <p className="form-error form-error--summary">{createError}</p>}

                <button
                  className="button-primary"
                  type="submit"
                  disabled={creating || !newEmail.trim() || !newDomainId}
                >
                  <Plus size={16} />
                  {creating ? "Creating…" : "Create account"}
                </button>
              </form>
            </>
          )}
        </section>

        <button className="link-button" onClick={() => router.push(`/workspace/${workspaceId}/mail`)}>
          Back to mail
        </button>
      </div>
    </div>
  );
}
