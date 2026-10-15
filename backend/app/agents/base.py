"""
Reusable agent execution framework.

Every agent in the pipeline extends `BaseAgent`, implements `_execute`,
and gets, for free: an `agent_runs` row logging input/output/error, retry
with backoff, and timeout handling. A failure here never crashes the whole
pipeline — the caller decides whether the job continues as PARTIAL.
"""
import abc
import asyncio
import logging
from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential

from app.models.research import AgentRun

logger = logging.getLogger("agents")

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class AgentExecutionError(Exception):
    pass


class BaseAgent(abc.ABC, Generic[InputT, OutputT]):
    name: str = "base_agent"
    timeout_seconds: float = 60.0
    max_attempts: int = 3

    @abc.abstractmethod
    async def _execute(self, payload: InputT) -> OutputT:
        """Do the actual work. Raise AgentExecutionError (or let exceptions
        propagate) on failure — retries and logging are handled by run()."""

    async def run(self, db: AsyncSession, research_job_id: UUID, payload: InputT) -> OutputT:
        agent_run = AgentRun(
            research_job_id=research_job_id,
            agent_name=self.name,
            status="running",
            input=payload.model_dump(mode="json"),
            started_at=datetime.now(timezone.utc),
        )
        db.add(agent_run)
        await db.commit()
        await db.refresh(agent_run)

        try:
            result = await self._run_with_retry(payload)
            agent_run.status = "completed"
            agent_run.output = result.model_dump(mode="json")
            agent_run.completed_at = datetime.now(timezone.utc)
            await db.commit()
            return result
        except Exception as exc:  # noqa: BLE001 — deliberately broad: this is the pipeline's failure boundary
            underlying = exc.last_attempt.exception() if isinstance(exc, RetryError) else exc
            logger.exception("Agent %s failed for job %s", self.name, research_job_id)
            agent_run.status = "failed"
            agent_run.error = str(underlying)
            agent_run.completed_at = datetime.now(timezone.utc)
            await db.commit()
            raise AgentExecutionError(f"{self.name} failed: {underlying}") from exc

    async def _run_with_retry(self, payload: InputT) -> OutputT:
        @retry(stop=stop_after_attempt(self.max_attempts), wait=wait_exponential(multiplier=1, min=1, max=10))
        async def _attempt() -> OutputT:
            return await asyncio.wait_for(self._execute(payload), timeout=self.timeout_seconds)

        return await _attempt()
