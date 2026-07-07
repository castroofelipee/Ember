import re
import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ember.models.knowledge import (
    Board,
    BoardCard,
    BoardColumn,
    Entity,
    KnowledgeFolder,
    Relation,
    RelationSource,
)
from ember.schemas.knowledge import (
    BoardColumnCreateRequest,
    BoardColumnUpdateRequest,
    BoardCreateRequest,
    EntityCreateRequest,
    EntityUpdateRequest,
    KnowledgeFolderCreateRequest,
    KnowledgeFolderUpdateRequest,
    RelationCreateRequest,
)

_WIKI_LINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")

_STARTER_COLUMNS = ["Backlog", "Doing", "Done"]


def status_key_for_title(title: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", title.strip().lower()).strip("_")
    return key or "column"


def _wiki_titles(content: str) -> list[str]:
    seen: set[str] = set()
    titles: list[str] = []
    for match in _WIKI_LINK_RE.finditer(content):
        title = match.group(1).strip()
        key = title.lower()
        if title and key not in seen:
            seen.add(key)
            titles.append(title)
    return titles


async def sync_wiki_link_relations(session: AsyncSession, entity: Entity) -> None:
    await session.execute(
        delete(Relation).where(
            Relation.from_entity_id == entity.id,
            Relation.source == RelationSource.WIKI_LINK,
        )
    )

    titles = _wiki_titles(entity.content)
    if not titles:
        await session.flush()
        return

    rows = (
        await session.execute(
            select(Entity).where(
                Entity.workspace_id == entity.workspace_id,
                Entity.id != entity.id,
                func.lower(Entity.title).in_([title.lower() for title in titles]),
            )
        )
    ).scalars()

    for target in rows:
        session.add(
            Relation(
                workspace_id=entity.workspace_id,
                from_entity_id=entity.id,
                to_entity_id=target.id,
                relation_type="references",
                source=RelationSource.WIKI_LINK,
                relation_metadata={"title": target.title},
            )
        )
    await session.flush()


async def create_entity(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: EntityCreateRequest,
) -> Entity:
    entity = Entity(
        workspace_id=workspace_id,
        type=data.type,
        title=data.title,
        content=data.content,
        properties=data.properties,
        created_by_id=user_id,
    )
    session.add(entity)
    await session.flush()
    await sync_wiki_link_relations(session, entity)
    return entity


async def get_entity(
    session: AsyncSession, workspace_id: uuid.UUID, entity_id: uuid.UUID
) -> Entity | None:
    return (
        await session.execute(
            select(Entity).where(Entity.workspace_id == workspace_id, Entity.id == entity_id)
        )
    ).scalar_one_or_none()


async def list_entities(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    query: str | None = None,
    entity_type: str | None = None,
    limit: int = 100,
) -> list[Entity]:
    stmt = select(Entity).where(Entity.workspace_id == workspace_id)
    if entity_type:
        stmt = stmt.where(Entity.type == entity_type)
    if query:
        pattern = f"%{query.strip()}%"
        stmt = stmt.where(or_(Entity.title.ilike(pattern), Entity.content.ilike(pattern)))
    return (
        await session.execute(stmt.order_by(Entity.updated_at.desc()).limit(limit))
    ).scalars().all()


async def update_entity(
    session: AsyncSession,
    entity: Entity,
    data: EntityUpdateRequest,
) -> Entity:
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(entity, field, value)
    await session.flush()
    if "content" in changes or "title" in changes:
        await sync_wiki_link_relations(session, entity)
    await session.refresh(entity)
    return entity


async def delete_entity(session: AsyncSession, entity: Entity) -> None:
    await session.delete(entity)
    await session.flush()


async def create_folder(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    data: KnowledgeFolderCreateRequest,
) -> KnowledgeFolder:
    max_position = (
        await session.execute(
            select(func.max(KnowledgeFolder.position)).where(
                KnowledgeFolder.workspace_id == workspace_id,
                KnowledgeFolder.parent_id == data.parent_id,
            )
        )
    ).scalar_one()
    folder = KnowledgeFolder(
        workspace_id=workspace_id,
        parent_id=data.parent_id,
        title=data.title,
        position=0 if max_position is None else max_position + 1,
    )
    session.add(folder)
    await session.flush()
    return folder


async def get_folder(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    folder_id: uuid.UUID,
) -> KnowledgeFolder | None:
    return (
        await session.execute(
            select(KnowledgeFolder).where(
                KnowledgeFolder.workspace_id == workspace_id,
                KnowledgeFolder.id == folder_id,
            )
        )
    ).scalar_one_or_none()


async def list_folders(
    session: AsyncSession,
    workspace_id: uuid.UUID,
) -> list[KnowledgeFolder]:
    return (
        await session.execute(
            select(KnowledgeFolder)
            .where(KnowledgeFolder.workspace_id == workspace_id)
            .order_by(KnowledgeFolder.parent_id, KnowledgeFolder.position, KnowledgeFolder.title)
        )
    ).scalars().all()


async def update_folder(
    session: AsyncSession,
    folder: KnowledgeFolder,
    data: KnowledgeFolderUpdateRequest,
) -> KnowledgeFolder:
    changes = data.model_dump(exclude_unset=True)

    if "title" in changes and data.title is not None:
        folder.title = data.title

    if "parent_id" in changes or data.position is not None:
        new_parent_id = changes.get("parent_id", folder.parent_id)
        siblings = (
            await session.execute(
                select(KnowledgeFolder)
                .where(
                    KnowledgeFolder.workspace_id == folder.workspace_id,
                    KnowledgeFolder.parent_id == new_parent_id,
                    KnowledgeFolder.id != folder.id,
                )
                .order_by(KnowledgeFolder.position, KnowledgeFolder.title)
            )
        ).scalars().all()
        insert_at = min(data.position if data.position is not None else len(siblings), len(siblings))
        ordered = [*siblings]
        ordered.insert(insert_at, folder)

        source_siblings = (
            await session.execute(
                select(KnowledgeFolder)
                .where(
                    KnowledgeFolder.workspace_id == folder.workspace_id,
                    KnowledgeFolder.parent_id == folder.parent_id,
                )
                .order_by(KnowledgeFolder.position, KnowledgeFolder.title)
            )
        ).scalars().all()
        offset = len(source_siblings) + len(ordered)
        for index, item in enumerate(source_siblings):
            item.position = offset + index
        await session.flush()

        folder.parent_id = new_parent_id
        for index, item in enumerate(ordered):
            item.position = index

    await session.flush()
    await session.refresh(folder)
    return folder


async def create_relation(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    from_entity: Entity,
    data: RelationCreateRequest,
) -> Relation:
    relation = Relation(
        workspace_id=workspace_id,
        from_entity_id=from_entity.id,
        to_entity_id=data.to_entity_id,
        relation_type=data.relation_type,
        source=data.source,
        relation_metadata=data.metadata,
    )
    session.add(relation)
    await session.flush()
    return relation


async def list_related(session: AsyncSession, workspace_id: uuid.UUID, entity_id: uuid.UUID):
    return (
        await session.execute(
            select(Relation, Entity)
            .join(
                Entity,
                or_(
                    Entity.id == Relation.to_entity_id,
                    Entity.id == Relation.from_entity_id,
                ),
            )
            .where(
                Relation.workspace_id == workspace_id,
                or_(Relation.from_entity_id == entity_id, Relation.to_entity_id == entity_id),
                Entity.id != entity_id,
            )
            .order_by(Relation.created_at.desc())
        )
    ).all()


async def create_board(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    data: BoardCreateRequest,
) -> Board:
    board = Board(workspace_id=workspace_id, title=data.title, description=data.description)
    session.add(board)
    await session.flush()
    for position, title in enumerate(data.initial_columns or _STARTER_COLUMNS):
        session.add(
            BoardColumn(
                board_id=board.id,
                title=title,
                position=position,
                status_key=status_key_for_title(title),
            )
        )
    await session.flush()
    return board


async def get_board(
    session: AsyncSession, workspace_id: uuid.UUID, board_id: uuid.UUID
) -> Board | None:
    return (
        await session.execute(
            select(Board).where(Board.workspace_id == workspace_id, Board.id == board_id)
        )
    ).scalar_one_or_none()


async def list_boards(session: AsyncSession, workspace_id: uuid.UUID) -> list[Board]:
    return (
        await session.execute(
            select(Board).where(Board.workspace_id == workspace_id).order_by(Board.created_at)
        )
    ).scalars().all()


async def list_board_columns(session: AsyncSession, board_id: uuid.UUID) -> list[BoardColumn]:
    return (
        await session.execute(
            select(BoardColumn).where(BoardColumn.board_id == board_id).order_by(BoardColumn.position)
        )
    ).scalars().all()


async def list_board_cards(
    session: AsyncSession, board_id: uuid.UUID
) -> list[tuple[BoardCard, Entity]]:
    return (
        await session.execute(
            select(BoardCard, Entity)
            .join(Entity, Entity.id == BoardCard.entity_id)
            .where(BoardCard.board_id == board_id)
            .order_by(BoardCard.column_id, BoardCard.position)
        )
    ).all()


async def create_board_column(
    session: AsyncSession,
    board: Board,
    data: BoardColumnCreateRequest,
) -> BoardColumn:
    max_position = (
        await session.execute(
            select(func.max(BoardColumn.position)).where(BoardColumn.board_id == board.id)
        )
    ).scalar_one()
    column = BoardColumn(
        board_id=board.id,
        title=data.title,
        position=0 if max_position is None else max_position + 1,
        status_key=data.status_key or status_key_for_title(data.title),
    )
    session.add(column)
    await session.flush()
    return column


async def update_board_column(
    session: AsyncSession,
    column: BoardColumn,
    data: BoardColumnUpdateRequest,
) -> BoardColumn:
    if data.title is not None:
        column.title = data.title
        column.status_key = data.status_key or status_key_for_title(data.title)
    elif data.status_key is not None:
        column.status_key = data.status_key

    if data.position is not None:
        columns = await list_board_columns(session, column.board_id)
        ordered = [item for item in columns if item.id != column.id]
        insert_at = min(data.position, len(ordered))
        ordered.insert(insert_at, column)

        offset = len(ordered)
        for index, item in enumerate(columns):
            item.position = offset + index
        await session.flush()

        for index, item in enumerate(ordered):
            item.position = index

    await session.flush()
    await session.refresh(column)
    return column


async def delete_board_column(session: AsyncSession, column: BoardColumn) -> None:
    await session.execute(delete(BoardCard).where(BoardCard.column_id == column.id))
    await session.delete(column)
    await session.flush()


async def add_entity_to_board(
    session: AsyncSession,
    board: Board,
    entity: Entity,
    column_id: uuid.UUID,
) -> BoardCard:
    max_position = (
        await session.execute(
            select(func.max(BoardCard.position)).where(
                BoardCard.board_id == board.id,
                BoardCard.column_id == column_id,
            )
        )
    ).scalar_one()
    card = BoardCard(
        board_id=board.id,
        entity_id=entity.id,
        column_id=column_id,
        position=0 if max_position is None else max_position + 1,
    )
    session.add(card)
    await session.flush()
    return card


async def get_board_card(
    session: AsyncSession,
    board_id: uuid.UUID,
    entity_id: uuid.UUID,
) -> BoardCard | None:
    return (
        await session.execute(
            select(BoardCard).where(
                BoardCard.board_id == board_id,
                BoardCard.entity_id == entity_id,
            )
        )
    ).scalar_one_or_none()


async def get_board_column(
    session: AsyncSession,
    board_id: uuid.UUID,
    column_id: uuid.UUID,
) -> BoardColumn | None:
    return (
        await session.execute(
            select(BoardColumn).where(BoardColumn.board_id == board_id, BoardColumn.id == column_id)
        )
    ).scalar_one_or_none()


async def move_board_card(
    session: AsyncSession,
    card: BoardCard,
    column_id: uuid.UUID,
    position: int,
) -> BoardCard:
    card.column_id = column_id
    card.position = position
    await session.flush()
    return card
