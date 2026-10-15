"""
Runs the evaluation dataset (evals/eval_dataset.py) against the real
production agents and services, and prints a metrics report.

Usage:
    cd backend
    python -m evals.run_evals

Exits with status 1 if any case fails, so this can be wired into CI.
"""
import asyncio
import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/unused")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "eval")
os.environ.setdefault("SUPABASE_JWT_SECRET", "eval")
os.environ.setdefault("OPENAI_API_KEY", "eval")
os.environ.setdefault("NCBI_EMAIL", "eval@example.com")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.evidence_verification import EvidenceVerificationAgent  # noqa: E402
from app.schemas.evidence_verification import EvidenceVerificationInput  # noqa: E402
from app.schemas.study_analysis import StudyAnalysisOutput  # noqa: E402
from app.services.conflict_detection_service import directions_conflict  # noqa: E402
from evals.eval_dataset import (  # noqa: E402
    CONFLICT_CASES,
    STUDY_ANALYSIS_VALIDITY_CASES,
    VERIFICATION_CASES,
)


class ScriptedLLM:
    def __init__(self, response: dict):
        self._response = json.dumps(response)

    async def complete_json(self, system_prompt, user_prompt):
        return self._response

    async def complete_text(self, system_prompt, user_prompt):
        raise NotImplementedError

    async def embed(self, texts):
        raise NotImplementedError


async def run_verification_evals() -> tuple[int, int, list[str]]:
    passed, total, failures = 0, 0, []
    for case in VERIFICATION_CASES:
        total += 1
        agent = EvidenceVerificationAgent(ScriptedLLM(case.llm_response))
        result = await agent._execute(
            EvidenceVerificationInput(claim_text=case.claim_text, study_id="eval", document_text=case.document_text)
        )
        status_ok = result.verification_status.value == case.expected_status
        excerpt_ok = (result.supporting_excerpt is not None) == case.expect_excerpt_present
        if status_ok and excerpt_ok:
            passed += 1
        else:
            failures.append(
                f"  FAIL {case.name}: status={result.verification_status.value} "
                f"(expected {case.expected_status}), excerpt_present={result.supporting_excerpt is not None} "
                f"(expected {case.expect_excerpt_present})"
            )
    return passed, total, failures


def run_conflict_evals() -> tuple[int, int, list[str]]:
    passed, total, failures = 0, 0, []
    for case in CONFLICT_CASES:
        total += 1
        confidence = directions_conflict(case.direction_a, case.direction_b)
        detected = confidence is not None
        if detected == case.expect_conflict:
            passed += 1
        else:
            failures.append(
                f"  FAIL {case.name}: {case.direction_a} vs {case.direction_b} -> "
                f"conflict={detected} (expected {case.expect_conflict})"
            )
    return passed, total, failures


def run_study_analysis_validity_evals() -> tuple[int, int, list[str]]:
    passed, total, failures = 0, 0, []
    for case in STUDY_ANALYSIS_VALIDITY_CASES:
        total += 1
        try:
            StudyAnalysisOutput.model_validate(case.llm_response)
            was_valid = True
        except Exception:
            was_valid = False
        if was_valid == case.expect_valid:
            passed += 1
        else:
            failures.append(f"  FAIL {case.name}: schema accepted={was_valid} (expected {case.expect_valid})")
    return passed, total, failures


async def main() -> int:
    print("Clinical Evidence Intelligence — AI Safety Evaluation\n" + "=" * 55)

    v_passed, v_total, v_failures = await run_verification_evals()
    print(f"\nEvidence Verification grounding: {v_passed}/{v_total} passed")
    for f in v_failures:
        print(f)

    c_passed, c_total, c_failures = run_conflict_evals()
    print(f"\nConflict Detection accuracy: {c_passed}/{c_total} passed")
    for f in c_failures:
        print(f)

    s_passed, s_total, s_failures = run_study_analysis_validity_evals()
    print(f"\nStudy Analysis structured-output validity: {s_passed}/{s_total} passed")
    for f in s_failures:
        print(f)

    total_passed = v_passed + c_passed + s_passed
    total_cases = v_total + c_total + s_total
    print("\n" + "=" * 55)
    print(f"TOTAL: {total_passed}/{total_cases} passed ({100 * total_passed / total_cases:.0f}%)")

    return 0 if total_passed == total_cases else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
