




















import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Sequence, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base, UUIDPrimaryKeyMixin




event_log_seq = Sequence("event_log_sequence_id_seq")


class EventLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "event_log"




    sequence_id: Mapped[int] = mapped_column(
        BigInteger,
        event_log_seq,
        server_default=event_log_seq.next_value(),
        nullable=False,
        unique=True,
    )




    scope: Mapped[str] = mapped_column(String(128), nullable=False)



    source: Mapped[str] = mapped_column(String(64), nullable=False)


    text: Mapped[str] = mapped_column(Text, nullable=False)





    event_metadata: Mapped[dict | None] = mapped_column(
        "event_metadata",
        JSONB,
        nullable=True,
    )




    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )



    __table_args__ = (
        Index("ix_event_log_scope_seq", "scope", "sequence_id"),
        Index("ix_event_log_sequence_id", "sequence_id"),
        Index("ix_event_log_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<EventLog seq={self.sequence_id} scope={self.scope!r} "
            f"source={self.source!r} text={self.text[:40]!r}>"
        )
