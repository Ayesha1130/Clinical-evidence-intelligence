"""
The full research pipeline, run as a background asyncio task (dispatched
by POST /api/research/{id}/start, which returns immediately once the job
row exists).

Refactored from the old inline request-handler logic to:
  1. open its own DB session (the request-scoped session is gone by the
     time this runs),
  2. publish a real event to app.core.event_bus at the start/end of each
     stage — every event corresponds to something that actually just
     happened, never a timer-based fake progress tick.

GET /api/research/{id}/events (the SSE endpoint) subscribes to these same
events for a given job_id.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.agents.query_analyzer import QueryAnalyzerAgent, QueryAnalyzerInput
from app.core.event_bus import event_bus
from app.db.session import AsyncSessionLocal
from app.integrations.embeddings import get_embedding_client
from app.integrations.llm import get_llm_client
from app.models.research import ResearchJob, ResearchQuery
from app.services.conflict_detection_service import run_conflict_detection
from app.services.evidence_grading_service import compute_evidence_grade
from app.services.evidence_verification_service import run_evidence_verification
from app.services.rag_indexing_service import index_studies_for_job
from app.services.report_generation_service import generate_report
from app.services.research_service import run_source_research
from app.services.study_analysis_service import run_study_analysis

logger = logging.getLogger("pipeline_service")


def _analyzer_input_from(query: ResearchQuery) -> QueryAnalyzerInput:
    return QueryAnalyzerInput(
        raw_question=query.raw_question,
        population_hint=query.population,
        intervention_hint=query.intervention,
        comparator_hint=query.comparator,
    )


async def _emit(job_id: UUID, event: str, data: dict | None = None) -> None:
    await event_bus.publish(str(job_id), event, data)


async def run_research_pipeline(job_id: UUID, query_id: UUID) -> None:
    """Entry point for the background task. Every exception is caught at
    the top level — a bug here must never leave a job stuck in RUNNING
    forever with no explanation."""
    async with AsyncSessionLocal() as db:
        try:
            await _run(db, job_id, query_id)
        except Exception as exc:  # noqa: BLE001 — last-resort safety net for the whole pipeline
            logger.exception("Unhandled error in research pipeline for job %s", job_id)
            job = (await db.execute(select(ResearchJob).where(ResearchJob.id == job_id))).scalar_one_or_none()
            if job is not None:
                job.status = "FAILED"
                job.failure_summary = f"The research pipeline failed unexpectedly: {exc}"
                job.completed_at = datetime.now(timezone.utc)
                query = (
                    await db.execute(select(ResearchQuery).where(ResearchQuery.id == query_id))
                ).scalar_one_or_none()
                if query is not None:
                    query.status = "FAILED"
                await db.commit()
            await _emit(job_id, "pipeline_completed", {"status": "FAILED"})


async def _run(db, job_id: UUID, query_id: UUID) -> None:
    job = (await db.execute(select(ResearchJob).where(ResearchJob.id == job_id))).scalar_one()
    query = (await db.execute(select(ResearchQuery).where(ResearchQuery.id == query_id))).scalar_one()

    await _emit(job_id, "pipeline_started", {"research_question": query.raw_question})

    llm = get_llm_client()

    await _emit(job_id, "agent_started", {"agent": "query_analyzer"})
    analyzer = QueryAnalyzerAgent(llm)
    try:
        result = await analyzer.run(db, research_job_id=job.id, payload=_analyzer_input_from(query))
    except Exception:
        await _emit(job_id, "agent_failed", {"agent": "query_analyzer"})
        job.status = "FAILED"
        job.failure_summary = "Query analysis failed. See agent_runs for details."
        job.completed_at = datetime.now(timezone.utc)
        query.status = "FAILED"
        await db.commit()
        await _emit(job_id, "pipeline_completed", {"status": "FAILED"})
        return
    await _emit(job_id, "agent_completed", {"agent": "query_analyzer"})

    if not result.is_researchable:
        job.status = "FAILED"
        job.failure_summary = result.safety_note or (
            "This looks like a request for personalized diagnosis or treatment rather than "
            "an evidence research question. Please consult a qualified healthcare professional, "
            "or rephrase as a research question (e.g. 'What does current evidence say about ...')."
        )
        job.completed_at = datetime.now(timezone.utc)
        query.status = "FAILED"
        await db.commit()
        await _emit(job_id, "pipeline_completed", {"status": "FAILED"})
        return

    query.population = result.population
    query.intervention = result.intervention
    query.comparator = result.comparator
    query.outcomes = result.outcomes
    query.study_types = result.study_types
    query.search_queries = result.search_queries.model_dump()
    await db.commit()

    await _emit(job_id, "agent_started", {"agent": "pubmed_research"})
    await _emit(job_id, "agent_started", {"agent": "clinical_trials_research"})
    await _emit(job_id, "agent_started", {"agent": "web_research"})

    summary = await run_source_research(db, research_job_id=job.id, search_queries=query.search_queries)

    for name, outcome in (
        ("pubmed_research", summary.pubmed),
        ("clinical_trials_research", summary.clinical_trials),
        ("web_research", summary.web_research),
    ):
        if outcome.status == "completed":
            await _emit(job_id, "agent_completed", {"agent": name, "count": outcome.count})
        elif outcome.status == "failed":
            await _emit(job_id, "agent_failed", {"agent": name, "error": outcome.error})
        else:
            await _emit(job_id, "agent_completed", {"agent": name, "count": 0, "note": outcome.error})

    for origin, count in summary.studies_stored.items():
        if count > 0:
            await _emit(job_id, "study_found", {"origin": origin, "count": count})

    def _source_line(name: str, outcome) -> str:
        if outcome.status == "completed":
            return f"{name}: {outcome.count} result(s)."
        if outcome.status == "unavailable":
            return f"{name}: unavailable ({outcome.error})"
        return f"{name}: failed ({outcome.error})"

    source_lines = [
        _source_line("PubMed", summary.pubmed),
        _source_line("ClinicalTrials.gov", summary.clinical_trials),
        _source_line("Web research (Tavily)", summary.web_research),
    ]
    no_source_failures = not any(
        o.status == "failed" for o in (summary.pubmed, summary.clinical_trials, summary.web_research)
    )

    if not summary.any_succeeded and summary.total_stored == 0:
        job.status = "FAILED"
        job.failure_summary = "All research sources failed or were unavailable.\n" + "\n".join(source_lines)
        job.completed_at = datetime.now(timezone.utc)
        query.status = "FAILED"
        await db.commit()
        await _emit(job_id, "pipeline_completed", {"status": "FAILED"})
        return

    if summary.total_stored == 0:
        job.status = "PARTIAL"
        job.failure_summary = "No sufficiently relevant evidence was found by any source.\n" + "\n".join(source_lines)
        job.completed_at = datetime.now(timezone.utc)
        query.status = "PARTIAL"
        await db.commit()
        await _emit(job_id, "pipeline_completed", {"status": "PARTIAL"})
        return

    await _emit(job_id, "agent_started", {"agent": "document_indexing"})
    embedding_client = get_embedding_client()
    indexing_summary = await index_studies_for_job(db, research_job_id=job.id, embedding_client=embedding_client)
    await _emit(
        job_id,
        "agent_completed" if not indexing_summary.any_failed else "agent_failed",
        {"agent": "document_indexing", "chunks_created": indexing_summary.chunks_created},
    )
    indexing_lines = [
        f"Document indexing: {indexing_summary.documents_indexed} document(s) indexed into "
        f"{indexing_summary.chunks_created} chunk(s), {indexing_summary.documents_skipped_empty} skipped (empty), "
        f"{len(indexing_summary.failed)} failed."
    ]

    await _emit(job_id, "analysis_started", {})
    await _emit(job_id, "agent_started", {"agent": "study_analysis"})
    analysis_summary = await run_study_analysis(db, research_job_id=job.id, research_query=query, llm=llm)
    await _emit(
        job_id,
        "agent_completed" if not analysis_summary.any_failed else "agent_failed",
        {"agent": "study_analysis", "analyzed": analysis_summary.analyzed, "failed": len(analysis_summary.failed)},
    )
    analysis_lines = [
        f"Study analysis: {analysis_summary.analyzed} analyzed, "
        f"{analysis_summary.skipped_no_content} skipped (no source text available), "
        f"{len(analysis_summary.failed)} failed."
    ]
    if analysis_summary.failed:
        analysis_lines.append("Failed studies:")
        analysis_lines.extend(
            f"  - {f['title']} (study_id={f['study_id']}): {f['error']}" for f in analysis_summary.failed
        )

    await _emit(job_id, "agent_started", {"agent": "evidence_verification"})
    verification_summary = await run_evidence_verification(db, research_job_id=job.id, research_query=query, llm=llm)
    await _emit(
        job_id,
        "agent_completed" if not verification_summary.any_failed else "agent_failed",
        {"agent": "evidence_verification", "claims_verified": verification_summary.claims_verified},
    )
    verification_lines = [
        f"Evidence verification: {verification_summary.claims_extracted} claim(s) extracted from "
        f"{verification_summary.studies_considered} study(ies), {verification_summary.claims_verified} verified."
    ]
    if verification_summary.extraction_failures:
        verification_lines.append(
            f"Claim extraction failed for {len(verification_summary.extraction_failures)} study(ies)."
        )
    if verification_summary.verification_failures:
        verification_lines.append(
            f"Verification failed for {len(verification_summary.verification_failures)} claim(s)."
        )

    await _emit(job_id, "agent_started", {"agent": "conflict_detection"})
    conflict_detection_failed = False
    try:
        conflicts = await run_conflict_detection(db, research_job_id=job.id)
        for c in conflicts:
            await _emit(job_id, "conflict_found", {"outcome": c.conflicting_outcome})
        await _emit(job_id, "agent_completed", {"agent": "conflict_detection", "count": len(conflicts)})
        conflict_lines = [f"Conflict detection: {len(conflicts)} conflict(s) found."]
    except Exception as exc:  # noqa: BLE001
        conflict_detection_failed = True
        await _emit(job_id, "agent_failed", {"agent": "conflict_detection", "error": str(exc)})
        conflict_lines = [f"Conflict detection failed: {exc}"]

    await _emit(job_id, "agent_started", {"agent": "evidence_grading"})
    grading_failed = False
    try:
        grading = await compute_evidence_grade(db, research_job_id=job.id)
        job.evidence_grade = grading.grade
        job.grading_explanation = grading.to_dict()
        await _emit(job_id, "agent_completed", {"agent": "evidence_grading", "grade": grading.grade})
        grading_lines = [f"Evidence grade: {grading.grade}."]
    except Exception as exc:  # noqa: BLE001
        grading_failed = True
        job.evidence_grade = "INSUFFICIENT"
        job.grading_explanation = {"error": str(exc), "note": "Grading could not be completed reliably."}
        await _emit(job_id, "agent_failed", {"agent": "evidence_grading", "error": str(exc)})
        grading_lines = [f"Evidence grading failed: {exc}"]

    await _emit(job_id, "agent_started", {"agent": "report_generation"})
    report_failed = False
    try:
        await generate_report(
            db, research_job_id=job.id, research_query=query, llm=llm, evidence_grade=job.evidence_grade
        )
        await _emit(job_id, "agent_completed", {"agent": "report_generation"})
        await _emit(job_id, "report_ready", {})
        report_lines = ["Report generation: succeeded."]
    except Exception as exc:  # noqa: BLE001
        report_failed = True
        await _emit(job_id, "agent_failed", {"agent": "report_generation", "error": str(exc)})
        report_lines = [f"Report generation failed: {exc}"]

    all_stages_clean = (
        no_source_failures
        and not indexing_summary.any_failed
        and not analysis_summary.any_failed
        and not verification_summary.any_failed
        and not conflict_detection_failed
        and not grading_failed
        and not report_failed
    )

    all_lines = (
        indexing_lines + source_lines + analysis_lines + verification_lines
        + conflict_lines + grading_lines + report_lines
    )

    if all_stages_clean:
        job.status = "COMPLETED"
        job.failure_summary = (
            f"Retrieved and fully processed {summary.total_stored} unique study/source record(s).\n"
            + "\n".join(all_lines)
        )
        query.status = "COMPLETED"
    else:
        job.status = "PARTIAL"
        job.failure_summary = (
            f"Retrieved {summary.total_stored} unique study/source record(s).\n" + "\n".join(all_lines)
        )
        query.status = "PARTIAL"

    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await _emit(job_id, "pipeline_completed", {"status": job.status})
