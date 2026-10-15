"""
Report-scoped endpoints. Ownership is enforced by joining
ResearchReport -> ResearchJob -> ResearchQuery.user_id, same pattern as
every other resource in this API.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, get_current_user
from app.db.session import get_db
from app.models.evidence import ResearchReport, SavedReport
from app.models.research import ResearchJob, ResearchQuery
from app.schemas.report import ReportOut, SaveReportOut

router = APIRouter(prefix="/api/reports", tags=["reports"])


async def _get_owned_report(report_id: UUID, user: CurrentUser, db: AsyncSession) -> ResearchReport:
    result = await db.execute(
        select(ResearchReport)
        .join(ResearchJob, ResearchJob.id == ResearchReport.research_job_id)
        .join(ResearchQuery, ResearchQuery.id == ResearchJob.research_query_id)
        .where(ResearchReport.id == report_id, ResearchQuery.user_id == user.id)
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return report


@router.get("/{report_id}", response_model=ReportOut)
async def get_report(
    report_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_owned_report(report_id, user, db)


@router.post("/{report_id}/save", response_model=SaveReportOut)
async def save_report(
    report_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_report(report_id, user, db)  # ownership check
    existing = await db.execute(
        select(SavedReport).where(SavedReport.user_id == user.id, SavedReport.report_id == report_id)
    )
    if existing.scalar_one_or_none() is None:
        db.add(SavedReport(user_id=user.id, report_id=report_id))
        await db.commit()
    return SaveReportOut(saved=True)


@router.delete("/{report_id}/save", response_model=SaveReportOut)
async def unsave_report(
    report_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_report(report_id, user, db)  # ownership check
    await db.execute(delete(SavedReport).where(SavedReport.user_id == user.id, SavedReport.report_id == report_id))
    await db.commit()
    return SaveReportOut(saved=False)
