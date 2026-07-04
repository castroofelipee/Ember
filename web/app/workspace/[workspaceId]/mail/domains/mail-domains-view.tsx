"use client";

import { useEffect, useState, type SubmitEvent } from "react";
import { useParams, useRouter } from "next/navigation";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRequireAuth } from "@/lib/auth-client";
import type { MailDomain, MailDomainStatus } from "@/lib/types";

import { MailNav } from "../mail-nav";

type Status = "loading" | "ready" | "not-found";

const STATUS_OPTIONS: { value: MailDomainStatus; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "active", label: "Active" },
  { value: "disabled", label: "Disabled" },
];

function domainsUrl(workspaceId: string, domainId?: string): string {
  const base = `/api/workspaces/${workspaceId}/mail/domains`;
  return domainId ? `${base}/${domainId}` : base;
}

export function MailDomainsView() {
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { status: authStatus, accessToken } = useRequireAuth();
  const [status, setStatus] = useState<Status>("loading");
  const [domains, setDomains] = useState<MailDomain[]>([]);
  const [newDomain, setNewDomain] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDomain, setEditDomain] = useState("");
  const [editStatus, setEditStatus] = useState<MailDomainStatus>("pending");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);

  useEffect(() => {
    if (authStatus !== "ready") return;
    let cancelled = false;

    fetch(domainsUrl(workspaceId), {
      headers: { Authorization: `Bearer ${accessToken}` },
    }).then(async (response) => {
      if (cancelled) return;
      if (response.status === 404) {
        setStatus("not-found");
        return;
      }
      if (response.ok) {
        setDomains(await response.json());
        setStatus("ready");
      }
    });

    return () => {
      cancelled = true;
    };
  }, [authStatus, accessToken, workspaceId]);

  async function handleCreate(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newDomain.trim()) return;
    setCreating(true);
    setCreateError(null);

    const response = await fetch(domainsUrl(workspaceId), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ domain: newDomain.trim() }),
    });

    if (response.status === 409) {
      setCreateError("A domain with this name is already registered.");
      setCreating(false);
      return;
    }
    if (!response.ok) {
      setCreateError("Could not add the domain. Please check the name and try again.");
      setCreating(false);
      return;
    }

    const domain: MailDomain = await response.json();
    setDomains((prev) => [...prev, domain]);
    setNewDomain("");
    setCreating(false);
  }

  function startEditing(domain: MailDomain) {
    setEditingId(domain.id);
    setEditDomain(domain.domain);
    setEditStatus(domain.status);
    setEditError(null);
  }

  function cancelEditing() {
    setEditingId(null);
    setEditError(null);
  }

  async function saveEditing(domainId: string) {
    setSavingId(domainId);
    setEditError(null);

    const response = await fetch(domainsUrl(workspaceId, domainId), {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ domain: editDomain.trim(), status: editStatus }),
    });

    if (response.status === 409) {
      setEditError("A domain with this name is already registered.");
      setSavingId(null);
      return;
    }
    if (!response.ok) {
      setEditError("Could not save changes. Please check the name and try again.");
      setSavingId(null);
      return;
    }

    const updated: MailDomain = await response.json();
    setDomains((prev) => prev.map((d) => (d.id === domainId ? updated : d)));
    setSavingId(null);
    setEditingId(null);
  }

  async function handleDelete(domainId: string) {
    setDeletingId(domainId);
    setRowError(null);

    const response = await fetch(domainsUrl(workspaceId, domainId), {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
    });

    if (response.status === 409) {
      setRowError({
        id: domainId,
        message: "Remove this domain's mail accounts before deleting it.",
      });
      setDeletingId(null);
      return;
    }
    if (!response.ok) {
      setRowError({ id: domainId, message: "Could not delete the domain. Please try again." });
      setDeletingId(null);
      return;
    }

    setDomains((prev) => prev.filter((d) => d.id !== domainId));
    setDeletingId(null);
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
        <h1 className="auth-title">Mail domains</h1>
        <p className="auth-subtitle">Domains this workspace can send and receive mail on</p>
      </div>
      <div className="hub-content">
        <MailNav workspaceId={workspaceId} active="domains" />
        <section className="settings-section">
          {domains.length > 0 && (
            <div className="mail-domain-list">
              {domains.map((domain) => {
                const isEditing = editingId === domain.id;
                return (
                  <div className="mail-domain-row" key={domain.id}>
                    {isEditing ? (
                      <>
                        <div className="mail-domain-edit-fields">
                          <div className="form-field">
                            <Label htmlFor={`domain-${domain.id}`} className="form-label">
                              Domain
                            </Label>
                            <input
                              id={`domain-${domain.id}`}
                              className="form-input"
                              value={editDomain}
                              onChange={(event) => setEditDomain(event.target.value)}
                              maxLength={255}
                            />
                          </div>
                          <div className="form-field">
                            <Label htmlFor={`status-${domain.id}`} className="form-label">
                              Status
                            </Label>
                            <Select
                              value={editStatus}
                              onValueChange={(value) => setEditStatus(value as MailDomainStatus)}
                            >
                              <SelectTrigger id={`status-${domain.id}`} className="w-full">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {STATUS_OPTIONS.map((option) => (
                                  <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                        {editError && <p className="form-error">{editError}</p>}
                        <div className="mail-domain-actions">
                          <button
                            type="button"
                            className="event-detail-icon"
                            aria-label="Save"
                            onClick={() => saveEditing(domain.id)}
                            disabled={savingId === domain.id || !editDomain.trim()}
                          >
                            <Check size={16} />
                          </button>
                          <button
                            type="button"
                            className="event-detail-icon"
                            aria-label="Cancel"
                            onClick={cancelEditing}
                            disabled={savingId === domain.id}
                          >
                            <X size={16} />
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="mail-domain-info">
                          <span className="mail-domain-name">{domain.domain}</span>
                          <span className={`mail-domain-status mail-domain-status--${domain.status}`}>
                            {domain.status}
                          </span>
                        </div>
                        {rowError?.id === domain.id && (
                          <p className="form-error">{rowError.message}</p>
                        )}
                        <div className="mail-domain-actions">
                          <button
                            type="button"
                            className="event-detail-icon"
                            aria-label="Edit domain"
                            onClick={() => startEditing(domain)}
                          >
                            <Pencil size={16} />
                          </button>
                          <button
                            type="button"
                            className="event-detail-icon"
                            aria-label="Delete domain"
                            onClick={() => handleDelete(domain.id)}
                            disabled={deletingId === domain.id}
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <form className="settings-grid" onSubmit={handleCreate}>
            <div className="form-field">
              <Label htmlFor="new-domain" className="form-label">
                Add a domain
              </Label>
              <input
                className="form-input"
                id="new-domain"
                value={newDomain}
                onChange={(event) => setNewDomain(event.target.value)}
                placeholder="example.com"
                maxLength={255}
              />
            </div>

            {createError && <p className="form-error form-error--summary">{createError}</p>}

            <button
              className="button-primary"
              type="submit"
              disabled={creating || !newDomain.trim()}
            >
              <Plus size={16} />
              {creating ? "Adding…" : "Add domain"}
            </button>
          </form>
        </section>

        <button className="link-button" onClick={() => router.push(`/workspace/${workspaceId}`)}>
          Back to workspace
        </button>
      </div>
    </div>
  );
}
