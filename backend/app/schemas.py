from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class UploadSummary(BaseModel):
    id: str
    filename: str
    uploaded_at: datetime
    rows_received: int
    records_stored: int
    start_ts: datetime
    end_ts: datetime


class UploadDetail(UploadSummary):
    report: dict[str, Any]


class CheckRecord(BaseModel):
    id: int
    service_id: str
    service_name: str
    ts: datetime
    status_code: int | None
    latency_ms: float | None
    outcome: str
    agent: str
    region: str
    raw_timestamp: str
    flags: list[str]


class CheckPage(BaseModel):
    items: list[CheckRecord]
    total: int
    page: int
    page_size: int
