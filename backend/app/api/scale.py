"""Scale ingestion (Phase 5.1b): scale_bridge posts readings, the backend stores them.

Stored exactly as received: no filtering, no decisions, no WebSocket yet. The negative undershoot
frame the real adapter sends on removal (-30 to -50 g) is valid data and is kept.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select

from ..db import get_session_factory
from ..models import ScaleReading
from ..schemas import ScaleBatchIn, ScaleReadingOut

router = APIRouter(tags=["scale"])


@router.post("/scale/readings")
async def post_readings(body: ScaleBatchIn, session_factory=Depends(get_session_factory)):
    """A batch from scale_bridge, in reception order. Returns how many rows were stored."""
    rows = [ScaleReading(received_at=r.received_at, grams=r.grams, raw=r.raw, source=body.source)
            for r in body.readings]

    def store():
        with session_factory() as db:
            db.add_all(rows)
            db.commit()

    if rows:
        await run_in_threadpool(store)
    return {"stored": len(rows)}


@router.get("/scale/readings", response_model=list[ScaleReadingOut])
async def recent_readings(seconds: float = Query(default=60, gt=0, le=86_400),
                          limit: int = Query(default=500, ge=1, le=5000),
                          source: str | None = None,
                          session_factory=Depends(get_session_factory)):
    """Readings received in the last N seconds, oldest first (for checking what was stored)."""
    since = datetime.now(timezone.utc) - timedelta(seconds=seconds)

    def query():
        with session_factory() as db:
            stmt = (select(ScaleReading).where(ScaleReading.received_at >= since)
                    .order_by(ScaleReading.received_at.desc(), ScaleReading.id.desc()).limit(limit))
            if source:
                stmt = stmt.where(ScaleReading.source == source)
            return [ScaleReadingOut.model_validate(r) for r in reversed(db.scalars(stmt).all())]

    return await run_in_threadpool(query)


@router.get("/scale/summary")
async def summary(session_factory=Depends(get_session_factory)):
    """Per source: row count, first/last reception time, min/max grams."""
    def query():
        with session_factory() as db:
            q = (select(ScaleReading.source, func.count(), func.min(ScaleReading.received_at),
                        func.max(ScaleReading.received_at), func.min(ScaleReading.grams),
                        func.max(ScaleReading.grams))
                 .group_by(ScaleReading.source).order_by(ScaleReading.source))
            return [{"source": s, "count": n, "first_received_at": a, "last_received_at": b,
                     "min_grams": lo, "max_grams": hi} for s, n, a, b, lo, hi in db.execute(q)]

    return await run_in_threadpool(query)
