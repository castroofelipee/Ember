"use client";

import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  CheckSquare,
  Clock,
  Columns3,
  FilePlus,
  FileText,
  Folder,
  FolderPlus,
  GripVertical,
  Link2,
  Mail,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  Tag,
  Trash2,
  UserRound,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { useRequireAuth } from "@/lib/auth-client";
import type {
  Board,
  BoardCard,
  BoardColumn,
  ChecklistItem,
  Entity,
  EntityType,
  KnowledgeFolder,
  RelatedEntity,
  Calendar,
} from "@/lib/types";

const MDEditor = dynamic(() => import("@uiw/react-md-editor"), { ssr: false });

const ENTITY_TYPES: { value: EntityType; label: string }[] = [
  { value: "task", label: "Task" },
  { value: "bug", label: "Bug" },
  { value: "idea", label: "Idea" },
  { value: "rfc", label: "RFC" },
  { value: "decision", label: "Decision" },
  { value: "event", label: "Event" },
  { value: "meeting", label: "Meeting" },
  { value: "email", label: "Email" },
  { value: "customer_request", label: "Customer request" },
  { value: "pr", label: "PR" },
  { value: "incident", label: "Incident" },
  { value: "note", label: "Note" },
  { value: "document", label: "Document" },
];

const CARD_TYPES = ENTITY_TYPES.filter((item) => item.value !== "document");
const RELATED_TYPES: { value: EntityType; label: string }[] = [
  { value: "decision", label: "Decision" },
  { value: "event", label: "Event" },
  { value: "email", label: "Email" },
  { value: "document", label: "Document" },
  { value: "task", label: "Task" },
];

type ViewMode = "board" | "docs";
type CardRecurrence = "none" | "daily";
type ColumnDropHint = { columnId: string; edge: "before" | "after" } | null;
type FolderDropTarget = string | "workspace" | null;

function typeLabel(type: EntityType): string {
  return ENTITY_TYPES.find((item) => item.value === type)?.label ?? type;
}

