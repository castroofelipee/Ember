"use client";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, BookOpen, Check, Image as ImageIcon, Plus, Target, Trash2, Upload, X } from "lucide-react";
import { AppHeader } from "@/app/workspace/[workspaceId]/app-header";
import { useRequireAuth } from "@/lib/auth-client";
import type { HabitData, PersonalItem, Workspace } from "@/lib/types";
import { VisionCanvas } from "./vision-canvas";
import { ReadingsView } from "./readings-view";
import { HabitTracker } from "./habit-tracker";

type Tab = PersonalItem["kind"];
type Horizon = "short" | "medium" | "long" | "none";
type TimeframeMode = "none" | "year" | "range";
const HORIZONS: { key: Horizon; label: string; description: string }[] = [
  { key: "short", label: "Short term", description: "What feels close and actionable" },
  { key: "medium", label: "Medium term", description: "The next meaningful chapter" },
  { key: "long", label: "Long term", description: "The future you are building toward" },
  { key: "none", label: "No timeframe", description: "Ideas without a fixed deadline" },
];

export function PersonalSpace() {
  const { status, accessToken } = useRequireAuth();
  const [items, setItems] = useState<PersonalItem[]>([]);
  const [tab, setTab] = useState<Tab>("vision");
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [wallModal, setWallModal] = useState(false);
  const [goalModal, setGoalModal] = useState(false);
  const [uploadWall, setUploadWall] = useState<PersonalItem | null>(null);
  const [wallName, setWallName] = useState("");
  const [goalName, setGoalName] = useState("");
  const [goalDescription, setGoalDescription] = useState("");
  const [goalHorizon, setGoalHorizon] = useState<Horizon>("short");
  const [timeframeMode, setTimeframeMode] = useState<TimeframeMode>("none");
  const [startYear, setStartYear] = useState(String(new Date().getFullYear()));
  const [endYear, setEndYear] = useState(String(new Date().getFullYear() + 3));
  const [activeWallId, setActiveWallId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const authHeaders = { Authorization: `Bearer ${accessToken}` };
  const jsonHeaders = { ...authHeaders, "Content-Type": "application/json" };

  const load = useCallback(async () => {
    const response = await fetch("/api/personal/items", { headers: authHeaders });
    if (response.ok) setItems(await response.json());
  }, [accessToken]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (status !== "ready") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    fetch("/api/workspaces", { headers: authHeaders })
      .then((response) => (response.ok ? response.json() : []))
      .then((workspaces: Workspace[]) => setWorkspaceId(workspaces[0]?.id ?? null));
  }, [status, load]); // eslint-disable-line react-hooks/exhaustive-deps

  async function createWall(event: FormEvent) {
    event.preventDefault();
    if (!wallName.trim()) return;
    const response = await fetch("/api/personal/items", {
      method: "POST", headers: jsonHeaders,
      body: JSON.stringify({
        kind: "vision",
        title: wallName,
        data: { type: "wall" },
      }),
    });
    if (response.ok) { const created: PersonalItem = await response.json(); setItems((current) => [created, ...current]); }
    setWallName(""); setWallModal(false);
  }

  async function createGoal(event: FormEvent) {
    event.preventDefault();
    if (!activeWall || !goalName.trim()) return;
    const response = await fetch("/api/personal/items", {
      method: "POST", headers: jsonHeaders,
      body: JSON.stringify({
        kind: "vision",
        title: goalName,
        data: {
          type: "goal",
          wall_id: activeWall.id,
          description: goalDescription.trim(),
          horizon: goalHorizon,
          status: "idea",
          timeframe_mode: timeframeMode,
          start_year: timeframeMode === "none" ? null : Number(startYear),
          end_year: timeframeMode === "range" ? Number(endYear) : null,
        },
      }),
    });
    if (response.ok) { const created: PersonalItem = await response.json(); setItems((current) => [created, ...current]); }
    setGoalName(""); setGoalDescription(""); setGoalHorizon("short"); setTimeframeMode("none"); setGoalModal(false);
  }

  async function uploadImagesTo(wall: PersonalItem, files: FileList | File[]) {
    const list = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (!wall || list.length === 0) return;
    setUploading(true);
    for (const file of list) {
      const body = new FormData();
      body.append("wall_id", wall.id); body.append("file", file);
      const response = await fetch("/api/personal/vision/upload", { method: "POST", headers: authHeaders, body });
      if (response.ok) { const created: PersonalItem = await response.json(); setItems((current) => [created, ...current]); }
    }
    setUploading(false);
  }

  async function uploadImages(files: FileList | File[]) {
    if (!uploadWall) return;
    await uploadImagesTo(uploadWall, files);
    setUploadWall(null);
  }

  async function createHabit(habitTitle: string, data: HabitData) {
    const response = await fetch("/api/personal/items", { method: "POST", headers: jsonHeaders, body: JSON.stringify({ kind: "habit", title: habitTitle, data }) });
    if (response.ok) { const created: PersonalItem = await response.json(); setItems((current) => [created, ...current]); }
  }

  async function remove(item: PersonalItem) {
    const response = await fetch(`/api/personal/items/${item.id}`, { method: "DELETE", headers: authHeaders });
    if (response.ok) setItems((current) => current.filter((candidate) => candidate.id !== item.id && candidate.data.wall_id !== item.id));
  }

  async function updateItemData(item: PersonalItem, data: Record<string, unknown>) {
    setItems((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, data } : candidate));
    const response = await fetch(`/api/personal/items/${item.id}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify({ data }),
      keepalive: true,
    });
    if (!response.ok) void load();
  }

  async function toggleHabit(item: PersonalItem, iso: string) {
    const dates = Array.isArray(item.data.dates) ? item.data.dates as string[] : [];
    const next = dates.includes(iso) ? dates.filter((date) => date !== iso) : [...dates, iso];
    setItems((current) => current.map((candidate) => candidate.id === item.id ? { ...candidate, data: { ...candidate.data, dates: next } } : candidate));
    const response = await fetch(`/api/personal/items/${item.id}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ data: { ...item.data, dates: next } }) });
    if (!response.ok) void load();
  }

  if (status !== "ready") return <div className="personal-page">Loading…</div>;
  const walls = items.filter((item) => item.kind === "vision" && item.data.type === "wall");
  const activeWall = walls.find((wall) => wall.id === activeWallId) ?? null;
  const habitItems = items.filter((item) => item.kind === "habit");

  return <div className="personal-shell">
    {workspaceId && <AppHeader workspaceId={workspaceId} />}
    <main className="personal-page">
      <header className="personal-hero"><span>YOUR PRIVATE SPACE</span></header>
      <nav className="personal-tabs">{([ ["vision", ImageIcon, "Vision board"], ["reading", BookOpen, "Readings"], ["habit", Check, "Habits"] ] as const).map(([key, Icon, label]) => <button className={tab === key ? "active" : ""} key={key} onClick={() => setTab(key)}><Icon size={17}/>{label}</button>)}</nav>

      {tab === "vision" ? <>
        {activeWall ? (() => { const images = items.filter((item) => item.data.type === "image" && item.data.wall_id === activeWall.id); const goals = items.filter((item) => item.data.type === "goal" && item.data.wall_id === activeWall.id); return <section className="vision-board-detail">
          <div className="vision-board-detail-head"><button className="vision-back" onClick={() => setActiveWallId(null)}><ArrowLeft size={17}/>All boards</button><div><h2>{activeWall.title}</h2><span>{goals.length} {goals.length === 1 ? "goal" : "goals"} · {images.length} {images.length === 1 ? "image" : "images"}</span></div><div className="vision-board-actions"><button onClick={() => setGoalModal(true)}><Target size={16}/>Add goal</button><button title="Add images" onClick={() => setUploadWall(activeWall)}><Upload size={16}/>Add images</button><button className="vision-delete-board" title="Delete board" onClick={() => { void remove(activeWall); setActiveWallId(null); }}><Trash2 size={15}/></button></div></div>
          <div className="vision-goals">{goals.map((goal) => <article className="vision-goal-card" key={goal.id}><span className={`vision-goal-horizon vision-goal-horizon--${String(goal.data.horizon)}`}>{horizonLabel(goal)}</span><h3>{goal.title}</h3>{Boolean(goal.data.description) && <p>{String(goal.data.description)}</p>}<footer><span>{timeframeLabel(goal)}</span><button aria-label="Delete goal" onClick={() => remove(goal)}><Trash2 size={14}/></button></footer></article>)}{!goals.length && <button className="vision-goal-empty" onClick={() => setGoalModal(true)}><Target size={19}/><span>Add your first goal</span></button>}</div>
          <VisionCanvas wall={activeWall} images={images} uploading={uploading} onUpload={(files) => uploadImagesTo(activeWall, files)} onRemove={remove} onUpdate={updateItemData}/>
        </section>; })() : <>
          <div className="vision-toolbar"><div><strong>Your vision boards</strong><span>Create a space, then define goals and inspiration inside it.</span></div><button onClick={() => setWallModal(true)}><Plus size={17}/>New board</button></div>
          <section className="vision-board-grid">{walls.map((wall) => { const images = items.filter((item) => item.data.type === "image" && item.data.wall_id === wall.id); const goals = items.filter((item) => item.data.type === "goal" && item.data.wall_id === wall.id); return <button className="vision-board-card" key={wall.id} onClick={() => setActiveWallId(wall.id)}><div className="vision-board-preview">{images.slice(0, 3).map((image) => <span key={image.id} style={{ backgroundImage: `url(${String(image.data.image_url)})` }}/>) }{!images.length && <ImageIcon size={24}/>}</div><div className="vision-board-card-copy"><strong>{wall.title}</strong><span>{goals.length} {goals.length === 1 ? "goal" : "goals"} · {images.length} {images.length === 1 ? "image" : "images"}</span></div></button>; })}<button className="vision-board-add" onClick={() => setWallModal(true)}><Plus size={18}/><span>Create a new board</span></button></section>
        </>}
      </> : tab === "habit" ? (
        <HabitTracker habits={habitItems} onCreate={createHabit} onUpdate={updateItemData} onToggle={toggleHabit} onRemove={remove}/>
      ) : <ReadingsView items={items} accessToken={accessToken} onCreated={(item) => setItems((current) => [item, ...current])} onUpdated={(item) => setItems((current) => current.map((candidate) => candidate.id === item.id ? item : candidate))}/>}
    </main>

    {wallModal && <div className="vision-drawer-backdrop" onClick={() => setWallModal(false)}><aside className="vision-drawer" onClick={(event) => event.stopPropagation()}><header><div><span>NEW BOARD</span><h2>Create a vision board</h2></div><button type="button" onClick={() => setWallModal(false)}><X size={19}/></button></header><form onSubmit={createWall}><div className="vision-drawer-intro"><span className="personal-modal-icon"><ImageIcon size={20}/></span><p>Name the visual space you want to build and revisit.</p></div><label className="personal-modal-field"><span>Board name</span><input autoFocus value={wallName} onChange={(event) => setWallName(event.target.value)} placeholder="e.g. My dream home" maxLength={240}/></label><footer><button type="button" className="vision-drawer-cancel" onClick={() => setWallModal(false)}>Cancel</button><button className="personal-primary">Create board</button></footer></form></aside></div>}
    {goalModal && activeWall && <div className="vision-drawer-backdrop" onClick={() => setGoalModal(false)}><aside className="vision-drawer" onClick={(event) => event.stopPropagation()}><header><div><span>NEW GOAL</span><h2>Create a goal</h2></div><button type="button" onClick={() => setGoalModal(false)}><X size={19}/></button></header><form onSubmit={createGoal}><div className="vision-drawer-intro"><span className="personal-modal-icon"><Target size={20}/></span><p>Define what you want to make real inside {activeWall.title}.</p></div><label className="personal-modal-field"><span>Goal</span><input autoFocus value={goalName} onChange={(event) => setGoalName(event.target.value)} placeholder="e.g. Save for the down payment" maxLength={240}/></label><label className="personal-modal-field"><span>Description</span><input value={goalDescription} onChange={(event) => setGoalDescription(event.target.value)} placeholder="Optional context" maxLength={500}/></label><label className="personal-modal-field"><span>Horizon</span><select value={goalHorizon} onChange={(event) => setGoalHorizon(event.target.value as Horizon)}>{HORIZONS.map((horizon) => <option key={horizon.key} value={horizon.key}>{horizon.label}</option>)}</select></label><label className="personal-modal-field"><span>Timeframe</span><select value={timeframeMode} onChange={(event) => setTimeframeMode(event.target.value as TimeframeMode)}><option value="none">No specific date</option><option value="year">Target year</option><option value="range">Year range</option></select></label>{timeframeMode !== "none" && <div className="personal-year-fields"><label className="personal-modal-field"><span>{timeframeMode === "year" ? "Target year" : "From"}</span><input type="number" min="1900" max="2200" value={startYear} onChange={(event) => setStartYear(event.target.value)}/></label>{timeframeMode === "range" && <label className="personal-modal-field"><span>To</span><input type="number" min={startYear} max="2200" value={endYear} onChange={(event) => setEndYear(event.target.value)}/></label>}</div>}<footer><button type="button" className="vision-drawer-cancel" onClick={() => setGoalModal(false)}>Cancel</button><button className="personal-primary">Create goal</button></footer></form></aside></div>}
    {uploadWall && <div className="personal-modal-backdrop" onClick={() => !uploading && setUploadWall(null)}><div className="personal-modal" onClick={(event) => event.stopPropagation()}><button className="personal-modal-close" onClick={() => setUploadWall(null)}><X size={18}/></button><span className="personal-modal-icon"><Upload size={20}/></span><h2>Add to {uploadWall.title}</h2><p>Choose one or more images. Up to 10 MB each.</p><button className="vision-dropzone" disabled={uploading} onClick={() => fileRef.current?.click()}><Upload size={24}/><strong>{uploading ? "Uploading…" : "Choose images"}</strong><span>JPG, PNG, WebP or GIF</span></button><input ref={fileRef} hidden type="file" accept="image/*" multiple onChange={(event) => event.target.files && void uploadImages(event.target.files)}/></div></div>}
  </div>;
}

function timeframeLabel(wall: PersonalItem): string {
  if (wall.data.timeframe_mode === "year" && wall.data.start_year) return String(wall.data.start_year);
  if (wall.data.timeframe_mode === "range" && wall.data.start_year && wall.data.end_year) return `${wall.data.start_year}–${wall.data.end_year}`;
  return HORIZONS.find((horizon) => horizon.key === (wall.data.horizon ?? "none"))?.label ?? "No timeframe";
}

function horizonLabel(goal: PersonalItem): string {
  return HORIZONS.find((horizon) => horizon.key === goal.data.horizon)?.label ?? "No timeframe";
}
