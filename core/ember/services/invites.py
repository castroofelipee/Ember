import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ember.config import env
from ember.models import Invite
from ember.security import generate_invite_code, hash_invite_code


async def create_invite(session: AsyncSession, created_by_user_id: uuid.UUID) -> tuple[Invite, str]:
    raw_code = generate_invite_code()
    invite = Invite(
        created_by_user_id=created_by_user_id,
        code_hash=hash_invite_code(raw_code),
        expires_at=datetime.now(timezone.utc) + timedelta(days=env["INVITE_CODE_TTL_DAYS"]),
    )
    session.add(invite)
    await session.flush()
    return invite, raw_code