function apiHeaders(accessToken: string | null) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${accessToken}`,
  };
}

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

async function jsonRequest<T>(
  input: RequestInfo | URL,
  init: RequestInit,
  fallback: string,
): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) throw new Error(await responseError(response, fallback));
  return (await response.json()) as T;
}

function stringProp(entity: Entity, key: string): string {
  const value = entity.properties[key];
  return typeof value === "string" ? value : "";
}

function stringListProp(entity: Entity, key: string): string[] {
  const value = entity.properties[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function checklistProp(entity: Entity): ChecklistItem[] {
  const value = entity.properties.checklist;
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const candidate = item as Record<string, unknown>;
      if (typeof candidate.text !== "string") return null;
      return {
        id: typeof candidate.id === "string" ? candidate.id : crypto.randomUUID(),
        text: candidate.text,
        done: candidate.done === true,
      };
    })
    .filter((item): item is ChecklistItem => item !== null);
}

function boolProp(entity: Entity, key: string): boolean {
  return entity.properties[key] === true;
}

function initialForName(name: string): string {
  return name.trim().charAt(0).toUpperCase() || "?";
}

function isFutureDate(value: string): boolean {
  if (!value) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(`${value}T00:00:00`);
  return date.getTime() > today.getTime();
}

function nextDayIsoDate(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  date.setDate(date.getDate() + 1);
  return date.toISOString();
}

/** Local (browser-timezone) calendar-day key, e.g. "2026-07-08". The board
 * reasons about "today" in the user's own timezone (UTC-3 for us) — a daily
 * card resets at their local midnight, not UTC's. */
function localDayKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isDailyRecurring(entity: Entity): boolean {
  return stringProp(entity, "recurrence") === "daily";
}

/** Whether a card counts as done *right now*. A daily-recurring card only
 * stays completed for the local day it was completed on; once the user's
 * clock rolls into the next day it resets so it can be completed again. */
function isEffectivelyCompleted(entity: Entity): boolean {
  if (!boolProp(entity, "completed")) return false;
  if (!isDailyRecurring(entity)) return true;
  const completedAt = stringProp(entity, "completed_at");
  if (!completedAt) return false;
  const completedDate = new Date(completedAt);
  if (Number.isNaN(completedDate.getTime())) return false;
  return localDayKey(completedDate) === localDayKey(new Date());
}

/** A card scheduled for a future day stays hidden from the board until its
 * due date arrives — "appear when it should appear". */
function isScheduledForFuture(entity: Entity): boolean {
  const dueDate = stringProp(entity, "due_date");
  return Boolean(dueDate) && isFutureDate(dueDate);
}

export function BoardsView() {
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { status: authStatus, accessToken } = useRequireAuth();
  const [mode, setMode] = useState<ViewMode>("board");
  const [boards, setBoards] = useState<Board[]>([]);
  const [calendars, setCalendars] = useState<Calendar[]>([]);
  const [folders, setFolders] = useState<KnowledgeFolder[]>([]);
  const [documents, setDocuments] = useState<Entity[]>([]);
  const [activeBoardId, setActiveBoardId] = useState<string | null>(null);
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<Entity | null>(null);
  const [creatingCardColumn, setCreatingCardColumn] = useState<BoardColumn | null>(null);
  const [boardTitle, setBoardTitle] = useState("Product Development");
  const [columnTitle, setColumnTitle] = useState("");
  const [folderTitle, setFolderTitle] = useState("");
  const [documentTitle, setDocumentTitle] = useState("");
  const [draggingEntityId, setDraggingEntityId] = useState<string | null>(null);
  const [draggingColumnId, setDraggingColumnId] = useState<string | null>(null);
  const [columnDropHint, setColumnDropHint] = useState<ColumnDropHint>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeBoard = useMemo(
    () => boards.find((board) => board.id === activeBoardId) ?? boards[0] ?? null,
    [boards, activeBoardId],
  );

  const loadKnowledge = useCallback(async () => {
    if (authStatus !== "ready") return;
    setLoading(true);
    setError(null);
    try {
      const [boardsResponse, calendarsResponse, foldersResponse, documentsResponse] = await Promise.all([
        fetch(`/api/workspaces/${workspaceId}/boards`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
        fetch(`/api/workspaces/${workspaceId}/calendars`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
        fetch(`/api/workspaces/${workspaceId}/folders`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
        fetch(`/api/workspaces/${workspaceId}/entities?type=document`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
      ]);
      if (!boardsResponse.ok || !calendarsResponse.ok || !foldersResponse.ok || !documentsResponse.ok) {
        setError("Could not load workspace knowledge.");
        return;
      }
      const boardItems: Board[] = await boardsResponse.json();
      const calendarItems: Calendar[] = await calendarsResponse.json();
      const folderItems: KnowledgeFolder[] = await foldersResponse.json();
      const documentItems: Entity[] = await documentsResponse.json();
      setBoards(boardItems);
      setCalendars(calendarItems);
      setFolders(folderItems);
      setDocuments(documentItems);
      setActiveBoardId((current) => current ?? boardItems[0]?.id ?? null);
    } finally {
      setLoading(false);
    }
  }, [authStatus, accessToken, workspaceId]);

  useEffect(() => {
    void loadKnowledge();
  }, [loadKnowledge]);

  async function createBoard() {
    if (!boardTitle.trim()) return;
    try {
      const board = await createBoardWithTitle(boardTitle.trim());
      if (board) {
        setBoardTitle("");
        setError(null);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create board.");
    }
  }

  async function createBoardWithTitle(title: string): Promise<Board | null> {
    const board = await jsonRequest<Board>(
      `/api/workspaces/${workspaceId}/boards`,
      {
        method: "POST",
        headers: apiHeaders(accessToken),
        body: JSON.stringify({ title, initial_columns: ["Backlog", "Doing", "Done"] }),
      },
      "Could not create board.",
    );
    setBoards((prev) => [...prev, board]);
    setActiveBoardId(board.id);
    return board;
  }

  async function createColumn() {
    if (!columnTitle.trim()) return;
    try {
      const board = activeBoard ?? (await createBoardWithTitle("Inbox"));
      if (!board) return;
      await jsonRequest<BoardColumn>(
        `/api/workspaces/${workspaceId}/boards/${board.id}/columns`,
        {
          method: "POST",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({ title: columnTitle.trim() }),
        },
        "Could not create column.",
      );
      await refreshBoard(board.id);
      setColumnTitle("");
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create column.");
    }
  }

  async function refreshBoard(boardId: string): Promise<Board> {
    const board = await jsonRequest<Board>(
      `/api/workspaces/${workspaceId}/boards/${boardId}`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
      "Could not refresh board.",
    );
    setBoards((prev) => prev.map((item) => (item.id === board.id ? board : item)));
    return board;
  }

  async function createCard(data: {
    column: BoardColumn;
    title: string;
    type: EntityType;
    labels: string[];
    assignees: string[];
    dueDate: string;
    content: string;
    checklist: ChecklistItem[];
    recurrence: CardRecurrence;
  }) {
    if (!activeBoard || !data.title.trim()) return;
    try {
      const updatedBoard = await jsonRequest<Board>(
        `/api/workspaces/${workspaceId}/boards/${activeBoard.id}/cards/new`,
        {
          method: "POST",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({
            column_id: data.column.id,
            type: data.type,
            title: data.title.trim(),
            content: data.content,
            labels: data.labels,
            assignees: data.assignees,
            due_date: data.dueDate,
            checklist: data.checklist,
            recurrence: data.recurrence,
          }),
        },
        "Could not create card.",
      );
      const createdEntity = updatedBoard.cards.at(-1)?.entity ?? null;
      setBoards((prev) => prev.map((item) => (item.id === updatedBoard.id ? updatedBoard : item)));
      setSelectedEntity(createdEntity);
      setCreatingCardColumn(null);
      if (createdEntity && data.dueDate && isFutureDate(data.dueDate)) {
        try {
          await createCalendarEventForCard(createdEntity, data.dueDate, data.recurrence);
        } catch (error) {
          setError(error instanceof Error ? error.message : "Card created, but calendar event could not be created.");
          return;
        }
      }
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create card.");
    }
  }

  async function createCalendarEventForCard(entity: Entity, dueDate: string, recurrence: CardRecurrence) {
    const calendarId = calendars[0]?.id;
    if (!calendarId) return;
    const response = await fetch(`/api/calendars/${calendarId}/events`, {
      method: "POST",
      headers: apiHeaders(accessToken),
      body: JSON.stringify({
        title: entity.title,
        description: entity.content || null,
        location: null,
        start_at: new Date(`${dueDate}T00:00:00`).toISOString(),
        end_at: nextDayIsoDate(dueDate),
        all_day: true,
        color: "#21103b",
        attendees: [],
        recurrence:
          recurrence === "daily"
            ? { freq: "DAILY", interval: 1, by_weekday: null, count: null, until: null }
            : null,
      }),
    });
    if (!response.ok) {
      throw new Error(await responseError(response, "Card created, but calendar event could not be created."));
    }
  }

  async function updateColumn(column: BoardColumn, title: string) {
    if (!activeBoard || !title.trim()) return;
    try {
      const board = await jsonRequest<Board>(
        `/api/workspaces/${workspaceId}/boards/${activeBoard.id}/columns/${column.id}`,
        {
          method: "PATCH",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({ title: title.trim() }),
        },
        "Could not update column.",
      );
      setBoards((prev) => prev.map((item) => (item.id === board.id ? board : item)));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not update column.");
    }
  }

  async function moveColumn(column: BoardColumn, position: number) {
    if (!activeBoard) return;
    try {
      const board = await jsonRequest<Board>(
        `/api/workspaces/${workspaceId}/boards/${activeBoard.id}/columns/${column.id}`,
        {
          method: "PATCH",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({ position }),
        },
        "Could not move column.",
      );
      setBoards((prev) => prev.map((item) => (item.id === board.id ? board : item)));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not move column.");
    } finally {
      setDraggingColumnId(null);
      setColumnDropHint(null);
    }
  }

  async function deleteColumn(column: BoardColumn) {
    if (!activeBoard) return;
    try {
      const response = await fetch(
        `/api/workspaces/${workspaceId}/boards/${activeBoard.id}/columns/${column.id}`,
        {
          method: "DELETE",
          headers: { Authorization: `Bearer ${accessToken}` },
        },
      );
      if (!response.ok) throw new Error(await responseError(response, "Could not delete column."));
      await refreshBoard(activeBoard.id);
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not delete column.");
    }
  }

  async function moveCard(column: BoardColumn) {
    if (!activeBoard || !draggingEntityId) return;
    const position = activeBoard.cards.filter((card) => card.column_id === column.id).length;
    const response = await fetch(
      `/api/workspaces/${workspaceId}/boards/${activeBoard.id}/cards/${draggingEntityId}`,
      {
        method: "PATCH",
        headers: apiHeaders(accessToken),
        body: JSON.stringify({ column_id: column.id, position }),
      },
    );
    if (response.ok) {
      const board: Board = await response.json();
      setBoards((prev) => prev.map((item) => (item.id === board.id ? board : item)));
    }
    setDraggingEntityId(null);
  }

  function handleColumnDragStart(columnId: string) {
    setDraggingColumnId(columnId);
    setDraggingEntityId(null);
  }

  function handleColumnDragOver(column: BoardColumn, event: DragEvent<HTMLElement>) {
    if (!activeBoard || !draggingColumnId) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const edge = event.clientX < rect.left + rect.width / 2 ? "before" : "after";
    setColumnDropHint({ columnId: column.id, edge });
  }

  async function handleColumnDrop(column: BoardColumn, event: DragEvent<HTMLElement>) {
    if (!activeBoard || !draggingColumnId) return;
    event.preventDefault();
    const dragged = activeBoard.columns.find((item) => item.id === draggingColumnId);
    if (!dragged) return;

    const columns = [...activeBoard.columns].sort((a, b) => a.position - b.position);
    const withoutDragged = columns.filter((item) => item.id !== dragged.id);
    const targetIndex = withoutDragged.findIndex((item) => item.id === column.id);
    if (targetIndex < 0) {
      setDraggingColumnId(null);
      setColumnDropHint(null);
      return;
    }

    const edge =
      columnDropHint?.columnId === column.id
        ? columnDropHint.edge
        : event.clientX < event.currentTarget.getBoundingClientRect().left + event.currentTarget.getBoundingClientRect().width / 2
          ? "before"
          : "after";
    const position = targetIndex + (edge === "after" ? 1 : 0);
    if (position === dragged.position) {
      setDraggingColumnId(null);
      setColumnDropHint(null);
      return;
    }
    await moveColumn(dragged, position);
  }

  async function createFolder() {
    if (!folderTitle.trim()) return;
    try {
      const folder = await jsonRequest<KnowledgeFolder>(
        `/api/workspaces/${workspaceId}/folders`,
        {
          method: "POST",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({ title: folderTitle.trim(), parent_id: activeFolderId }),
        },
        "Could not create folder.",
      );
      setFolders((prev) => [...prev, folder]);
      setActiveFolderId(folder.id);
      setFolderTitle("");
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create folder.");
    }
  }

  async function moveFolder(folderId: string, parentId: string | null) {
    try {
      const folder = await jsonRequest<KnowledgeFolder>(
        `/api/workspaces/${workspaceId}/folders/${folderId}`,
        {
          method: "PATCH",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({ parent_id: parentId }),
        },
        "Could not move folder.",
      );
      setFolders((prev) => prev.map((item) => (item.id === folder.id ? folder : item)));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not move folder.");
    }
  }

  async function createDocument() {
    if (!documentTitle.trim()) return;
    try {
      const document = await jsonRequest<Entity>(
        `/api/workspaces/${workspaceId}/documents`,
        {
          method: "POST",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({
            title: documentTitle.trim(),
            content: `# ${documentTitle.trim()}\n`,
            folder_id: activeFolderId,
          }),
        },
        "Could not create document.",
      );
      setDocuments((prev) => [...prev, document]);
      setSelectedDocument(document);
      setSelectedEntity(null);
      setDocumentTitle("");
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create document.");
    }
  }

  function updateEntityInState(entity: Entity) {
    setSelectedEntity((current) => (current?.id === entity.id ? entity : current));
    setSelectedDocument((current) => (current?.id === entity.id ? entity : current));
    setBoards((prev) =>
      prev.map((board) => ({
        ...board,
        cards: board.cards.map((card) =>
          card.entity.id === entity.id ? { ...card, entity } : card,
        ),
      })),
    );
    setDocuments((prev) => prev.map((document) => (document.id === entity.id ? entity : document)));
  }

  async function closeCard(entity: Entity) {
    try {
      const updated = await jsonRequest<Entity>(
        `/api/workspaces/${workspaceId}/entities/${entity.id}`,
        {
          method: "PATCH",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({
            properties: {
              ...entity.properties,
              completed: true,
              completed_at: new Date().toISOString(),
            },
          }),
        },
        "Could not close card.",
      );
      updateEntityInState(updated);
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not close card.");
    }
  }

  async function deleteCard(entity: Entity) {
    if (!activeBoard) return;
    try {
      const response = await fetch(`/api/workspaces/${workspaceId}/entities/${entity.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (!response.ok) throw new Error(await responseError(response, "Could not delete card."));
      setBoards((prev) =>
        prev.map((board) =>
          board.id === activeBoard.id
            ? { ...board, cards: board.cards.filter((card) => card.entity.id !== entity.id) }
            : board,
        ),
      );
      setSelectedEntity((current) => (current?.id === entity.id ? null : current));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not delete card.");
    }
  }

  if (authStatus !== "ready" || loading) {
    return (
      <div className="knowledge-page knowledge-page--center">
        <p className="mail-empty-title">Loading boards...</p>
      </div>
    );
  }

  if (mode === "docs") {
    return (
      <div className="knowledge-page knowledge-page--docs-only">
        {error && <p className="form-error">{error}</p>}
        <DocsPanel
          folders={folders}
          documents={documents}
          selectedDocument={selectedDocument}
          documentTitle={documentTitle}
          folderTitle={folderTitle}
          activeFolderId={activeFolderId}
          onBack={() => router.push(`/workspace/${workspaceId}`)}
          onDocumentTitleChange={setDocumentTitle}
          onFolderTitleChange={setFolderTitle}
          onCreateDocument={createDocument}
          onCreateFolder={createFolder}
          onMoveFolder={moveFolder}
          onSelectFolder={setActiveFolderId}
          onSelectDocument={(document) => {
            setSelectedDocument(document);
            setSelectedEntity(null);
          }}
          onUpdated={updateEntityInState}
          workspaceId={workspaceId}
          accessToken={accessToken}
        />
      </div>
    );
  }

  return (
    <div className="knowledge-page">
      <aside className="knowledge-nav">
        <div className="knowledge-nav-top">
          <button
            type="button"
            className="mail-icon-button"
            aria-label="Back to calendar"
            onClick={() => router.push(`/workspace/${workspaceId}`)}
          >
            <ArrowLeft size={18} />
          </button>
          <span className="knowledge-brand">Knowledge</span>
        </div>

        <div className="knowledge-tabs">
          <button
            type="button"
            className={mode === "board" ? "knowledge-tab knowledge-tab--active" : "knowledge-tab"}
            onClick={() => setMode("board")}
          >
            <Columns3 size={15} />
            Boards
          </button>
          <button
            type="button"
            className="knowledge-tab"
            onClick={() => setMode("docs")}
          >
            <FileText size={15} />
            Docs
          </button>
        </div>

        <div className="knowledge-create">
          <input
            className="event-dialog-input"
            value={boardTitle}
            onChange={(event) => setBoardTitle(event.target.value)}
            placeholder="Board name"
          />
          <Button type="button" onClick={createBoard}>
            <Plus />
            Board
          </Button>
        </div>

        <div className="knowledge-board-list">
          {boards.map((board) => (
            <button
              type="button"
              key={board.id}
              className={`knowledge-board-button${activeBoard?.id === board.id ? " knowledge-board-button--active" : ""}`}
              onClick={() => setActiveBoardId(board.id)}
            >
              <Columns3 size={16} />
              <span>{board.title}</span>
            </button>
          ))}
        </div>
      </aside>

      <main className="knowledge-main">
        {error && <p className="form-error">{error}</p>}
        <BoardPanel
          activeBoard={activeBoard}
          columnTitle={columnTitle}
          selectedEntity={selectedEntity}
          onColumnTitleChange={setColumnTitle}
          onCreateColumn={createColumn}
          onCreateCard={(column) => setCreatingCardColumn(column)}
          onUpdateColumn={updateColumn}
          onDeleteColumn={deleteColumn}
          onDragStart={(entityId) => {
            setDraggingEntityId(entityId);
            setDraggingColumnId(null);
            setColumnDropHint(null);
          }}
          onDropColumn={moveCard}
          draggingColumnId={draggingColumnId}
          columnDropHint={columnDropHint}
          onColumnDragStart={handleColumnDragStart}
          onColumnDragOver={handleColumnDragOver}
          onColumnDrop={handleColumnDrop}
          onColumnDragEnd={() => {
            setDraggingColumnId(null);
            setColumnDropHint(null);
          }}
          onSelectEntity={setSelectedEntity}
          onCloseCard={closeCard}
          onDeleteCard={deleteCard}
        />
      </main>

      {selectedEntity && selectedEntity.type !== "document" && (
        <EntityDrawer
          workspaceId={workspaceId}
          accessToken={accessToken}
          entity={selectedEntity}
          onClose={() => setSelectedEntity(null)}
          onUpdated={updateEntityInState}
          onClosed={closeCard}
          onDeleted={deleteCard}
          onRelatedCreated={updateEntityInState}
        />
      )}
      {creatingCardColumn && activeBoard && (
        <CardCreateDrawer
          column={creatingCardColumn}
          onClose={() => setCreatingCardColumn(null)}
          onCreate={createCard}
        />
      )}
    </div>
  );
}

function BoardPanel({
  activeBoard,
  columnTitle,
  selectedEntity,
  draggingColumnId,
  columnDropHint,
  onColumnTitleChange,
  onCreateColumn,
  onCreateCard,
  onUpdateColumn,
  onDeleteColumn,
  onDragStart,
  onDropColumn,
  onColumnDragStart,
  onColumnDragOver,
  onColumnDrop,
  onColumnDragEnd,
  onSelectEntity,
  onCloseCard,
  onDeleteCard,
}: {
  activeBoard: Board | null;
  columnTitle: string;
  selectedEntity: Entity | null;
  draggingColumnId: string | null;
  columnDropHint: ColumnDropHint;
  onColumnTitleChange: (value: string) => void;
  onCreateColumn: () => void;
  onCreateCard: (column: BoardColumn) => void;
  onUpdateColumn: (column: BoardColumn, title: string) => void;
  onDeleteColumn: (column: BoardColumn) => void;
  onDragStart: (entityId: string) => void;
  onDropColumn: (column: BoardColumn) => void;
  onColumnDragStart: (columnId: string) => void;
  onColumnDragOver: (column: BoardColumn, event: DragEvent<HTMLElement>) => void;
  onColumnDrop: (column: BoardColumn, event: DragEvent<HTMLElement>) => void;
  onColumnDragEnd: () => void;
  onSelectEntity: (entity: Entity) => void;
  onCloseCard: (entity: Entity) => void;
  onDeleteCard: (entity: Entity) => void;
}) {
  if (!activeBoard) {
    return (
      <section className="knowledge-empty knowledge-empty--compact">
        <Columns3 size={24} />
        <h1>Create a board</h1>
        <p>Create a board to start with editable workflow columns, then add your own columns.</p>
      </section>
    );
  }

  return (
    <>
      <header className="knowledge-header">
        <div>
          <p className="mail-list-kicker">Workspace board</p>
          <h1>{activeBoard.title}</h1>
        </div>
      </header>

      <div className="knowledge-column-create">
        <input
          className="event-dialog-input"
          value={columnTitle}
          onChange={(event) => onColumnTitleChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") onCreateColumn();
          }}
          placeholder="Column name, e.g. Backlog, Blocked, Done"
        />
        <Button type="button" onClick={onCreateColumn}>
          <Plus />
          Column
        </Button>
      </div>

      {activeBoard.columns.length === 0 ? (
        <section className="knowledge-empty knowledge-empty--compact">
          <Columns3 size={24} />
          <h1>Create your first column</h1>
          <p>This board has no predefined workflow. Add the columns that match your process.</p>
        </section>
      ) : (
        <section className="knowledge-board">
          {[...activeBoard.columns].sort((a, b) => a.position - b.position).map((column) => {
            const columnCards = activeBoard.cards
              .filter((card) => card.column_id === column.id)
              .sort((a, b) => a.position - b.position);
            // Future-scheduled cards are held back until their due date.
            const cards = columnCards.filter((card) => !isScheduledForFuture(card.entity));
            const scheduledCount = columnCards.length - cards.length;
            const dropClass =
              columnDropHint?.columnId === column.id
                ? ` knowledge-column--drop-${columnDropHint.edge}`
                : "";
            return (
              <div
                className={`knowledge-column${draggingColumnId === column.id ? " knowledge-column--dragging" : ""}${dropClass}`}
                key={column.id}
                onDragOver={(event) => {
                  event.preventDefault();
                  if (draggingColumnId) onColumnDragOver(column, event);
                }}
                onDrop={(event) => {
                  if (draggingColumnId) {
                    void onColumnDrop(column, event);
                    return;
                  }
                  onDropColumn(column);
                }}
              >
                <ColumnHeader
                  column={column}
                  count={cards.length}
                  scheduledCount={scheduledCount}
                  onUpdate={onUpdateColumn}
                  onDelete={onDeleteColumn}
                  onDragStart={onColumnDragStart}
                  onDragEnd={onColumnDragEnd}
                />
                <div className="knowledge-card-list">
                  {cards.map((card) => (
                    <BoardCardView
                      key={card.entity.id}
                      card={card}
                      active={selectedEntity?.id === card.entity.id}
                      onSelect={() => onSelectEntity(card.entity)}
                      onDragStart={(event) => {
                        event.dataTransfer.setData("application/x-ember-board-card", card.entity.id);
                        onDragStart(card.entity.id);
                      }}
                      onClose={() => onCloseCard(card.entity)}
                      onDelete={() => onDeleteCard(card.entity)}
                    />
                  ))}
                  <button
                    type="button"
                    className="knowledge-add-card"
                    onClick={() => onCreateCard(column)}
                  >
                    <Plus size={15} />
                    Add card
                  </button>
                </div>
              </div>
            );
          })}
        </section>
      )}
    </>
  );
}

function ColumnHeader({
  column,
  count,
  scheduledCount = 0,
  onUpdate,
  onDelete,
  onDragStart,
  onDragEnd,
}: {
  column: BoardColumn;
  count: number;
  scheduledCount?: number;
  onUpdate: (column: BoardColumn, title: string) => void;
  onDelete: (column: BoardColumn) => void;
  onDragStart: (columnId: string) => void;
  onDragEnd: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(column.title);

  useEffect(() => {
    setTitle(column.title);
  }, [column.title]);

  return (
    <div className="knowledge-column-head">
      <button
        type="button"
        className="knowledge-column-drag"
        draggable
        aria-label="Move column"
        onDragStart={(event) => {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("application/x-ember-board-column", column.id);
          onDragStart(column.id);
        }}
        onDragEnd={onDragEnd}
      >
        <GripVertical size={15} />
      </button>
      {editing ? (
        <input
          className="event-dialog-input"
          value={title}
          autoFocus
          onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              onUpdate(column, title);
              setEditing(false);
            }
            if (event.key === "Escape") {
              setTitle(column.title);
              setEditing(false);
            }
          }}
          onBlur={() => {
            if (title.trim() && title.trim() !== column.title) onUpdate(column, title);
            else setTitle(column.title);
            setEditing(false);
          }}
        />
      ) : (
        <h2>{column.title}</h2>
      )}
      <div className="knowledge-column-actions">
        <span>{count}</span>
        {scheduledCount > 0 && (
          <span
            className="knowledge-column-scheduled"
            title={`${scheduledCount} scheduled for a future day`}
          >
            <Clock size={12} />
            {scheduledCount}
          </span>
        )}
        <button type="button" aria-label="Edit column" onClick={() => setEditing(true)}>
          <Pencil size={14} />
        </button>
        <button type="button" aria-label="Delete column" onClick={() => onDelete(column)}>
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}

function DocsPanel({
  folders,
  documents,
  selectedDocument,
  documentTitle,
  folderTitle,
  activeFolderId,
  workspaceId,
  accessToken,
  onBack,
  onDocumentTitleChange,
  onFolderTitleChange,
  onCreateDocument,
  onCreateFolder,
  onMoveFolder,
  onSelectFolder,
  onSelectDocument,
  onUpdated,
}: {
  folders: KnowledgeFolder[];
  documents: Entity[];
  selectedDocument: Entity | null;
  documentTitle: string;
  folderTitle: string;
  activeFolderId: string | null;
  workspaceId: string;
  accessToken: string | null;
  onBack: () => void;
  onDocumentTitleChange: (value: string) => void;
  onFolderTitleChange: (value: string) => void;
  onCreateDocument: () => void;
  onCreateFolder: () => void;
  onMoveFolder: (folderId: string, parentId: string | null) => void;
  onSelectFolder: (folderId: string | null) => void;
  onSelectDocument: (entity: Entity) => void;
  onUpdated: (entity: Entity) => void;
}) {
  const [openFolderIds, setOpenFolderIds] = useState<Set<string>>(() => new Set());
  const [draggingFolderId, setDraggingFolderId] = useState<string | null>(null);
  const [folderDropTarget, setFolderDropTarget] = useState<FolderDropTarget>(null);
  const rootDocuments = documents.filter((document) => !stringProp(document, "folder_id"));
  const folderIds = useMemo(() => new Set(folders.map((folder) => folder.id)), [folders]);
  const rootFolders = useMemo(
    () => folders.filter((folder) => !folder.parent_id || !folderIds.has(folder.parent_id)),
    [folderIds, folders],
  );
  const childFolderMap = useMemo(() => {
    const map = new Map<string, KnowledgeFolder[]>();
    folders.forEach((folder) => {
      if (!folder.parent_id) return;
      map.set(folder.parent_id, [...(map.get(folder.parent_id) ?? []), folder]);
    });
    return map;
  }, [folders]);
  const folderDocumentMap = useMemo(() => {
    const map = new Map<string, Entity[]>();
    folders.forEach((folder) => map.set(folder.id, []));
    documents.forEach((document) => {
      const folderId = stringProp(document, "folder_id");
      if (!folderId) return;
      map.set(folderId, [...(map.get(folderId) ?? []), document]);
    });
    return map;
  }, [documents, folders]);
  const activeFolder = folders.find((folder) => folder.id === activeFolderId) ?? null;
  const createTarget = activeFolder?.title ?? "Workspace";

  function toggleFolder(folderId: string) {
    setOpenFolderIds((current) => {
      const next = new Set(current);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  }

  function canMoveFolder(folderId: string, targetParentId: string | null) {
    if (folderId === targetParentId) return false;
    const parentById = new Map(folders.map((folder) => [folder.id, folder.parent_id]));
    let cursor = targetParentId;
    while (cursor) {
      if (cursor === folderId) return false;
      cursor = parentById.get(cursor) ?? null;
    }
    return true;
  }

  function handleFolderDrop(targetParentId: string | null) {
    if (!draggingFolderId || !canMoveFolder(draggingFolderId, targetParentId)) {
      setDraggingFolderId(null);
      setFolderDropTarget(null);
      return;
    }
    onMoveFolder(draggingFolderId, targetParentId);
    if (targetParentId) {
      setOpenFolderIds((current) => new Set(current).add(targetParentId));
    }
    setDraggingFolderId(null);
    setFolderDropTarget(null);
  }

  return (
    <div className="knowledge-doc-layout">
      <aside className="knowledge-doc-explorer">
        <div className="knowledge-doc-explorer-head">
          <button
            type="button"
            className="mail-icon-button"
            aria-label="Back to calendar"
            onClick={onBack}
          >
            <ArrowLeft size={18} />
          </button>
          <span>Files</span>
          <FileText size={15} />
        </div>

        <div className="knowledge-doc-create-row">
          <input
            className="event-dialog-input"
            value={documentTitle}
            onChange={(event) => onDocumentTitleChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onCreateDocument();
            }}
            placeholder={`Document in ${createTarget}`}
          />
          <button type="button" aria-label="Create document" onClick={onCreateDocument}>
            <FilePlus size={15} />
          </button>
        </div>
        <div className="knowledge-doc-create-row">
          <input
            className="event-dialog-input"
            value={folderTitle}
            onChange={(event) => onFolderTitleChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onCreateFolder();
            }}
            placeholder={`Folder in ${createTarget}`}
          />
          <button type="button" aria-label="Create folder" onClick={onCreateFolder}>
            <FolderPlus size={15} />
          </button>
        </div>

        <nav className="knowledge-doc-tree" aria-label="Documents">
          <button
            type="button"
            className={`knowledge-doc-workspace${activeFolderId === null ? " knowledge-doc-workspace--active" : ""}${
              folderDropTarget === "workspace" ? " knowledge-doc-workspace--drop" : ""
            }`}
            onClick={() => onSelectFolder(null)}
            onDragOver={(event) => {
              if (!draggingFolderId) return;
              event.preventDefault();
              setFolderDropTarget("workspace");
            }}
            onDrop={(event) => {
              event.preventDefault();
              handleFolderDrop(null);
            }}
          >
            <Folder size={15} />
            <span>Workspace</span>
          </button>
          {rootFolders.map((folder) => (
            <FolderTreeItem
              key={folder.id}
              folder={folder}
              activeFolderId={activeFolderId}
              selectedDocument={selectedDocument}
              openFolderIds={openFolderIds}
              draggingFolderId={draggingFolderId}
              folderDropTarget={folderDropTarget}
              childFolderMap={childFolderMap}
              folderDocumentMap={folderDocumentMap}
              onSelectFolder={onSelectFolder}
              onSelectDocument={onSelectDocument}
              onToggleFolder={toggleFolder}
              onDragStart={setDraggingFolderId}
              onDragEnd={() => {
                setDraggingFolderId(null);
                setFolderDropTarget(null);
              }}
              onDragOverFolder={setFolderDropTarget}
              onDropFolder={handleFolderDrop}
            />
          ))}
          {rootDocuments.map((document) => (
            <DocTreeItem
              key={document.id}
              document={document}
              active={selectedDocument?.id === document.id}
              onSelect={() => onSelectDocument(document)}
            />
          ))}
        </nav>
      </aside>

      {selectedDocument ? (
        <DocumentEditor
          workspaceId={workspaceId}
          accessToken={accessToken}
          document={selectedDocument}
          onUpdated={onUpdated}
        />
      ) : (
        <section className="knowledge-doc-editor knowledge-doc-editor--empty">
          <FileText size={24} />
          <h2>No file is open</h2>
        </section>
      )}
    </div>
  );
}

function FolderTreeItem({
  folder,
  activeFolderId,
  selectedDocument,
  openFolderIds,
  draggingFolderId,
  folderDropTarget,
  childFolderMap,
  folderDocumentMap,
  onSelectFolder,
  onSelectDocument,
  onToggleFolder,
  onDragStart,
  onDragEnd,
  onDragOverFolder,
  onDropFolder,
}: {
  folder: KnowledgeFolder;
  activeFolderId: string | null;
  selectedDocument: Entity | null;
  openFolderIds: Set<string>;
  draggingFolderId: string | null;
  folderDropTarget: FolderDropTarget;
  childFolderMap: Map<string, KnowledgeFolder[]>;
  folderDocumentMap: Map<string, Entity[]>;
  onSelectFolder: (folderId: string) => void;
  onSelectDocument: (entity: Entity) => void;
  onToggleFolder: (folderId: string) => void;
  onDragStart: (folderId: string) => void;
  onDragEnd: () => void;
  onDragOverFolder: (folderId: string) => void;
  onDropFolder: (folderId: string) => void;
}) {
  const childFolders = childFolderMap.get(folder.id) ?? [];
  const folderDocuments = folderDocumentMap.get(folder.id) ?? [];
  const hasChildren = childFolders.length > 0 || folderDocuments.length > 0;
  const isOpen = openFolderIds.has(folder.id);

  return (
    <div className="knowledge-doc-tree-section">
      <button
        type="button"
        className={`knowledge-doc-folder${activeFolderId === folder.id ? " knowledge-doc-folder--active" : ""}${
          draggingFolderId === folder.id ? " knowledge-doc-folder--dragging" : ""
        }${folderDropTarget === folder.id ? " knowledge-doc-folder--drop" : ""}`}
        draggable
        onDragStart={(event) => {
          event.stopPropagation();
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("application/x-ember-folder", folder.id);
          onDragStart(folder.id);
        }}
        onDragEnd={onDragEnd}
        onDragOver={(event) => {
          if (!draggingFolderId || draggingFolderId === folder.id) return;
          event.preventDefault();
          onDragOverFolder(folder.id);
        }}
        onDrop={(event) => {
          event.preventDefault();
          event.stopPropagation();
          onDropFolder(folder.id);
        }}
        onClick={() => onSelectFolder(folder.id)}
      >
        <span
          className="knowledge-doc-folder-toggle"
          onClick={(event) => {
            event.stopPropagation();
            if (hasChildren) onToggleFolder(folder.id);
          }}
        >
          {hasChildren && (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />)}
        </span>
        <Folder size={15} />
        <span>{folder.title}</span>
      </button>
      {isOpen && hasChildren && (
        <div className="knowledge-doc-tree-children">
          {childFolders.map((child) => (
            <FolderTreeItem
              key={child.id}
              folder={child}
              activeFolderId={activeFolderId}
              selectedDocument={selectedDocument}
              openFolderIds={openFolderIds}
              draggingFolderId={draggingFolderId}
              folderDropTarget={folderDropTarget}
              childFolderMap={childFolderMap}
              folderDocumentMap={folderDocumentMap}
              onSelectFolder={onSelectFolder}
              onSelectDocument={onSelectDocument}
              onToggleFolder={onToggleFolder}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              onDragOverFolder={onDragOverFolder}
              onDropFolder={onDropFolder}
            />
          ))}
          {folderDocuments.map((document) => (
            <DocTreeItem
              key={document.id}
              document={document}
              active={selectedDocument?.id === document.id}
              onSelect={() => onSelectDocument(document)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DocTreeItem({
  document,
  active,
  onSelect,
}: {
  document: Entity;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`knowledge-doc-file${active ? " knowledge-doc-file--active" : ""}`}
      onClick={onSelect}
    >
      <FileText size={14} />
      <span>{document.title}</span>
    </button>
  );
}

function DocumentEditor({
  workspaceId,
  accessToken,
  document,
  onUpdated,
}: {
  workspaceId: string;
  accessToken: string | null;
  document: Entity;
  onUpdated: (entity: Entity) => void;
}) {
  const [title, setTitle] = useState(document.title);
  const [content, setContent] = useState(document.content);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTitle(document.title);
    setContent(document.content);
    setError(null);
  }, [document]);

  async function saveDocument() {
    const response = await fetch(`/api/workspaces/${workspaceId}/entities/${document.id}`, {
      method: "PATCH",
      headers: apiHeaders(accessToken),
      body: JSON.stringify({
        title,
        content,
        properties: document.properties,
      }),
    });
    if (!response.ok) {
      setError(await responseError(response, "Could not save document."));
      return;
    }
    const updated: Entity = await response.json();
    onUpdated(updated);
    setError(null);
  }

  return (
    <section className="knowledge-doc-editor">
      <div className="knowledge-doc-editor-top">
        <input
          className="knowledge-doc-title-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <Button type="button" onClick={saveDocument}>
          <Save />
          Save
        </Button>
      </div>
      {error && <p className="form-error">{error}</p>}
      <div className="knowledge-doc-md-editor" data-color-mode="dark">
        <MDEditor
          value={content}
          onChange={(value) => setContent(value ?? "")}
          preview="edit"
          visibleDragbar={false}
          textareaProps={{ spellCheck: false }}
          height="100%"
        />
      </div>
    </section>
  );
}

function BoardCardView({
  card,
  active,
  onSelect,
  onDragStart,
  onClose,
  onDelete,
}: {
  card: BoardCard;
  active: boolean;
  onSelect: () => void;
  onDragStart: (event: DragEvent<HTMLElement>) => void;
  onClose: () => void;
  onDelete: () => void;
}) {
  const labels = stringListProp(card.entity, "labels");
  const assignees = stringListProp(card.entity, "assignees");
  const done = checklistProp(card.entity).filter((item) => item.done).length;
  const total = checklistProp(card.entity).length;
  const completed = isEffectivelyCompleted(card.entity);
  const recurringDaily = isDailyRecurring(card.entity);

  return (
    <article
      className={`knowledge-card${active ? " knowledge-card--active" : ""}${completed ? " knowledge-card--completed" : ""}`}
      draggable
      role="button"
      tabIndex={0}
      onDragStart={onDragStart}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      <span className="knowledge-card-topline">
        <span className="knowledge-card-type">
          {completed ? "Completed" : typeLabel(card.entity.type)}
          {recurringDaily && (
            <span className="knowledge-card-recurring" title="Repeats every day">
              <RefreshCw size={11} />
              Daily
            </span>
          )}
        </span>
        <span className="knowledge-card-actions">
          {!completed && (
            <button
              type="button"
              aria-label="Close card as completed"
              onClick={(event) => {
                event.stopPropagation();
                onClose();
              }}
            >
              <CheckCircle2 size={14} />
            </button>
          )}
          <button
            type="button"
            aria-label="Delete card"
            onClick={(event) => {
              event.stopPropagation();
              onDelete();
            }}
          >
            <Trash2 size={14} />
          </button>
        </span>
      </span>
      <strong>{card.entity.title}</strong>
      {card.entity.content && <span className="knowledge-card-preview">{card.entity.content}</span>}
      {labels.length > 0 && (
        <span className="knowledge-card-labels">
          {labels.map((label) => (
            <span key={label}>{label}</span>
          ))}
        </span>
      )}
      <span className="knowledge-card-meta">
        {total > 0 && (
          <span>
            <CheckSquare size={13} /> {done}/{total}
          </span>
        )}
        {assignees.length > 0 && (
          <span className="knowledge-assignee-list">
            {assignees.map((assignee) => (
              <span className="knowledge-assignee" key={assignee} title={assignee}>
                <span className="knowledge-assignee-avatar">{initialForName(assignee)}</span>
                {assignee}
              </span>
            ))}
          </span>
        )}
      </span>
    </article>
  );
}

function CardCreateDrawer({
  column,
  onClose,
  onCreate,
}: {
  column: BoardColumn;
  onClose: () => void;
  onCreate: (data: {
    column: BoardColumn;
    title: string;
    type: EntityType;
    labels: string[];
    assignees: string[];
    dueDate: string;
    content: string;
    checklist: ChecklistItem[];
    recurrence: CardRecurrence;
  }) => void;
}) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState<EntityType>("task");
  const [labelsInput, setLabelsInput] = useState("");
  const [assigneesInput, setAssigneesInput] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [recurrence, setRecurrence] = useState<CardRecurrence>("none");
  const [content, setContent] = useState("");
  const [checklist, setChecklist] = useState<ChecklistItem[]>([]);
  const [checklistInput, setChecklistInput] = useState("");

  function addChecklistItem() {
    const text = checklistInput.trim();
    if (!text) return;
    setChecklist((prev) => [...prev, { id: crypto.randomUUID(), text, done: false }]);
    setChecklistInput("");
  }

  function create() {
    onCreate({
      column,
      title,
      type,
      labels: labelsInput.split(",").map((item) => item.trim()).filter(Boolean),
      assignees: assigneesInput.split(",").map((item) => item.trim()).filter(Boolean),
      dueDate,
      content,
      checklist,
      recurrence,
    });
  }

  return (
    <aside className="knowledge-drawer">
      <div className="knowledge-drawer-top">
        <div>
          <p className="mail-list-kicker">{column.title}</p>
          <h2>Create card</h2>
        </div>
        <button type="button" className="mail-icon-button" aria-label="Close" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <div className="knowledge-drawer-body">
        <label className="event-dialog-field">
          <span className="event-dialog-label">Title</span>
          <input
            className="event-dialog-input"
            value={title}
            autoFocus
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Task title"
          />
        </label>
        <label className="event-dialog-field">
          <span className="event-dialog-label">Type</span>
          <select
            className="event-dialog-input"
            value={type}
            onChange={(event) => setType(event.target.value as EntityType)}
          >
            {CARD_TYPES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <div className="knowledge-editor-grid">
          <label className="event-dialog-field">
            <span className="event-dialog-label">
              <Tag size={14} />
              Labels
            </span>
            <input
              className="event-dialog-input"
              value={labelsInput}
              onChange={(event) => setLabelsInput(event.target.value)}
              placeholder="frontend, urgent"
            />
          </label>
          <label className="event-dialog-field">
            <span className="event-dialog-label">
              <UserRound size={14} />
              Responsible
            </span>
            <input
              className="event-dialog-input"
              value={assigneesInput}
              onChange={(event) => setAssigneesInput(event.target.value)}
              placeholder="Felipe"
            />
          </label>
        </div>
        <label className="event-dialog-field">
          <span className="event-dialog-label">
            <CalendarDays size={14} />
            Due date
          </span>
          <input
            type="date"
            className="event-dialog-input"
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
          />
        </label>
        <label className="event-dialog-field">
          <span className="event-dialog-label">Recurrence</span>
          <select
            className="event-dialog-input"
            value={recurrence}
            onChange={(event) => setRecurrence(event.target.value as CardRecurrence)}
          >
            <option value="none">No recurrence</option>
            <option value="daily">Every day</option>
          </select>
        </label>
        <section className="knowledge-checklist">
          <div className="knowledge-related-head">
            <h3>Checklist</h3>
            <span>{checklist.length}</span>
          </div>
          {checklist.map((item) => (
            <label className="knowledge-checklist-item" key={item.id}>
              <input
                type="checkbox"
                checked={item.done}
                onChange={(event) =>
                  setChecklist((prev) =>
                    prev.map((candidate) =>
                      candidate.id === item.id ? { ...candidate, done: event.target.checked } : candidate,
                    ),
                  )
                }
              />
              <span>{item.text}</span>
              <button
                type="button"
                aria-label="Remove checklist item"
                onClick={() => setChecklist((prev) => prev.filter((candidate) => candidate.id !== item.id))}
              >
                <X size={13} />
              </button>
            </label>
          ))}
          <div className="knowledge-inline-create">
            <input
              className="event-dialog-input"
              value={checklistInput}
              onChange={(event) => setChecklistInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") addChecklistItem();
              }}
              placeholder="Checklist item"
            />
            <Button type="button" onClick={addChecklistItem}>
              <Plus />
            </Button>
          </div>
        </section>
        <label className="event-dialog-field">
          <span className="event-dialog-label">
            <FileText size={14} />
            Markdown
          </span>
          <textarea
            className="event-dialog-input knowledge-markdown"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="Reference context with [[Entity title]]"
          />
        </label>
        <Button type="button" onClick={create} disabled={!title.trim()}>
          <Save />
          Create card
        </Button>
      </div>
    </aside>
  );
}

function EntityDrawer({
  workspaceId,
  accessToken,
  entity,
  onClose,
  onUpdated,
  onClosed,
  onDeleted,
  onRelatedCreated,
}: {
  workspaceId: string;
  accessToken: string;
  entity: Entity;
  onClose: () => void;
  onUpdated: (entity: Entity) => void;
  onClosed: (entity: Entity) => void;
  onDeleted: (entity: Entity) => void;
  onRelatedCreated: (entity: Entity) => void;
}) {
  const [title, setTitle] = useState(entity.title);
  const [type, setType] = useState<EntityType>(entity.type);
  const [content, setContent] = useState(entity.content);
  const [labelsInput, setLabelsInput] = useState(stringListProp(entity, "labels").join(", "));
  const [assigneesInput, setAssigneesInput] = useState(stringListProp(entity, "assignees").join(", "));
  const [dueDate, setDueDate] = useState(stringProp(entity, "due_date"));
  const [recurrence, setRecurrence] = useState<CardRecurrence>(
    stringProp(entity, "recurrence") === "daily" ? "daily" : "none",
  );
  const [checklist, setChecklist] = useState<ChecklistItem[]>(checklistProp(entity));
  const [checklistInput, setChecklistInput] = useState("");
  const [related, setRelated] = useState<RelatedEntity[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Entity[]>([]);
  const [relatedTitle, setRelatedTitle] = useState("");
  const [relatedType, setRelatedType] = useState<EntityType>("decision");
  const [drawerError, setDrawerError] = useState<string | null>(null);

  const loadRelated = useCallback(async () => {
    const response = await fetch(
      `/api/workspaces/${workspaceId}/entities/${entity.id}/related`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    if (response.ok) setRelated(await response.json());
  }, [accessToken, entity.id, workspaceId]);

  useEffect(() => {
    setTitle(entity.title);
    setType(entity.type);
    setContent(entity.content);
    setLabelsInput(stringListProp(entity, "labels").join(", "));
    setAssigneesInput(stringListProp(entity, "assignees").join(", "));
    setDueDate(stringProp(entity, "due_date"));
    setRecurrence(stringProp(entity, "recurrence") === "daily" ? "daily" : "none");
    setChecklist(checklistProp(entity));
    setDrawerError(null);
    void loadRelated();
  }, [entity, loadRelated]);

  async function saveEntity() {
    const labels = labelsInput.split(",").map((item) => item.trim()).filter(Boolean);
    const assignees = assigneesInput.split(",").map((item) => item.trim()).filter(Boolean);
    const response = await fetch(`/api/workspaces/${workspaceId}/entities/${entity.id}`, {
      method: "PATCH",
      headers: apiHeaders(accessToken),
      body: JSON.stringify({
        title,
        type,
        content,
        properties: {
          ...entity.properties,
          labels,
          assignees,
          due_date: dueDate,
          checklist,
          recurrence,
        },
      }),
    });
    if (!response.ok) {
      setDrawerError(await responseError(response, "Could not save entity."));
      return;
    }
    const updated: Entity = await response.json();
    onUpdated(updated);
    setDrawerError(null);
    await loadRelated();
  }

  async function searchEntities(value: string) {
    setQuery(value);
    if (!value.trim()) {
      setResults([]);
      return;
    }
    const response = await fetch(
      `/api/workspaces/${workspaceId}/search?q=${encodeURIComponent(value.trim())}`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    );
    if (response.ok) {
      const items: Entity[] = await response.json();
      setResults(items.filter((item) => item.id !== entity.id));
    }
  }

  async function linkEntity(target: Entity) {
    const response = await fetch(`/api/workspaces/${workspaceId}/entities/${entity.id}/relations`, {
      method: "POST",
      headers: apiHeaders(accessToken),
      body: JSON.stringify({ to_entity_id: target.id, relation_type: "references" }),
    });
    if (response.ok || response.status === 409) {
      setQuery("");
      setResults([]);
      await loadRelated();
    }
  }

  async function createRelatedEntity() {
    if (!relatedTitle.trim()) return;
    const response = await fetch(`/api/workspaces/${workspaceId}/entities`, {
      method: "POST",
      headers: apiHeaders(accessToken),
      body: JSON.stringify({
        type: relatedType,
        title: relatedTitle.trim(),
        content: "",
        properties: {
          source:
            relatedType === "email"
              ? "email_reference"
              : relatedType === "event"
                ? "event_reference"
                : "manual",
        },
      }),
    });
    if (!response.ok) {
      setDrawerError(await responseError(response, "Could not create related entity."));
      return;
    }
    const created: Entity = await response.json();
    await linkEntity(created);
    onRelatedCreated(created);
    setRelatedTitle("");
    setDrawerError(null);
  }

  function addChecklistItem() {
    const text = checklistInput.trim();
    if (!text) return;
    setChecklist((prev) => [...prev, { id: crypto.randomUUID(), text, done: false }]);
    setChecklistInput("");
  }

  return (
    <aside className="knowledge-drawer">
      <div className="knowledge-drawer-top">
        <div>
          <p className="mail-list-kicker">Entity</p>
          <h2>{entity.title}</h2>
        </div>
        <button type="button" className="mail-icon-button" aria-label="Close" onClick={onClose}>
          <X size={18} />
        </button>
      </div>

      <div className="knowledge-drawer-body">
        {drawerError && <p className="form-error">{drawerError}</p>}
        <div className="knowledge-drawer-actions">
          {!isEffectivelyCompleted(entity) && (
            <Button type="button" onClick={() => onClosed(entity)}>
              <CheckCircle2 />
              Complete
            </Button>
          )}
          <button
            type="button"
            className="knowledge-danger-button"
            onClick={() => onDeleted(entity)}
          >
            <Trash2 size={16} />
            Delete
          </button>
        </div>

        <label className="event-dialog-field">
          <span className="event-dialog-label">Title</span>
          <input className="event-dialog-input" value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>

        <label className="event-dialog-field">
          <span className="event-dialog-label">Type</span>
          <select
            className="event-dialog-input"
            value={type}
            onChange={(event) => setType(event.target.value as EntityType)}
          >
            {ENTITY_TYPES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <div className="knowledge-editor-grid">
          <label className="event-dialog-field">
            <span className="event-dialog-label">
              <Tag size={14} />
              Labels
            </span>
            <input
              className="event-dialog-input"
              value={labelsInput}
              onChange={(event) => setLabelsInput(event.target.value)}
              placeholder="frontend, urgent"
            />
          </label>
          <label className="event-dialog-field">
            <span className="event-dialog-label">
              <UserRound size={14} />
              Responsible
            </span>
            <input
              className="event-dialog-input"
              value={assigneesInput}
              onChange={(event) => setAssigneesInput(event.target.value)}
              placeholder="Felipe, Ana"
            />
          </label>
        </div>

        <label className="event-dialog-field">
          <span className="event-dialog-label">
            <CalendarDays size={14} />
            Due date
          </span>
          <input
            type="date"
            className="event-dialog-input"
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
          />
        </label>
        <label className="event-dialog-field">
          <span className="event-dialog-label">Recurrence</span>
          <select
            className="event-dialog-input"
            value={recurrence}
            onChange={(event) => setRecurrence(event.target.value as CardRecurrence)}
          >
            <option value="none">No recurrence</option>
            <option value="daily">Every day</option>
          </select>
        </label>

        <section className="knowledge-checklist">
          <div className="knowledge-related-head">
            <h3>Checklist</h3>
            <span>{checklist.filter((item) => item.done).length}/{checklist.length}</span>
          </div>
          {checklist.map((item) => (
            <label className="knowledge-checklist-item" key={item.id}>
              <input
                type="checkbox"
                checked={item.done}
                onChange={(event) =>
                  setChecklist((prev) =>
                    prev.map((candidate) =>
                      candidate.id === item.id ? { ...candidate, done: event.target.checked } : candidate,
                    ),
                  )
                }
              />
              <span>{item.text}</span>
              <button
                type="button"
                aria-label="Remove checklist item"
                onClick={() => setChecklist((prev) => prev.filter((candidate) => candidate.id !== item.id))}
              >
                <X size={13} />
              </button>
            </label>
          ))}
          <div className="knowledge-inline-create">
            <input
              className="event-dialog-input"
              value={checklistInput}
              onChange={(event) => setChecklistInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") addChecklistItem();
              }}
              placeholder="Checklist item"
            />
            <Button type="button" onClick={addChecklistItem}>
              <Plus />
            </Button>
          </div>
        </section>

        <label className="event-dialog-field">
          <span className="event-dialog-label">
            <FileText size={14} />
            Markdown
          </span>
          <textarea
            className="event-dialog-input knowledge-markdown"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="Reference context with [[Entity title]]"
          />
        </label>

        <Button type="button" onClick={saveEntity}>
          <Save />
          Save
        </Button>

        <section className="knowledge-related">
          <div className="knowledge-related-head">
            <h3>Related</h3>
            <span>{related.length}</span>
          </div>
          {related.length === 0 ? (
            <p className="knowledge-muted">No related entities yet.</p>
          ) : (
            related.map((item) => (
              <div className="knowledge-related-item" key={item.relation.id}>
                <span>{typeLabel(item.entity.type)}</span>
                <strong>{item.entity.title}</strong>
                <small>{item.direction === "incoming" ? "Backlink" : item.relation.relation_type}</small>
              </div>
            ))
          )}
        </section>

        <section className="knowledge-linker">
          <div className="knowledge-searchbox">
            <Search size={15} />
            <input
              value={query}
              onChange={(event) => void searchEntities(event.target.value)}
              placeholder="Link an entity"
            />
          </div>
          {results.map((result) => (
            <button
              type="button"
              className="knowledge-search-result"
              key={result.id}
              onClick={() => void linkEntity(result)}
            >
              <Link2 size={14} />
              <span>{result.title}</span>
            </button>
          ))}
        </section>

        <section className="knowledge-linker">
          <div className="knowledge-related-head">
            <h3>Create related</h3>
          </div>
          <div className="knowledge-related-create">
            <select
              className="event-dialog-input"
              value={relatedType}
              onChange={(event) => setRelatedType(event.target.value as EntityType)}
            >
              {RELATED_TYPES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <input
              className="event-dialog-input"
              value={relatedTitle}
              onChange={(event) => setRelatedTitle(event.target.value)}
              placeholder={
                relatedType === "email"
                  ? "Email subject"
                  : relatedType === "event"
                    ? "Event title"
                    : "Title"
              }
            />
            <Button type="button" onClick={createRelatedEntity}>
              {relatedType === "email" ? <Mail /> : relatedType === "event" ? <CalendarDays /> : <Plus />}
              Create
            </Button>
          </div>
        </section>
      </div>
    </aside>
  );
}
