"""
Research endpoints.

POST /{id}/start dispatches the full research pipeline as a background
task (see app/services/pipeline_service.py) and returns immediately with
status RUNNING — real-time progress is available via GET /{id}/events
(Server-Sent Events), and the final result is read back via GET /{id} or
the various sub-resource endpoints below once the job reaches a terminal
status (COMPLETED/PARTIAL/FAILED).
"""
import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import StreamingResponse

from app.core.event_bus import event_bus
from app.core.rate_limit import rate_limit
from app.core.security import CurrentUser, get_current_user
from app.db.session import get_db
from app.integrations.llm import get_llm_client
from app.integrations.embeddings import get_embedding_client
from app.models.evidence import Conflict, EvidenceClaim, EvidenceLink, ResearchReport, Source, Study
from app.models.research import AgentRun, ResearchJob, ResearchQuery
from app.schemas.research import (
    AgentRunOut,
    ResearchJobOut,
    ResearchQueryCreate,
    ResearchQueryOut,
)
from app.schemas.evidence import ConflictOut, EvidenceClaimOut, EvidenceGradeOut
from app.schemas.report import EvidenceMapOut, ReportOut
from app.schemas.study import StudyOut
from app.services.conflict_detection_service import run_conflict_detection
from app.services.evidence_grading_service import compute_evidence_grade
from app.services.evidence_verification_service import run_evidence_verification
from app.services.rag_indexing_service import index_studies_for_job
from app.services.report_generation_service import generate_report
from app.services.evidence_map_service import build_evidence_map
from app.services.pipeline_service import run_research_pipeline
from app.services.research_service import run_source_research
from app.services.study_analysis_service import run_study_analysis

router = APIRouter(prefix="/api/research", tags=["research"])


