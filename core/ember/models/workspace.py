from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from ember.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    holiday_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    holiday_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    holiday_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    holiday_region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    holiday_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
