"""
Runs the Study Analysis Agent for every study retrieved in Phase 3 for a
research job. Each study is fully independent: one failing (LLM error,
invalid structured output, timeout) never stops analysis of the others,
and never fails the whole job — it's recorded so the job ends up PARTIAL
with a clear list of which studies couldn't be analyzed.
"""
import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.base import AgentExecutionError
from app.agents.study_analysis import StudyAnalysisAgent
from app.integrations.llm import LLMClient
from app.models.evidence import Source, Study
from app.models.research import ResearchQuery
from app.services.study_analysis_persistence import build_study_analysis_input, persist_study_analysis

logger = logging.getLogger("study_analysis_service")


@dataclass
class StudyAnalysisSummary:
    analyzed: int = 0
    skipped_no_content: int = 0
    failed: list[dict] = field(default_factory=list)  # [{"study_id": ..., "title": ..., "error": ...}]

    @property
    def any_failed(self) -> bool:
        return len(self.failed) > 0

    @property
    def total_considered(self) -> int:
        return self.analyzed + self.skipped_no_content + len(self.failed)


async def run_study_analysis(
    db: AsyncSession, research_job_id: UUID, research_query: ResearchQuery, llm: LLMClient
) -> StudyAnalysisSummary:
    result = await db.execute(
        select(Study)
        .options(selectinload(Study.source), selectinload(Study.documents))
        .join(Source, Source.id == Study.source_id)
        .where(Source.research_job_id == research_job_id)
    )
    studies = result.scalars().all()

    summary = StudyAnalysisSummary()
    agent = StudyAnalysisAgent(llm)

    for study in studies:
        source = study.source
        document = study.documents[0] if study.documents else None

        agent_input = build_study_analysis_input(
            study=study,
            source=source,
            document=document,
            research_question=research_query.raw_question,
            population_hint=research_query.population,
            intervention_hint=research_query.intervention,
            comparator_hint=research_query.comparator,
            outcomes_hint=list(research_query.outcomes) if research_query.outcomes else [],
        )

        try:
            output = await agent.run(db, research_job_id, agent_input)
        except AgentExecutionError as exc:
            logger.warning("Study analysis failed for study %s: %s", study.id, exc)
            summary.failed.append({"study_id": str(study.id), "title": source.title, "error": str(exc)})
            continue

        if output.evidence_level.value == "no_content_available":
            summary.skipped_no_content += 1
        else:
            summary.analyzed += 1

        await persist_study_analysis(db, study, source, output, document)
        await db.commit()

    return summary