@router.post("", response_model=ResearchQueryOut, status_code=status.HTTP_201_CREATED)
async def create_research_query(
    body: ResearchQueryCreate,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = ResearchQuery(
        user_id=user.id,
        raw_question=body.raw_question,
        population=body.population,
        intervention=body.intervention,
        comparator=body.comparator,
        outcomes=body.outcomes,
        study_types=body.study_types,
        date_range=body.date_range,
        sources=body.sources,
        status="DRAFT",
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)
    return query


@router.get("", response_model=list[ResearchQueryOut])
async def list_research_queries(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    result = await db.execute(
        select(ResearchQuery)
        .where(ResearchQuery.user_id == user.id)
        .order_by(ResearchQuery.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


async def _get_owned_query(query_id: UUID, user: CurrentUser, db: AsyncSession) -> ResearchQuery:
    result = await db.execute(
        select(ResearchQuery).where(ResearchQuery.id == query_id, ResearchQuery.user_id == user.id)
    )
    query = result.scalar_one_or_none()
    if query is None:
        # Same 404 whether it doesn't exist or belongs to someone else —
        # never leak existence of another user's data.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Research query not found.")
    return query


@router.get("/{query_id}", response_model=ResearchQueryOut)
async def get_research_query(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_owned_query(query_id, user, db)


@router.post("/{query_id}/start", response_model=ResearchJobOut, status_code=status.HTTP_202_ACCEPTED)
async def start_research(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("research_start", max_requests=10, window_seconds=60.0)),
):
    """Creates the job and dispatches the full pipeline as a background
    task, returning immediately with status RUNNING. Real-time progress is
    available via GET /{query_id}/events (SSE) — the response here is
    intentionally not the final result; poll GET /{query_id} or subscribe
    to the event stream to know when it's done."""
    query = await _get_owned_query(query_id, user, db)

    job = ResearchJob(research_query_id=query.id, status="RUNNING", started_at=datetime.now(timezone.utc))
    db.add(job)
    query.status = "RUNNING"
    await db.commit()
    await db.refresh(job)

    asyncio.create_task(run_research_pipeline(job.id, query.id))

    return job


@router.get("/{query_id}/events")
async def stream_research_events(
    request: Request,
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events stream of real pipeline progress for the latest
    job of this research question. Ownership is checked before
    subscribing — a job_id is never guessable-and-usable across users."""
    await _get_owned_query(query_id, user, db)  # ownership check
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No research job found for this query.")

    async def event_generator():
        queue = event_bus.subscribe(str(job_id))
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Keep-alive comment line so intermediary proxies/load
                    # balancers don't time out an idle SSE connection.
                    yield ": keep-alive\n\n"
                    continue

                payload = json.dumps({"event": event.event, "data": event.data, "timestamp": event.timestamp})
                yield f"event: {event.event}\ndata: {payload}\n\n"

                if event.event == "pipeline_completed":
                    break
        finally:
            event_bus.unsubscribe(str(job_id), queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/{query_id}/agent-runs", response_model=list[AgentRunOut])
async def list_agent_runs(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_query(query_id, user, db)  # ownership check
    result = await db.execute(
        select(AgentRun)
        .join(ResearchJob, ResearchJob.id == AgentRun.research_job_id)
        .where(ResearchJob.research_query_id == query_id)
        .order_by(AgentRun.created_at.asc())
    )
    return result.scalars().all()


@router.get("/{query_id}/studies", response_model=list[StudyOut])
async def list_studies_for_research(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    await _get_owned_query(query_id, user, db)  # ownership check
    result = await db.execute(
        select(Study)
        .options(selectinload(Study.source), selectinload(Study.study_findings))
        .join(Source, Source.id == Study.source_id)
        .join(ResearchJob, ResearchJob.id == Source.research_job_id)
        .where(ResearchJob.research_query_id == query_id)
        .order_by(Study.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    studies = result.scalars().all()
    return [StudyOut.from_orm_with_source(s) for s in studies]


async def _latest_job_id_for_query(query_id: UUID, db: AsyncSession) -> UUID | None:
    result = await db.execute(
        select(ResearchJob.id)
        .where(ResearchJob.research_query_id == query_id)
        .order_by(ResearchJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/{query_id}/job", response_model=ResearchJobOut)
async def get_latest_job(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetches the latest job's full detail (status, evidence_grade,
    failure_summary) — needed now that /start returns immediately with
    status RUNNING rather than the final result. A frontend polls this (or
    subscribes to GET /{id}/events) to know when the pipeline is done."""
    await _get_owned_query(query_id, user, db)  # ownership check
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No research job found for this query.")
    result = await db.execute(select(ResearchJob).where(ResearchJob.id == job_id))
    return result.scalar_one()


@router.get("/{query_id}/evidence", response_model=list[EvidenceClaimOut])
async def list_evidence_claims(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_query(query_id, user, db)  # ownership check
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        return []
    result = await db.execute(
        select(EvidenceClaim)
        .options(selectinload(EvidenceClaim.evidence_links))
        .where(EvidenceClaim.research_job_id == job_id)
        .order_by(EvidenceClaim.created_at.asc())
    )
    return [EvidenceClaimOut.from_orm_model(c) for c in result.scalars().all()]


@router.get("/{query_id}/conflicts", response_model=list[ConflictOut])
async def list_conflicts(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_query(query_id, user, db)  # ownership check
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        return []
    result = await db.execute(
        select(Conflict).where(Conflict.research_job_id == job_id).order_by(Conflict.created_at.asc())
    )
    return [ConflictOut.from_orm_model(c) for c in result.scalars().all()]


@router.get("/{query_id}/grade", response_model=EvidenceGradeOut)
async def get_evidence_grade(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_query(query_id, user, db)  # ownership check
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        return EvidenceGradeOut(grade=None, explanation=None)
    result = await db.execute(select(ResearchJob).where(ResearchJob.id == job_id))
    job = result.scalar_one()
    return EvidenceGradeOut(grade=job.evidence_grade, explanation=job.grading_explanation)


@router.post("/{query_id}/index", status_code=status.HTTP_200_OK)
async def reindex_research_job(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("research_index", max_requests=10, window_seconds=60.0)),
):
    """Manually (re-)runs Phase 6 indexing for the latest job of this
    research question. Idempotent — safe to call repeatedly."""
    await _get_owned_query(query_id, user, db)  # ownership check
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No research job found for this query.")

    embedding_client = get_embedding_client()
    summary = await index_studies_for_job(db, research_job_id=job_id, embedding_client=embedding_client)
    return {
        "documents_indexed": summary.documents_indexed,
        "chunks_created": summary.chunks_created,
        "documents_skipped_empty": summary.documents_skipped_empty,
        "failed": summary.failed,
    }


@router.get("/{query_id}/report", response_model=ReportOut)
async def get_latest_report(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_query(query_id, user, db)  # ownership check
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No research job found for this query.")

    result = await db.execute(
        select(ResearchReport)
        .where(ResearchReport.research_job_id == job_id)
        .order_by(ResearchReport.created_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No report has been generated for this research yet.",
        )
    return report


@router.post("/{query_id}/report", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def regenerate_report(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually (re-)generates the report for the latest job of this
    research question — useful if Phase 5 data has changed or the first
    attempt failed."""
    query = await _get_owned_query(query_id, user, db)
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No research job found for this query.")

    result = await db.execute(select(ResearchJob).where(ResearchJob.id == job_id))
    job = result.scalar_one()
    llm = get_llm_client()
    return await generate_report(
        db, research_job_id=job_id, research_query=query, llm=llm, evidence_grade=job.evidence_grade or "INSUFFICIENT"
    )


@router.get("/{query_id}/evidence-map", response_model=EvidenceMapOut)
async def get_evidence_map(
    query_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = await _get_owned_query(query_id, user, db)
    job_id = await _latest_job_id_for_query(query_id, db)
    if job_id is None:
        return EvidenceMapOut(nodes=[], edges=[])
    data = await build_evidence_map(db, research_job_id=job_id, research_question=query.raw_question)
    return EvidenceMapOut(**data)
