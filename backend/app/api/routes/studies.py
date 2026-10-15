"""
Study-scoped endpoints. Ownership is enforced by joining all the way from
Study -> Source -> ResearchJob -> ResearchQuery.user_id, exactly like the
research.py endpoints do — a study can never be inspected by a user who
doesn't own the research question it came from.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import CurrentUser, get_current_user
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.integrations.embeddings import get_embedding_client
from app.integrations.llm import get_llm_client
from app.models.evidence import DocumentChunk, EvidenceClaim, EvidenceLink, SavedStudy, Source, Study
from app.models.research import ResearchJob, ResearchQuery
from app.rag.rag_service import ask_study_question
from app.schemas.evidence import EvidenceClaimOut
from app.schemas.rag import AskQuestionRequest, AskResponse
from app.schemas.study import SaveStudyOut, StudyDetailOut

router = APIRouter(prefix="/api/studies", tags=["studies"])


async def _get_owned_study_with_relations(study_id: UUID, user: CurrentUser, db: AsyncSession) -> Study:
    result = await db.execute(
        select(Study)
        .options(selectinload(Study.source), selectinload(Study.documents), selectinload(Study.study_findings))
        .join(Source, Source.id == Study.source_id)
        .join(ResearchJob, ResearchJob.id == Source.research_job_id)
        .join(ResearchQuery, ResearchQuery.id == ResearchJob.research_query_id)
        .where(Study.id == study_id, ResearchQuery.user_id == user.id)
    )
    study = result.scalar_one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study not found.")
    return study


async def _get_owned_study(study_id: UUID, user: CurrentUser, db: AsyncSession) -> Study:
    result = await db.execute(
        select(Study)
        .join(Source, Source.id == Study.source_id)
        .join(ResearchJob, ResearchJob.id == Source.research_job_id)
        .join(ResearchQuery, ResearchQuery.id == ResearchJob.research_query_id)
        .where(Study.id == study_id, ResearchQuery.user_id == user.id)
    )
    study = result.scalar_one_or_none()
    if study is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Study not found.")
    return study


@router.get("/{study_id}/evidence", response_model=list[EvidenceClaimOut])
async def list_evidence_for_study(
    study_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_study(study_id, user, db)  # ownership check
    result = await db.execute(
        select(EvidenceClaim)
        .join(EvidenceLink, EvidenceLink.evidence_claim_id == EvidenceClaim.id)
        .options(selectinload(EvidenceClaim.evidence_links))
        .where(EvidenceLink.study_id == study_id)
        .order_by(EvidenceClaim.created_at.asc())
    )
    claims = result.scalars().unique().all()
    return [EvidenceClaimOut.from_orm_model(c) for c in claims]


@router.post("/{study_id}/ask", response_model=AskResponse)
async def ask_this_paper(
    study_id: UUID,
    body: AskQuestionRequest,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _rate_limit: None = Depends(rate_limit("ask_this_paper", max_requests=20, window_seconds=60.0)),
):
    await _get_owned_study(study_id, user, db)  # ownership check — enforced before any retrieval happens
    llm = get_llm_client()
    embedding_client = get_embedding_client()
    return await ask_study_question(db, study_id, body.question, llm, embedding_client)


@router.get("/{study_id}/chunks")
async def list_chunks_for_study(
    study_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_study(study_id, user, db)  # ownership check
    result = await db.execute(
        select(DocumentChunk).where(DocumentChunk.study_id == study_id).order_by(DocumentChunk.chunk_index.asc())
    )
    chunks = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "document_id": str(c.document_id),
            "chunk_index": c.chunk_index,
            "content": c.content,
            "char_count": c.char_count,
        }
        for c in chunks
    ]


@router.get("/{study_id}", response_model=StudyDetailOut)
async def get_study_detail(
    study_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    study = await _get_owned_study_with_relations(study_id, user, db)
    return StudyDetailOut.from_orm_with_source(study)


@router.post("/{study_id}/save", response_model=SaveStudyOut)
async def save_study(
    study_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_study(study_id, user, db)  # ownership check
    existing = await db.execute(
        select(SavedStudy).where(SavedStudy.user_id == user.id, SavedStudy.study_id == study_id)
    )
    if existing.scalar_one_or_none() is None:
        db.add(SavedStudy(user_id=user.id, study_id=study_id))
        await db.commit()
    return SaveStudyOut(saved=True)


@router.delete("/{study_id}/save", response_model=SaveStudyOut)
async def unsave_study(
    study_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_study(study_id, user, db)  # ownership check
    await db.execute(delete(SavedStudy).where(SavedStudy.user_id == user.id, SavedStudy.study_id == study_id))
    await db.commit()
    return SaveStudyOut(saved=False)
