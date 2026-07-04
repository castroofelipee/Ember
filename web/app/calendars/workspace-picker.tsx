"use client";

import { useState, type SubmitEvent } from "react";
import { useRouter } from "next/navigation";
import { Building2, Plus } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Workspace } from "@/lib/types";

export function WorkspacePicker({
  accessToken,
  workspaces,
  onCreated,
}: {
  accessToken: string;
  workspaces: Workspace[];
  onCreated: (workspace: Workspace) => void;
}) {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleCreate(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setErrorMessage(null);

    const response = await fetch("/api/workspaces", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ name }),
    });

    if (!response.ok) {
      setErrorMessage("Could not create the workspace. Please try again.");
      setPending(false);
      return;
    }

    const workspace: Workspace = await response.json();
    onCreated(workspace);
    router.push(`/workspace/${workspace.id}`);
  }

  return (
    <div className="workspace-grid">
      {workspaces.map((workspace) => (
        <Card
          key={workspace.id}
          className="workspace-card"
          onClick={() => router.push(`/workspace/${workspace.id}`)}
        >
          <CardHeader>
            <div className="workspace-card-icon">
              <Building2 size={18} />
            </div>
            <CardTitle>{workspace.name}</CardTitle>
          </CardHeader>
          <CardContent>
            <span className="workspace-role-badge">{workspace.role}</span>
          </CardContent>
        </Card>
      ))}

      {creating ? (
        <Card className="workspace-card">
          <CardContent>
            <form className="auth-form" onSubmit={handleCreate}>
              <div className="form-field">
                <label className="form-label" htmlFor="new-workspace-name">
                  Workspace name
                </label>
                <input
                  className="form-input"
                  id="new-workspace-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={120}
                  autoFocus
                  required
                />
              </div>
              {errorMessage && <p className="form-error">{errorMessage}</p>}
              <button className="button-primary" type="submit" disabled={pending}>
                {pending ? "Creating…" : "Create"}
              </button>
            </form>
          </CardContent>
        </Card>
      ) : (
        <button className="new-workspace-card" type="button" onClick={() => setCreating(true)}>
          <Plus size={20} />
          New workspace
        </button>
      )}
    </div>
  );
}
