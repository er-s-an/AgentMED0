from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "records"

    collection: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Store:
    def __init__(self, database_url: str, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, future=True, connect_args=connect_args)
        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(self.engine, expire_on_commit=False)

    def put(self, collection: str, obj: dict[str, Any]) -> dict[str, Any]:
        obj_id = obj["id"]
        payload = json.dumps(obj, ensure_ascii=False, default=str)
        with self._session() as session:
            existing = session.get(Record, (collection, obj_id))
            if existing:
                existing.json = payload
            else:
                session.add(Record(collection=collection, id=obj_id, json=payload))
            session.commit()
        return obj

    def get(self, collection: str, obj_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            row = session.get(Record, (collection, obj_id))
            return json.loads(row.json) if row else None

    def list(self, collection: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = session.scalars(select(Record).where(Record.collection == collection)).all()
            return [json.loads(row.json) for row in rows]
