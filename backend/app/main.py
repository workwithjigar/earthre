from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import config, db
from .cleaning import CsvValidationError, clean_csv
from .schemas import CheckPage, UploadDetail, UploadSummary
from .stats import StatsConfig, compute_monthly, compute_stats

app = FastAPI(title="SLA Monitoring API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def _stats_config() -> StatsConfig:
    return StatsConfig(sla_target=config.SLA_TARGET, slow_ms=config.SLOW_THRESHOLD_MS)


def _require_upload(upload_id: str) -> dict:
    upload = db.get_upload(db.get_engine(), upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    return upload


def _validate_range(start: date | None, end: date | None) -> None:
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/uploads", response_model=UploadDetail, status_code=201)
async def create_upload(file: UploadFile = File(...)) -> dict:
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds {config.MAX_UPLOAD_BYTES // 1024} KB limit")
    try:
        result = clean_csv(data)
    except CsvValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return db.save_upload(db.get_engine(), file.filename or "upload.csv", result)


@app.get("/api/uploads", response_model=list[UploadSummary])
def list_uploads() -> list[dict]:
    return db.list_uploads(db.get_engine())


@app.get("/api/uploads/{upload_id}", response_model=UploadDetail)
def get_upload(upload_id: str) -> dict:
    return _require_upload(upload_id)


@app.delete("/api/uploads/{upload_id}", status_code=204, response_class=Response)
def delete_upload(upload_id: str) -> Response:
    if not db.delete_upload(db.get_engine(), upload_id):
        raise HTTPException(status_code=404, detail="Upload not found")
    return Response(status_code=204)


@app.get("/api/uploads/{upload_id}/stats")
def get_stats(upload_id: str, start: date | None = None, end: date | None = None) -> dict:
    _require_upload(upload_id)
    _validate_range(start, end)
    engine = db.get_engine()
    cfg = _stats_config()
    names = db.service_names(engine, upload_id)
    stats = compute_stats(db.fetch_for_stats(engine, upload_id, start, end), names, cfg)
    # Billing credits are per calendar month, so they always use the full dataset, never the filter.
    stats["monthly"] = compute_monthly(db.fetch_for_stats(engine, upload_id), names, cfg)
    stats["range"] = {"start": start, "end": end}
    return stats


@app.get("/api/uploads/{upload_id}/checks", response_model=CheckPage)
def get_checks(
    upload_id: str,
    start: date | None = None,
    end: date | None = None,
    service_id: str | None = None,
    outcome: Literal["up", "down", "invalid"] | None = None,
    agent: str | None = None,
    flagged_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    _require_upload(upload_id)
    _validate_range(start, end)
    items, total = db.query_checks(
        db.get_engine(),
        upload_id,
        start=start,
        end=end,
        service_id=service_id,
        outcome=outcome,
        agent=agent,
        flagged_only=flagged_only,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}
