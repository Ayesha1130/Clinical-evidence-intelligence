"""
Sets placeholder-but-valid-shaped env vars *before* any `app.*` module is
imported, since `app.core.config.get_settings()` is called at module import
time by app.db.session. This lets schema/unit tests run without real
Supabase/OpenAI credentials while still exercising real validation logic —
tests that need a real LLM or DB call are marked and skipped unless the
corresponding env var is actually present (see test files for that pattern).
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/clinical_evidence_test")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("NCBI_EMAIL", "test@example.com")

import socket
import urllib.parse
import pytest


def _is_db_reachable() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except Exception:
        return False


_DB_AVAILABLE = _is_db_reachable()

DB_TEST_MODULES = {
    "test_ask_this_paper_api",
    "test_evidence_grading_service",
    "test_evidence_map_service",
    "test_full_pipeline_phase4_integration",
    "test_full_pipeline_phase5_integration",
    "test_pagination",
    "test_rag_service",
    "test_report_generation",
    "test_research_pipeline_integration",
    "test_security_hardening",
    "test_sse_events",
    "test_study_analysis_pipeline",
    "test_study_detail_and_save_api",
}


def pytest_runtest_setup(item):
    if not _DB_AVAILABLE:
        module_name = getattr(item.module, "__name__", "").split(".")[-1]
        if module_name in DB_TEST_MODULES or "db" in item.keywords:
            pytest.skip("Live database not reachable at DATABASE_URL (skipping integration test)")

