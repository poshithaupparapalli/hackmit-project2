import asyncio

from fastapi import APIRouter

from app import analyst
from app.db import get_conn, meta_get, now_ms
from app.models import AnalyzeResponse, StatusResponse

router = APIRouter()


def _run_analysis_sync() -> None:
    analyst.run_analysis(get_conn(), use_llm=True)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze() -> AnalyzeResponse:
    asyncio.get_event_loop().run_in_executor(None, _run_analysis_sync)
    return AnalyzeResponse(queued=True)


@router.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    conn = get_conn()
    last_event = meta_get(conn, "last_event_at")
    last_event_ms = int(last_event) if last_event else None
    return StatusResponse(
        observerOnline=bool(last_event_ms and (now_ms() - last_event_ms) < 120_000),
        paused=False,
        lastEventAt=last_event_ms,
        lastAnalysisAt=analyst.last_analysis_at(conn),
        newEventsPending=analyst.new_events_pending(conn),
    )
