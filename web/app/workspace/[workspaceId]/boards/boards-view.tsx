"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CalendarDays,
  CheckSquare,
  Columns3,
  FilePlus,
  FileText,
  Folder,
  FolderPlus,
  Link2,
  Mail,
  Pencil,
  Plus,
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
} from "@/lib/types";

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

export function BoardsView() {
  const router = useRouter();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { status: authStatus, accessToken } = useRequireAuth();
  const [mode, setMode] = useState<ViewMode>("board");
  const [boards, setBoards] = useState<Board[]>([]);
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeBoard = useMemo(
    () => boards.find((board) => board.id === activeBoardId) ?? boards[0] ?? null,
    [boards, activeBoardId],
  );

  const visibleDocuments = useMemo(
    () =>
      documents.filter((document) => {
        const folderId = stringProp(document, "folder_id") || null;
        return folderId === activeFolderId;
      }),
    [activeFolderId, documents],
  );

  const loadKnowledge = useCallback(async () => {
    if (authStatus !== "ready") return;
    setLoading(true);
    setError(null);
    try {
      const [boardsResponse, foldersResponse, documentsResponse] = await Promise.all([
        fetch(`/api/workspaces/${workspaceId}/boards`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
        fetch(`/api/workspaces/${workspaceId}/folders`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
        fetch(`/api/workspaces/${workspaceId}/entities?type=document`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        }),
      ]);
      if (!boardsResponse.ok || !foldersResponse.ok || !documentsResponse.ok) {
        setError("Could not load workspace knowledge.");
        return;
      }
      const boardItems: Board[] = await boardsResponse.json();
      const folderItems: KnowledgeFolder[] = await foldersResponse.json();
      const documentItems: Entity[] = await documentsResponse.json();
      setBoards(boardItems);
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
          }),
        },
        "Could not create card.",
      );
      setBoards((prev) => prev.map((item) => (item.id === updatedBoard.id ? updatedBoard : item)));
      setSelectedEntity(updatedBoard.cards.at(-1)?.entity ?? null);
      setCreatingCardColumn(null);
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not create card.");
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

  async function createFolder() {
    if (!folderTitle.trim()) return;
    try {
      const folder = await jsonRequest<KnowledgeFolder>(
        `/api/workspaces/${workspaceId}/folders`,
        {
          method: "POST",
          headers: apiHeaders(accessToken),
          body: JSON.stringify({ title: folderTitle.trim(), parent_id: null }),
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

  if (authStatus !== "ready" || loading) {
    return (
      <div className="knowledge-page knowledge-page--center">
        <p className="mail-empty-title">Loading boards...</p>
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
            className={mode === "docs" ? "knowledge-tab knowledge-tab--active" : "knowledge-tab"}
            onClick={() => setMode("docs")}
          >
            <FileText size={15} />
            Docs
          </button>
        </div>

        {mode === "board" ? (
          <>
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
          </>
        ) : (
          <>
            <div className="knowledge-create">
              <input
                className="event-dialog-input"
                value={folderTitle}
                onChange={(event) => setFolderTitle(event.target.value)}
                placeholder="Folder name"
              />
              <Button type="button" onClick={createFolder}>
                <FolderPlus />
                Folder
              </Button>
            </div>

            <div className="knowledge-board-list">
              <button
                type="button"
                className={`knowledge-board-button${activeFolderId === null ? " knowledge-board-button--active" : ""}`}
                onClick={() => setActiveFolderId(null)}
              >
                <Folder size={16} />
                <span>Root</span>
              </button>
              {folders.map((folder) => (
                <button
                  type="button"
                  key={folder.id}
                  className={`knowledge-board-button${activeFolderId === folder.id ? " knowledge-board-button--active" : ""}`}
                  onClick={() => setActiveFolderId(folder.id)}
                >
                  <Folder size={16} />
                  <span>{folder.title}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </aside>

      <main className="knowledge-main">
        {error && <p className="form-error">{error}</p>}
        {mode === "board" ? (
          <BoardPanel
            activeBoard={activeBoard}
            columnTitle={columnTitle}
            selectedEntity={selectedEntity}
            onColumnTitleChange={setColumnTitle}
            onCreateColumn={createColumn}
            onCreateCard={(column) => setCreatingCardColumn(column)}
            onUpdateColumn={updateColumn}
            onDeleteColumn={deleteColumn}
            onDragStart={setDraggingEntityId}
            onDropColumn={moveCard}
            onSelectEntity={setSelectedEntity}
          />
        ) : (
          <DocsPanel
            folder={folders.find((item) => item.id === activeFolderId) ?? null}
            documents={visibleDocuments}
            selectedDocument={selectedDocument}
            documentTitle={documentTitle}
            onDocumentTitleChange={setDocumentTitle}
            onCreateDocument={createDocument}
            onSelectDocument={(document) => {
              setSelectedDocument(document);
              setSelectedEntity(null);
            }}
            onUpdated={updateEntityInState}
            workspaceId={workspaceId}
            accessToken={accessToken}
          />
        )}
      </main>

      {selectedEntity && selectedEntity.type !== "document" && (
        <EntityDrawer
          workspaceId={workspaceId}
          accessToken={accessToken}
          entity={selectedEntity}
          onClose={() => setSelectedEntity(null)}
          onUpdated={updateEntityInState}
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
  onColumnTitleChange,
  onCreateColumn,
  onCreateCard,
  onUpdateColumn,
  onDeleteColumn,
  onDragStart,
  onDropColumn,
  onSelectEntity,
}: {
  activeBoard: Board | null;
  columnTitle: string;
  selectedEntity: Entity | null;
  onColumnTitleChange: (value: string) => void;
  onCreateColumn: () => void;
  onCreateCard: (column: BoardColumn) => void;
  onUpdateColumn: (column: BoardColumn, title: string) => void;
  onDeleteColumn: (column: BoardColumn) => void;
  onDragStart: (entityId: string) => void;
  onDropColumn: (column: BoardColumn) => void;
  onSelectEntity: (entity: Entity) => void;
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
          {activeBoard.columns.map((column) => {
            const cards = activeBoard.cards
              .filter((card) => card.column_id === column.id)
              .sort((a, b) => a.position - b.position);
            return (
              <div
                className="knowledge-column"
                key={column.id}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => onDropColumn(column)}
              >
                <ColumnHeader
                  column={column}
                  count={cards.length}
                  onUpdate={onUpdateColumn}
                  onDelete={onDeleteColumn}
                />
                <div className="knowledge-card-list">
                  {cards.map((card) => (
                    <BoardCardView
                      key={card.entity.id}
                      card={card}
                      active={selectedEntity?.id === card.entity.id}
                      onSelect={() => onSelectEntity(card.entity)}
                      onDragStart={() => onDragStart(card.entity.id)}
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
  onUpdate,
  onDelete,
}: {
  column: BoardColumn;
  count: number;
  onUpdate: (column: BoardColumn, title: string) => void;
  onDelete: (column: BoardColumn) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(column.title);

  useEffect(() => {
    setTitle(column.title);
  }, [column.title]);

  return (
    <div className="knowledge-column-head">
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
  folder,
  documents,
  selectedDocument,
  documentTitle,
  workspaceId,
  accessToken,
  onDocumentTitleChange,
  onCreateDocument,
  onSelectDocument,
  onUpdated,
}: {
  folder: KnowledgeFolder | null;
  documents: Entity[];
  selectedDocument: Entity | null;
  documentTitle: string;
  workspaceId: string;
  accessToken: string | null;
  onDocumentTitleChange: (value: string) => void;
  onCreateDocument: () => void;
  onSelectDocument: (entity: Entity) => void;
  onUpdated: (entity: Entity) => void;
}) {
  return (
    <div className="knowledge-doc-layout">
      <header className="knowledge-header">
        <div>
          <p className="mail-list-kicker">Markdown documents</p>
          <h1>{folder?.title ?? "Root"}</h1>
        </div>
        <div className="knowledge-card-create knowledge-card-create--docs">
          <input
            className="event-dialog-input"
            value={documentTitle}
            onChange={(event) => onDocumentTitleChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onCreateDocument();
            }}
            placeholder="Document title"
          />
          <Button type="button" onClick={onCreateDocument}>
            <FilePlus />
            Document
          </Button>
        </div>
      </header>

      <section className="knowledge-doc-grid">
        {documents.length === 0 ? (
          <div className="knowledge-empty knowledge-empty--compact">
            <FileText size={24} />
            <h1>Create a document</h1>
            <p>Documents are Markdown entities and can be linked from cards with [[title]].</p>
          </div>
        ) : (
          documents.map((document) => (
            <button
              type="button"
              className="knowledge-doc"
              key={document.id}
              onClick={() => onSelectDocument(document)}
            >
              <FileText size={18} />
              <strong>{document.title}</strong>
              <span>{document.content || "Empty Markdown document"}</span>
            </button>
          ))
        )}
      </section>

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
          <h2>Select a document</h2>
        </section>
      )}
    </div>
  );
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderInlineMarkdown(value: string): string {
  return escapeHtml(value)
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\[\[([^\]\n]+)\]\]/g, '<span class="knowledge-doc-wikilink">$1</span>')
    .replace(/__(.+?)__/g, "<strong>$1</strong>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function markdownToEditorHtml(markdown: string): string {
  const lines = markdown.split("\n");
  let html = "";
  let inCode = false;
  let codeLines: string[] = [];

  lines.forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        html += `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
      }
      return;
    }

    if (inCode) {
      codeLines.push(line);
      return;
    }

    if (!line.trim()) {
      html += "<p><br></p>";
      return;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      html += `<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`;
      return;
    }

    const checkbox = /^-\s+\[( |x|X)\]\s+(.+)$/.exec(line);
    if (checkbox) {
      const checked = checkbox[1].toLowerCase() === "x";
      html += `<div class="knowledge-doc-task" data-checked="${checked ? "true" : "false"}"><span>${checked ? "☑" : "☐"}</span><p>${renderInlineMarkdown(checkbox[2])}</p></div>`;
      return;
    }

    const bullet = /^[-*]\s+(.+)$/.exec(line);
    if (bullet) {
      html += `<div class="knowledge-doc-bullet" data-block="bullet"><span></span><p>${renderInlineMarkdown(bullet[1])}</p></div>`;
      return;
    }

    html += `<p>${renderInlineMarkdown(line)}</p>`;
  });

  if (inCode) html += `<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`;
  return html || "<p><br></p>";
}

function serializeInline(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const element = node as HTMLElement;
  const text = Array.from(element.childNodes).map(serializeInline).join("");
  if (element.tagName === "STRONG" || element.tagName === "B") return `__${text}__`;
  if (element.tagName === "CODE") return `\`${text}\``;
  if (element.classList.contains("knowledge-doc-wikilink")) return `[[${text}]]`;
  return text;
}

function editorHtmlToMarkdown(root: HTMLElement): string {
  return Array.from(root.childNodes)
    .map((node) => {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
      if (node.nodeType !== Node.ELEMENT_NODE) return "";
      const element = node as HTMLElement;
      if (element.tagName === "H1") return `# ${serializeInline(element)}`;
      if (element.tagName === "H2") return `## ${serializeInline(element)}`;
      if (element.tagName === "H3") return `### ${serializeInline(element)}`;
      if (element.tagName === "PRE") return `\`\`\`\n${element.innerText.trimEnd()}\n\`\`\``;
      if (element.classList.contains("knowledge-doc-task")) {
        const checked = element.dataset.checked === "true" ? "x" : " ";
        const paragraph = element.querySelector("p");
        return `- [${checked}] ${paragraph ? serializeInline(paragraph) : element.innerText}`;
      }
      if (element.classList.contains("knowledge-doc-bullet")) {
        const paragraph = element.querySelector("p");
        return `- ${paragraph ? serializeInline(paragraph) : element.innerText}`;
      }
      return serializeInline(element);
    })
    .join("\n");
}

function caretOffset(root: HTMLElement): number {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return 0;
  const range = selection.getRangeAt(0);
  const clone = range.cloneRange();
  clone.selectNodeContents(root);
  clone.setEnd(range.endContainer, range.endOffset);
  return clone.toString().length;
}

function restoreCaret(root: HTMLElement, offset: number) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let currentOffset = 0;
  let current = walker.nextNode();
  while (current) {
    const length = current.textContent?.length ?? 0;
    if (currentOffset + length >= offset) {
      const range = document.createRange();
      range.setStart(current, Math.max(0, Math.min(length, offset - currentOffset)));
      range.collapse(true);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      return;
    }
    currentOffset += length;
    current = walker.nextNode();
  }
  const range = document.createRange();
  range.selectNodeContents(root);
  range.collapse(false);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
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
  const editorRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setTitle(document.title);
    setContent(document.content);
    setError(null);
    if (editorRef.current) {
      editorRef.current.innerHTML = markdownToEditorHtml(document.content);
    }
  }, [document]);

  function handleEditorInput() {
    const editor = editorRef.current;
    if (!editor) return;
    const offset = caretOffset(editor);
    const markdown = editorHtmlToMarkdown(editor);
    setContent(markdown);
    editor.innerHTML = markdownToEditorHtml(markdown);
    restoreCaret(editor, offset);
  }

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
      <div
        ref={editorRef}
        className="knowledge-doc-rich-editor"
        contentEditable
        suppressContentEditableWarning
        onInput={handleEditorInput}
        onBlur={handleEditorInput}
      />
    </section>
  );
}

function BoardCardView({
  card,
  active,
  onSelect,
  onDragStart,
}: {
  card: BoardCard;
  active: boolean;
  onSelect: () => void;
  onDragStart: () => void;
}) {
  const labels = stringListProp(card.entity, "labels");
  const assignees = stringListProp(card.entity, "assignees");
  const done = checklistProp(card.entity).filter((item) => item.done).length;
  const total = checklistProp(card.entity).length;

  return (
    <button
      type="button"
      className={`knowledge-card${active ? " knowledge-card--active" : ""}`}
      draggable
      onDragStart={onDragStart}
      onClick={onSelect}
    >
      <span className="knowledge-card-type">{typeLabel(card.entity.type)}</span>
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
          <span>
            <UserRound size={13} /> {assignees.join(", ")}
          </span>
        )}
      </span>
    </button>
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
  }) => void;
}) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState<EntityType>("task");
  const [labelsInput, setLabelsInput] = useState("");
  const [assigneesInput, setAssigneesInput] = useState("");
  const [dueDate, setDueDate] = useState("");
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
  onRelatedCreated,
}: {
  workspaceId: string;
  accessToken: string;
  entity: Entity;
  onClose: () => void;
  onUpdated: (entity: Entity) => void;
  onRelatedCreated: (entity: Entity) => void;
}) {
  const [title, setTitle] = useState(entity.title);
  const [type, setType] = useState<EntityType>(entity.type);
  const [content, setContent] = useState(entity.content);
  const [labelsInput, setLabelsInput] = useState(stringListProp(entity, "labels").join(", "));
  const [assigneesInput, setAssigneesInput] = useState(stringListProp(entity, "assignees").join(", "));
  const [dueDate, setDueDate] = useState(stringProp(entity, "due_date"));
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
