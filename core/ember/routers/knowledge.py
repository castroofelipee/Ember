import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ember.db import get_db
from ember.dependencies import get_current_user
from ember.models import Board, Entity, EntityType, User
from ember.schemas.knowledge import (
    BoardCardCreateRequest,
    BoardCardCreateWithEntityRequest,
    BoardCardMoveRequest,
    BoardCardResponse,
    BoardColumnCreateRequest,
    BoardColumnResponse,
    BoardColumnUpdateRequest,
    BoardCreateRequest,
    BoardResponse,
    DocumentCreateRequest,
    EntityCreateRequest,
    EntityResponse,
    EntityUpdateRequest,
    KnowledgeFolderCreateRequest,
    KnowledgeFolderResponse,
    RelatedEntityResponse,
    RelationCreateRequest,
    RelationResponse,
)
from ember.services.knowledge import (
    add_entity_to_board,
    create_board,
    create_board_column,
    create_entity,
    create_folder,
    create_relation,
    delete_board_column,
    delete_entity,
    get_board,
    get_board_card,
    get_board_column,
    get_entity,
    get_folder,
    list_board_cards,
    list_board_columns,
    list_boards,
    list_folders,
    list_entities,
    list_related,
    move_board_card,
    update_board_column,
    update_entity,
)
from ember.services.workspaces import NotAWorkspaceMemberError, assert_workspace_member

