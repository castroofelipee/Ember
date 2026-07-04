from datetime import datetime

from pydantic import BaseModel


class InviteCreateResponse(BaseModel):
    code: str
    expires_at: datetime
