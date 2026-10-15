# Test Results: Clinical Evidence Intelligence

This report documents the verification and test execution results for the entire frontend and backend test suites.

---

## 1. Backend Test Suite (Pytest)

- **Test Framework:** `pytest 8.3.3`, `pytest-asyncio 0.24.0`
- **Execution Environment:** Python 3.12.10 (win32)
- **Command:** `pytest -v`
- **Summary:** **92 passed, 63 skipped, 0 failed, 0 errors in 6.56s**

### Test Breakdown by Module

| Module | Total Tests | Passed | Skipped | Status | Description |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `tests/test_ai_evals.py` | 14 | 14 | 0 | PASSED | Golden eval dataset for conflict detection & study analysis |
| `tests/test_chunking.py` | 9 | 9 | 0 | PASSED | Document chunking, char limits, overlap, boundary handling |
| `tests/test_clinical_trials_parser.py` | 2 | 2 | 0 | PASSED | API v2 trial record parsing and field extraction |
| `tests/test_conflict_detection_service.py` | 15 | 15 | 0 | PASSED | Conflict detection logic across outcomes and directions |
| `tests/test_embedding_client.py` | 3 | 3 | 0 | PASSED | Embedding dimension validation (1536 dim enforcement) |
| `tests/test_event_bus.py` | 7 | 7 | 0 | PASSED | Event bus subscription, job scoping, history replay |
| `tests/test_evidence_verification_agent.py` | 11 | 11 | 0 | PASSED | Verification agent excerpt matching & hallucination checks |
| `tests/test_health.py` | 1 | 1 | 0 | PASSED | API health check endpoint verification |
| `tests/test_normalization_service.py` | 7 | 7 | 0 | PASSED | Cross-source deduplication, DOI matching, title matching |
| `tests/test_pubmed_parser.py` | 2 | 2 | 0 | PASSED | NCBI efetch XML parser, abstract sectioning, DOI extraction |
| `tests/test_query_analyzer_schema.py` | 3 | 3 | 0 | PASSED | PICO schema parsing and unresearchable query safety detection |
| `tests/test_rate_limit.py` | 6 | 6 | 0 | PASSED | Sliding-window in-memory rate limiter and expiration |
| `tests/test_study_analysis_agent.py` | 9 | 9 | 0 | PASSED | Study analysis agent parsing, effect directions, sample sizes |
| `tests/test_tavily_client.py` | 3 | 3 | 0 | PASSED | Tavily client, query formatting, missing key handling |
| *DB Integration Tests (13 modules)* | 63 | 0 | 63 | SKIPPED | Safely skipped when live PostgreSQL database is unreachable |

*Note on Skipped Tests: The 63 integration tests exercise end-to-end database transactions (`test_ask_this_paper_api`, `test_evidence_grading_service`, `test_rag_service`, `test_report_generation`, etc.). When connected to an active Supabase or PostgreSQL instance via `DATABASE_URL`, these tests execute against the live database.*

---

## 2. Frontend Test Suite (Vitest + Testing Library)

- **Test Framework:** `vitest 2.1.1`, `@testing-library/react 16.0.1`, `@testing-library/jest-dom 6.5.0`
- **Execution Environment:** Node.js, JSDOM 25.0.0
- **Command:** `npm test`
- **Summary:** **7 test files passed, 29 tests passed, 0 failed in 14.89s**

### Test Suite Summary

| Test File | Tests | Duration | Status | Description |
| :--- | :---: | :---: | :---: | :--- |
| `tests/components/Accessibility.test.tsx` | 5 | ~1.1s | PASSED | `axe-core` accessibility compliance across all components |
| `tests/components/AskPaperPanel.test.tsx` | 5 | ~2.0s | PASSED | Grounded Q&A, citation excerpts, loading & empty states |
| `tests/components/EvidenceMap.test.tsx` | 3 | ~0.4s | PASSED | Visual node rendering, directional styles, conflict flags |
| `tests/components/LandingPage.test.tsx` | 5 | ~0.9s | PASSED | Hero, research question form, sources, safety disclaimer |
| `tests/components/ResearchReport.test.tsx` | 5 | ~0.4s | PASSED | GRADE badges, citation links, conflict sections, sources |
| `tests/components/StudyPage.test.tsx` | 2 | ~0.2s | PASSED | Study details rendering and 404/not found states |
| `tests/components/AuthAndNewResearch.test.tsx` | 4 | ~0.7s | PASSED | Login mode toggle, inquiry form prefill, PICO expander |

---

## 3. Static Type Analysis & Production Build

### TypeScript Compilation (`npx tsc --noEmit`)
- Result: **0 errors** across entire frontend codebase.

### Next.js ESLint Check (`npm run lint`)
- Result: **0 warnings, 0 errors** (`✔ No ESLint warnings or errors`).
- Verified rule compliance including `react/no-unescaped-entities` and core web vitals.

### Next.js Production Build (`npm run build`)
- Result: **0 errors**. Successfully generated static and dynamic routes:
  - `○ /` (Static - 90.1 kB first load)
  - `○ /_not-found` (Static - 88.2 kB)
  - `○ /login` (Static - 134 kB)
  - `○ /research/new` (Static - 136 kB)
  - `ƒ /research/[id]` (Dynamic - 128 kB)
  - `ƒ /studies/[id]` (Dynamic - 126 kB)

