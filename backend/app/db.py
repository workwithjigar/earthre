"""Database schema and access. SQLAlchemy Core keeps it portable between
sqlite (local dev, tests) and Postgres (deployed)."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta
from functools import lru_cache

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from . import config
from .cleaning import CleanResult

metadata = MetaData()

uploads = Table(
    "uploads",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("filename", String(255), nullable=False),
    Column("uploaded_at", DateTime, nullable=False),
    Column("rows_received", Integer, nullable=False),
    Column("records_stored", Integer, nullable=False),
    Column("start_ts", DateTime, nullable=False),
    Column("end_ts", DateTime, nullable=False),
    Column("report", Text, nullable=False),  # JSON data-quality report
)

# All timestamps are stored as naive UTC.
checks = Table(
    "checks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("upload_id", String(36), ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False),
    Column("service_id", String(64), nullable=False),
    Column("service_name", String(128), nullable=False),
    Column("ts", DateTime, nullable=False),
    Column("status_code", Integer),
    Column("latency_ms", Float),
    Column("outcome", String(8), nullable=False),
    Column("agent", String(64), nullable=False),
    Column("region", String(64), nullable=False),
    Column("raw_timestamp", String(64), nullable=False),
    Column("flags", String(255), nullable=False),
    Index("ix_checks_upload_ts", "upload_id", "ts"),
    Index("ix_checks_upload_service_ts", "upload_id", "service_id", "ts"),
)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """One engine per process (i.e. per warm Lambda container)."""
    url = config.DATABASE_URL
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url, pool_size=1, max_overflow=1, pool_pre_ping=True, pool_recycle=300)
    metadata.create_all(engine)
    return engine


def _day_bounds(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    """Inclusive date range -> [start 00:00, day after end 00:00)."""
    lo = datetime.combine(start, time.min) if start else None
    hi = datetime.combine(end + timedelta(days=1), time.min) if end else None
    return lo, hi


def save_upload(engine: Engine, filename: str, result: CleanResult) -> dict:
    upload_id = str(uuid.uuid4())
    row = {
        "id": upload_id,
        "filename": filename,
        "uploaded_at": datetime.utcnow().replace(microsecond=0),
        "rows_received": result.report["rows_received"],
        "records_stored": result.report["records_stored"],
        "start_ts": result.records[0].ts,
        "end_ts": result.records[-1].ts,
        "report": json.dumps(result.report),
    }
    records = [
        {
            "upload_id": upload_id,
            "service_id": r.service_id,
            "service_name": r.service_name,
            "ts": r.ts,
            "status_code": r.status_code,
            "latency_ms": r.latency_ms,
            "outcome": r.outcome,
            "agent": r.agent,
            "region": r.region,
            "raw_timestamp": r.raw_timestamp[:64],
            "flags": ",".join(r.flags),
        }
        for r in result.records
    ]
    # One transaction: either the whole upload lands or none of it does.
    with engine.begin() as conn:
        conn.execute(insert(uploads), row)
        for i in range(0, len(records), 2000):
            conn.execute(insert(checks), records[i : i + 2000])
    return _upload_dict(row)


def _upload_dict(row) -> dict:
    d = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    d["report"] = json.loads(d["report"])
    return d


def list_uploads(engine: Engine) -> list[dict]:
    cols = [c for c in uploads.c if c.name != "report"]
    with engine.connect() as conn:
        rows = conn.execute(select(*cols).order_by(uploads.c.uploaded_at.desc())).all()
    return [dict(r._mapping) for r in rows]


def get_upload(engine: Engine, upload_id: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(uploads).where(uploads.c.id == upload_id)).first()
    return _upload_dict(row) if row else None


def delete_upload(engine: Engine, upload_id: str) -> bool:
    with engine.begin() as conn:
        conn.execute(delete(checks).where(checks.c.upload_id == upload_id))
        return conn.execute(delete(uploads).where(uploads.c.id == upload_id)).rowcount > 0


def service_names(engine: Engine, upload_id: str) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(checks.c.service_id, checks.c.service_name)
            .where(checks.c.upload_id == upload_id)
            .group_by(checks.c.service_id, checks.c.service_name)
        ).all()
    return {r.service_id: r.service_name for r in rows}


def fetch_for_stats(engine: Engine, upload_id: str, start: date | None = None, end: date | None = None) -> list[dict]:
    lo, hi = _day_bounds(start, end)
    q = select(
        checks.c.service_id, checks.c.ts, checks.c.outcome, checks.c.status_code, checks.c.latency_ms
    ).where(checks.c.upload_id == upload_id)
    if lo:
        q = q.where(checks.c.ts >= lo)
    if hi:
        q = q.where(checks.c.ts < hi)
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]


def query_checks(
    engine: Engine,
    upload_id: str,
    *,
    start: date | None,
    end: date | None,
    service_id: str | None,
    outcome: str | None,
    agent: str | None,
    flagged_only: bool,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    lo, hi = _day_bounds(start, end)
    conditions = [checks.c.upload_id == upload_id]
    if lo:
        conditions.append(checks.c.ts >= lo)
    if hi:
        conditions.append(checks.c.ts < hi)
    if service_id:
        conditions.append(checks.c.service_id == service_id)
    if outcome:
        conditions.append(checks.c.outcome == outcome)
    if agent:
        conditions.append(checks.c.agent == agent)
    if flagged_only:
        conditions.append(checks.c.flags != "")

    with engine.connect() as conn:
        total = conn.execute(select(func.count()).select_from(checks).where(*conditions)).scalar_one()
        rows = conn.execute(
            select(checks)
            .where(*conditions)
            .order_by(checks.c.ts, checks.c.service_id, checks.c.agent)
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).all()
    items = []
    for r in rows:
        d = dict(r._mapping)
        d["flags"] = [f for f in d["flags"].split(",") if f]
        items.append(d)
    return items, total
