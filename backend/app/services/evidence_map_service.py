"""
Evidence Map data assembly.

Purely deterministic — no LLM. Shapes existing studies/conflicts data into
a node/edge graph: the research question is the center node, each study is
a node carrying its type/year/effect-direction/relevance, and conflicting
study pairs become distinguishable edges.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.evidence import Conflict, Source, Study


def _dominant_direction(study: Study) -> str | None:
    if not study.study_findings:
        return None
    directions = [f.effect_direction for f in study.study_findings if f.effect_direction]
    if not directions:
        return None
    unique = set(directions)
    if len(unique) == 1:
        return unique.pop()
    return "UNCLEAR"


async def build_evidence_map(db: AsyncSession, research_job_id: UUID, research_question: str) -> dict:
    studies_result = await db.execute(
        select(Study)
        .options(selectinload(Study.source), selectinload(Study.study_findings))
        .join(Source, Source.id == Study.source_id)
        .where(Source.research_job_id == research_job_id)
    )
    studies = studies_result.scalars().all()

    conflicts_result = await db.execute(select(Conflict).where(Conflict.research_job_id == research_job_id))
    conflicts = conflicts_result.scalars().all()

    conflicted_study_ids = {c.study_a_id for c in conflicts} | {c.study_b_id for c in conflicts}

    nodes = [{"id": "research_question", "type": "question", "label": research_question}]
    for s in studies:
        nodes.append(
            {
                "id": str(s.id),
                "type": "study",
                "label": s.source.title,
                "study_type": s.study_type or s.source.source_type,
                "origin": s.source.origin,
                "year": s.source.published_date.year if s.source.published_date else None,
                "effect_direction": _dominant_direction(s),
                "relevance_score": float(s.relevance_score) if s.relevance_score is not None else None,
                "has_conflict": s.id in conflicted_study_ids,
            }
        )

    edges = [{"source": "research_question", "target": str(s.id), "type": "informs"} for s in studies]
    for c in conflicts:
        edges.append(
            {
                "source": str(c.study_a_id),
                "target": str(c.study_b_id),
                "type": "conflict",
                "outcome": c.conflicting_outcome,
                "explanation": c.possible_explanation,
            }
        )

    return {"nodes": nodes, "edges": edges}