router = APIRouter(prefix="/api/workspaces", tags=["Knowledge"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


def _conflict() -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already exists.")


async def _require_membership(db: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
    try:
        await assert_workspace_member(db, workspace_id, user_id)
    except NotAWorkspaceMemberError as exc:
        raise _NOT_FOUND from exc


async def _get_entity_or_404(
    db: AsyncSession, workspace_id: uuid.UUID, entity_id: uuid.UUID
) -> Entity:
    entity = await get_entity(db, workspace_id, entity_id)
    if entity is None:
        raise _NOT_FOUND
    return entity


async def _get_board_or_404(
    db: AsyncSession, workspace_id: uuid.UUID, board_id: uuid.UUID
) -> Board:
    board = await get_board(db, workspace_id, board_id)
    if board is None:
        raise _NOT_FOUND
    return board


async def _board_response(db: AsyncSession, board: Board) -> BoardResponse:
    columns = await list_board_columns(db, board.id)
    cards = await list_board_cards(db, board.id)
    return BoardResponse(
        id=board.id,
        workspace_id=board.workspace_id,
        title=board.title,
        description=board.description,
        created_at=board.created_at,
        updated_at=board.updated_at,
        columns=[BoardColumnResponse.model_validate(column) for column in columns],
        cards=[
            BoardCardResponse(
                board_id=card.board_id,
                entity=EntityResponse.model_validate(entity),
                column_id=card.column_id,
                position=card.position,
                created_at=card.created_at,
                updated_at=card.updated_at,
            )
            for card, entity in cards
        ],
    )


@router.post("/{workspace_id}/entities", status_code=status.HTTP_201_CREATED)
async def create_entity_route(
    workspace_id: uuid.UUID,
    data: EntityCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntityResponse:
    await _require_membership(db, workspace_id, current_user.id)
    entity = await create_entity(db, workspace_id, current_user.id, data)
    return EntityResponse.model_validate(entity)


@router.get("/{workspace_id}/entities")
async def list_entities_route(
    workspace_id: uuid.UUID,
    q: str | None = Query(default=None, max_length=200),
    type: str | None = Query(default=None, max_length=40),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EntityResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    entities = await list_entities(db, workspace_id, query=q, entity_type=type)
    return [EntityResponse.model_validate(entity) for entity in entities]


@router.get("/{workspace_id}/search")
async def search_entities_route(
    workspace_id: uuid.UUID,
    q: str = Query(..., min_length=1, max_length=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EntityResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    entities = await list_entities(db, workspace_id, query=q, limit=25)
    return [EntityResponse.model_validate(entity) for entity in entities]


@router.get("/{workspace_id}/entities/{entity_id}")
async def get_entity_route(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntityResponse:
    await _require_membership(db, workspace_id, current_user.id)
    entity = await _get_entity_or_404(db, workspace_id, entity_id)
    return EntityResponse.model_validate(entity)


@router.patch("/{workspace_id}/entities/{entity_id}")
async def update_entity_route(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    data: EntityUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntityResponse:
    await _require_membership(db, workspace_id, current_user.id)
    entity = await _get_entity_or_404(db, workspace_id, entity_id)
    entity = await update_entity(db, entity, data)
    return EntityResponse.model_validate(entity)


@router.delete("/{workspace_id}/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity_route(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_membership(db, workspace_id, current_user.id)
    entity = await _get_entity_or_404(db, workspace_id, entity_id)
    await delete_entity(db, entity)


@router.post("/{workspace_id}/folders", status_code=status.HTTP_201_CREATED)
async def create_folder_route(
    workspace_id: uuid.UUID,
    data: KnowledgeFolderCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeFolderResponse:
    await _require_membership(db, workspace_id, current_user.id)
    if data.parent_id is not None and await get_folder(db, workspace_id, data.parent_id) is None:
        raise _NOT_FOUND
    folder = await create_folder(db, workspace_id, data)
    return KnowledgeFolderResponse.model_validate(folder)


@router.get("/{workspace_id}/folders")
async def list_folders_route(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeFolderResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    folders = await list_folders(db, workspace_id)
    return [KnowledgeFolderResponse.model_validate(folder) for folder in folders]


@router.post("/{workspace_id}/documents", status_code=status.HTTP_201_CREATED)
async def create_document_route(
    workspace_id: uuid.UUID,
    data: DocumentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntityResponse:
    await _require_membership(db, workspace_id, current_user.id)
    if data.folder_id is not None and await get_folder(db, workspace_id, data.folder_id) is None:
        raise _NOT_FOUND
    entity = await create_entity(
        db,
        workspace_id,
        current_user.id,
        EntityCreateRequest(
            type=EntityType.DOCUMENT,
            title=data.title,
            content=data.content,
            properties={"folder_id": str(data.folder_id) if data.folder_id else ""},
        ),
    )
    return EntityResponse.model_validate(entity)


@router.post("/{workspace_id}/entities/{entity_id}/relations", status_code=status.HTTP_201_CREATED)
async def create_relation_route(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    data: RelationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RelationResponse:
    await _require_membership(db, workspace_id, current_user.id)
    entity = await _get_entity_or_404(db, workspace_id, entity_id)
    target = await _get_entity_or_404(db, workspace_id, data.to_entity_id)
    if target.id == entity.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Self relations are not allowed.",
        )
    try:
        relation = await create_relation(db, workspace_id, entity, data)
    except IntegrityError as exc:
        raise _conflict() from exc
    return RelationResponse.model_validate(relation)


@router.get("/{workspace_id}/entities/{entity_id}/related")
async def list_related_route(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RelatedEntityResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    await _get_entity_or_404(db, workspace_id, entity_id)
    rows = await list_related(db, workspace_id, entity_id)
    return [
        RelatedEntityResponse(
            entity=EntityResponse.model_validate(entity),
            relation=RelationResponse.model_validate(relation),
            direction="outgoing" if relation.from_entity_id == entity_id else "incoming",
        )
        for relation, entity in rows
    ]


@router.post("/{workspace_id}/boards", status_code=status.HTTP_201_CREATED)
async def create_board_route(
    workspace_id: uuid.UUID,
    data: BoardCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardResponse:
    await _require_membership(db, workspace_id, current_user.id)
    board = await create_board(db, workspace_id, data)
    return await _board_response(db, board)


@router.get("/{workspace_id}/boards")
async def list_boards_route(
    workspace_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BoardResponse]:
    await _require_membership(db, workspace_id, current_user.id)
    boards = await list_boards(db, workspace_id)
    return [await _board_response(db, board) for board in boards]


@router.get("/{workspace_id}/boards/{board_id}")
async def get_board_route(
    workspace_id: uuid.UUID,
    board_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardResponse:
    await _require_membership(db, workspace_id, current_user.id)
    board = await _get_board_or_404(db, workspace_id, board_id)
    return await _board_response(db, board)


@router.post("/{workspace_id}/boards/{board_id}/columns", status_code=status.HTTP_201_CREATED)
async def create_board_column_route(
    workspace_id: uuid.UUID,
    board_id: uuid.UUID,
    data: BoardColumnCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardColumnResponse:
    await _require_membership(db, workspace_id, current_user.id)
    board = await _get_board_or_404(db, workspace_id, board_id)
    column = await create_board_column(db, board, data)
    return BoardColumnResponse.model_validate(column)


@router.patch("/{workspace_id}/boards/{board_id}/columns/{column_id}")
async def update_board_column_route(
    workspace_id: uuid.UUID,
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    data: BoardColumnUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardResponse:
    await _require_membership(db, workspace_id, current_user.id)
    board = await _get_board_or_404(db, workspace_id, board_id)
    column = await get_board_column(db, board.id, column_id)
    if column is None:
        raise _NOT_FOUND
    await update_board_column(db, column, data)
    return await _board_response(db, board)


@router.delete(
    "/{workspace_id}/boards/{board_id}/columns/{column_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_board_column_route(
    workspace_id: uuid.UUID,
    board_id: uuid.UUID,
    column_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_membership(db, workspace_id, current_user.id)
    board = await _get_board_or_404(db, workspace_id, board_id)
    column = await get_board_column(db, board.id, column_id)
    if column is None:
        raise _NOT_FOUND
    await delete_board_column(db, column)


@router.post("/{workspace_id}/boards/{board_id}/cards", status_code=status.HTTP_201_CREATED)
async def add_board_card_route(
    workspace_id: uuid.UUID,
    board_id: uuid.UUID,
    data: BoardCardCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardResponse:
    await _require_membership(db, workspace_id, current_user.id)
    board = await _get_board_or_404(db, workspace_id, board_id)
    entity = await _get_entity_or_404(db, workspace_id, data.entity_id)
    column = await get_board_column(db, board.id, data.column_id)
    if column is None:
        raise _NOT_FOUND
    try:
        await add_entity_to_board(db, board, entity, column.id)
    except IntegrityError as exc:
        raise _conflict() from exc
    return await _board_response(db, board)


@router.post("/{workspace_id}/boards/{board_id}/cards/new", status_code=status.HTTP_201_CREATED)
async def create_board_card_route(
    workspace_id: uuid.UUID,
    board_id: uuid.UUID,
    data: BoardCardCreateWithEntityRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardResponse:
    await _require_membership(db, workspace_id, current_user.id)
    board = await _get_board_or_404(db, workspace_id, board_id)
    column = await get_board_column(db, board.id, data.column_id)
    if column is None:
        raise _NOT_FOUND

    entity = await create_entity(
        db,
        workspace_id,
        current_user.id,
        EntityCreateRequest(
            type=data.type,
            title=data.title,
            content=data.content,
            properties={
                "status": column.status_key or column.title,
                "checklist": data.checklist,
                "labels": data.labels,
                "assignees": data.assignees,
                "due_date": data.due_date,
                "recurrence": data.recurrence,
            },
        ),
    )
    await add_entity_to_board(db, board, entity, column.id)
    return await _board_response(db, board)


@router.patch("/{workspace_id}/boards/{board_id}/cards/{entity_id}")
async def move_board_card_route(
    workspace_id: uuid.UUID,
    board_id: uuid.UUID,
    entity_id: uuid.UUID,
    data: BoardCardMoveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardResponse:
    await _require_membership(db, workspace_id, current_user.id)
    board = await _get_board_or_404(db, workspace_id, board_id)
    card = await get_board_card(db, board.id, entity_id)
    column = await get_board_column(db, board.id, data.column_id)
    if card is None or column is None:
        raise _NOT_FOUND
    await move_board_card(db, card, column.id, data.position)
    return await _board_response(db, board)
