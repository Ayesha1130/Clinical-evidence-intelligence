-- Phase 5 needs somewhere to store the evidence grade + its transparent
-- explanation. research_reports.evidence_grade already exists in the
-- schema, but research_reports also requires NOT NULL `sections` and
-- `citations` (Phase 7 / Report Generation's responsibility) — writing a
-- placeholder row there now would mean starting Report Generation early.
-- research_jobs is the correct home: the grade is a property of this
-- research run, computed once Phase 5 completes, independent of whether a
-- narrative report has been generated yet.

alter table research_jobs
    add column if not exists evidence_grade text
        check (evidence_grade in ('STRONG', 'MODERATE', 'LIMITED', 'INSUFFICIENT')),
    add column if not exists grading_explanation jsonb;
