"use client";
/* eslint-disable @next/next/no-img-element -- Cloudinary serves optimized cover URLs. */

import { useRef, useState, type FormEvent } from "react";
import { AlertCircle, BookOpen, CalendarDays, CheckCircle2, Library, Plus, Star, Tag, TrendingUp, Upload, X } from "lucide-react";
import type { PersonalItem } from "@/lib/types";

type Props = { items: PersonalItem[]; accessToken: string; onCreated: (item: PersonalItem) => void; onUpdated: (item: PersonalItem) => void };
type Alert = { kind: "success" | "error"; message: string } | null;
type Shelf = "reading" | "finished" | "want_to_read";
const today = () => { const date = new Date(); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`; };

export function ReadingsView({ items, accessToken, onCreated, onUpdated }: Props) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [rating, setRating] = useState(0);
  const [cover, setCover] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [alert, setAlert] = useState<Alert>(null);
  const [progressBook, setProgressBook] = useState<PersonalItem | null>(null);
  const [currentPage, setCurrentPage] = useState("");
  const [activeShelf, setActiveShelf] = useState<Shelf>("reading");
  const [createShelf, setCreateShelf] = useState<Shelf>("reading");
  const timer = useRef<number | null>(null);
  const readings = items.filter((item) => item.kind === "reading");
  const finished = readings.filter((item) => item.data.status === "finished");
  const year = String(new Date().getFullYear());
  const thisYear = finished.filter((item) => String(item.data.finished_at ?? "").startsWith(year));
  const genres = readings.map((item) => String(item.data.genre ?? "").trim()).filter(Boolean);
  const favorite = genres.length ? [...new Set(genres)].sort((a, b) => genres.filter((genre) => genre === b).length - genres.filter((genre) => genre === a).length)[0] : "Not enough data";
  const currentReading = readings.find((item) => item.data.status === "reading") ?? null;
  const readingNow = readings.filter((item) => item.data.status === "reading");
  const wantToRead = readings.filter((item) => !["reading", "finished"].includes(String(item.data.status)));
  const shelfBooks = activeShelf === "reading" ? readingNow : activeShelf === "finished" ? finished : wantToRead;
  const shelves: { key: Shelf; label: string; count: number }[] = [
    { key: "reading", label: "Reading now", count: readingNow.length },
    { key: "finished", label: "Read", count: finished.length },
    { key: "want_to_read", label: "Want to read", count: wantToRead.length },
  ];

  function notify(next: NonNullable<Alert>) {
    if (timer.current) window.clearTimeout(timer.current);
    setAlert(next); timer.current = window.setTimeout(() => setAlert(null), 4500);
  }
  function close() {
    if (pending) return;
    if (preview) URL.revokeObjectURL(preview);
    setCover(null); setPreview(null); setRating(0); setCreateShelf("reading"); setOpen(false);
  }
  function chooseCover(file: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setCover(file); setPreview(file ? URL.createObjectURL(file) : null);
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPending(true);
    const body = new FormData(event.currentTarget); body.set("rating", String(rating));
    if (cover) body.set("cover", cover);
    try {
      const response = await fetch("/api/personal/readings", { method: "POST", headers: { Authorization: `Bearer ${accessToken}` }, body });
      if (!response.ok) { const result = await response.json().catch(() => null); throw new Error(typeof result?.detail === "string" ? result.detail : "Could not save this reading."); }
      onCreated(await response.json()); setPending(false); close(); notify({ kind: "success", message: "Reading added to your library." });
    } catch (error) { setPending(false); notify({ kind: "error", message: error instanceof Error ? error.message : "Could not save this reading." }); }
  }

  function openProgress(book: PersonalItem) {
    setCurrentPage(String(book.data.pages_read ?? 0));
    setProgressBook(book);
  }

  async function saveProgress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!progressBook) return;
    const pages = Number(currentPage);
    const total = Number(progressBook.data.total_pages ?? 0);
    if (!Number.isFinite(pages) || pages < 0 || pages > total) {
      notify({ kind: "error", message: `Current page must be between 0 and ${total}.` });
      return;
    }
    setPending(true);
    const completed = pages === total;
    const data = {
      ...progressBook.data,
      pages_read: pages,
      status: completed ? "finished" : "reading",
      finished_at: completed ? (progressBook.data.finished_at ?? today()) : null,
    };
    try {
      const response = await fetch(`/api/personal/items/${progressBook.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({ data }),
      });
      if (!response.ok) throw new Error("Could not update your reading progress.");
      const updated: PersonalItem = await response.json();
      onUpdated(updated); setPending(false); setProgressBook(null);
      notify({ kind: "success", message: completed ? "Book completed. Well done!" : "Reading progress updated." });
    } catch (error) {
      setPending(false);
      notify({ kind: "error", message: error instanceof Error ? error.message : "Could not update your reading progress." });
    }
  }

  return <section className="readings-view">
    <div className="readings-heading"><div><h2>Your reading life</h2><p>Track what you read and the stories that stay with you.</p></div><button onClick={() => setOpen(true)}><Plus size={17}/>Add reading</button></div>
    <div className="reading-kpis"><Kpi icon={<Library size={19}/>} value={String(finished.length)} label="Books read"/><Kpi icon={<CalendarDays size={19}/>} value={String(thisYear.length)} label={`Read in ${year}`}/><Kpi icon={<Tag size={19}/>} value={favorite} label="Favorite genre" text/></div>
    {currentReading && (() => { const read = Number(currentReading.data.pages_read ?? 0); const total = Number(currentReading.data.total_pages ?? 0); const progress = total ? Math.min(100, Math.round(read / total * 100)) : 0; return <article className="current-reading"><div className="current-reading-cover">{currentReading.data.cover_url ? <img src={String(currentReading.data.cover_url)} alt={`${currentReading.title} cover`}/> : <BookOpen size={34}/>}</div><div className="current-reading-copy"><span>CURRENTLY READING</span><h2>{currentReading.title}</h2><p>{String(currentReading.data.author || "Unknown author")}</p><div className="current-reading-percentage"><strong>{progress}%</strong><small>{read} of {total} pages</small></div><div className="current-reading-progress" aria-label={`${progress}% complete`}><i style={{ width: `${progress}%` }}/></div><button onClick={() => openProgress(currentReading)}><TrendingUp size={16}/>Log progress</button></div></article>; })()}
    <div className="reading-shelves" role="tablist" aria-label="Reading shelves">{shelves.map((shelf) => <button role="tab" aria-selected={activeShelf === shelf.key} className={activeShelf === shelf.key ? "active" : ""} key={shelf.key} onClick={() => setActiveShelf(shelf.key)}><span>{shelf.label}</span><strong>{shelf.count}</strong></button>)}</div>
    <div className="reading-shelf-grid">{shelfBooks.map((book) => <article className="reading-shelf-book" key={book.id}><div className="reading-shelf-cover">{book.data.cover_url ? <img src={String(book.data.cover_url)} alt={`${book.title} cover`}/> : <BookOpen size={30}/>}</div><h3>{book.title}</h3><div className="reading-stars" aria-label={`${Number(book.data.rating ?? 0)} out of 5 stars`}>{[1,2,3,4,5].map((star) => <Star key={star} size={14} fill={star <= Number(book.data.rating ?? 0) ? "currentColor" : "none"}/>)}</div></article>)}{!shelfBooks.length && <div className="reading-empty"><BookOpen size={28}/><strong>No books here yet</strong><span>{activeShelf === "reading" ? "Add a book you are currently reading." : activeShelf === "finished" ? "Finished books will appear here." : "Save the books you want to read next."}</span><button onClick={() => { setCreateShelf(activeShelf); setOpen(true); }}>Add a reading</button></div>}</div>
    {progressBook && <div className="reading-progress-modal-backdrop" onClick={() => !pending && setProgressBook(null)}><form className="reading-progress-modal" onSubmit={saveProgress} onClick={(event) => event.stopPropagation()}><button type="button" className="reading-progress-modal-close" onClick={() => setProgressBook(null)} disabled={pending}><X size={18}/></button><span className="reading-progress-modal-icon"><TrendingUp size={20}/></span><h2>Log reading progress</h2><p>{progressBook.title}</p><label><span>Current page</span><div><input autoFocus type="number" min="0" max={Number(progressBook.data.total_pages ?? 0)} value={currentPage} onChange={(event) => setCurrentPage(event.target.value)} required/><strong>/ {Number(progressBook.data.total_pages ?? 0)}</strong></div></label><button className="reading-save" disabled={pending}>{pending ? "Saving…" : "Save progress"}</button></form></div>}
    {open && <div className="reading-drawer-backdrop" onClick={close}><aside className="reading-drawer" onClick={(event) => event.stopPropagation()}><header><div><span>NEW READING</span><h2>Add to your library</h2></div><button onClick={close} disabled={pending}><X size={19}/></button></header><form onSubmit={submit}>
      <label className="reading-cover-upload"><input type="file" accept="image/*" hidden onChange={(event) => chooseCover(event.target.files?.[0] ?? null)}/>{preview ? <img src={preview} alt="Book cover preview"/> : <><Upload size={22}/><strong>Upload cover</strong><span>JPG, PNG or WebP · max 10 MB</span></>}</label>
      <div className="reading-form-grid"><Field label="Book title"><input name="title" required maxLength={240} placeholder="Atomic Habits"/></Field><Field label="Author"><input name="author" required maxLength={240} placeholder="James Clear"/></Field><Field label="Shelf"><select name="shelf" value={createShelf} onChange={(event) => setCreateShelf(event.target.value as Shelf)}><option value="reading">Reading now</option><option value="finished">Read</option><option value="want_to_read">Want to read</option></select></Field><Field label="Genre"><input name="genre" maxLength={120} placeholder="Self-development"/></Field>{createShelf !== "want_to_read" && <Field label="Started on"><input name="started_at" type="date" required defaultValue={today()}/></Field>}{createShelf === "finished" && <Field label="Finished on"><input name="finished_at" type="date" defaultValue={today()}/></Field>}<Field label="Pages read"><input name="pages_read" type="number" min="0" defaultValue="0" required/></Field><Field label="Total pages"><input name="total_pages" type="number" min="0" required={createShelf !== "want_to_read"} placeholder="320"/></Field></div>
      <fieldset className="reading-rating"><legend>Your rating</legend><div>{[1,2,3,4,5].map((star) => <button type="button" key={star} className={star <= rating ? "active" : ""} aria-label={`${star} star${star > 1 ? "s" : ""}`} onClick={() => setRating(star)}><Star size={25} fill={star <= rating ? "currentColor" : "none"}/></button>)}</div><span>{rating ? `${rating} out of 5` : "Not rated yet"}</span></fieldset>
      <footer><button type="button" className="reading-cancel" onClick={close} disabled={pending}>Cancel</button><button className="reading-save" disabled={pending}>{pending ? "Saving…" : "Save reading"}</button></footer>
    </form></aside></div>}
    {alert && <div className={`reading-alert reading-alert--${alert.kind}`} role="alert">{alert.kind === "success" ? <CheckCircle2 size={19}/> : <AlertCircle size={19}/>}<span>{alert.message}</span><button onClick={() => setAlert(null)}><X size={16}/></button></div>}
  </section>;
}

function Kpi({ icon, value, label, text = false }: { icon: React.ReactNode; value: string; label: string; text?: boolean }) { return <article><span className="reading-kpi-icon">{icon}</span><div><strong className={text ? "reading-kpi-text" : ""}>{value}</strong><span>{label}</span></div></article>; }
function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label><span>{label}</span>{children}</label>; }
