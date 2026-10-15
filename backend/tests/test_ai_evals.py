"""
Wraps evals/run_evals.py as pytest tests so the AI safety evaluation
dataset runs alongside the normal suite, while evals/run_evals.py remains
independently runnable as a human-readable report.
"""
import pytest

from evals.eval_dataset import CONFLICT_CASES, STUDY_ANALYSIS_VALIDITY_CASES, VERIFICATION_CASES
from evals.run_evals import ScriptedLLM
from app.agents.evidence_verification import EvidenceVerificationAgent
from app.schemas.evidence_verification import EvidenceVerificationInput
from app.schemas.study_analysis import StudyAnalysisOutput
from app.services.conflict_detection_service import directions_conflict


@pytest.mark.parametrize("case", VERIFICATION_CASES, ids=[c.name for c in VERIFICATION_CASES])
@pytest.mark.asyncio
async def test_verification_eval_case(case):
    agent = EvidenceVerificationAgent(ScriptedLLM(case.llm_response))
    result = await agent._execute(
        EvidenceVerificationInput(claim_text=case.claim_text, study_id="eval", document_text=case.document_text)
    )
    assert result.verification_status.value == case.expected_status
    assert (result.supporting_excerpt is not None) == case.expect_excerpt_present


@pytest.mark.parametrize("case", CONFLICT_CASES, ids=[c.name for c in CONFLICT_CASES])
def test_conflict_eval_case(case):
    detected = directions_conflict(case.direction_a, case.direction_b) is not None
    assert detected == case.expect_conflict


@pytest.mark.parametrize("case", STUDY_ANALYSIS_VALIDITY_CASES, ids=[c.name for c in STUDY_ANALYSIS_VALIDITY_CASES])
def test_study_analysis_validity_eval_case(case):
    if case.expect_valid:
        StudyAnalysisOutput.model_validate(case.llm_response)
    else:
        with pytest.raises(Exception):
            StudyAnalysisOutput.model_validate(case.llm_response)
