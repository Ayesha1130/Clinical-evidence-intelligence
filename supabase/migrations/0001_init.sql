-- Clinical Evidence Intelligence — initial schema
-- Run in the Supabase SQL editor (or via `supabase db push`).
-- Assumes Supabase Auth is enabled (auth.users already exists).

create extension if not exists "uuid-ossp";
create extension if not exists vector;

-- ============================================================
-- RESEARCH QUERIES + JOBS
-- ============================================================

create table if not exists research_queries (
    id              uuid primary key default uuid_generate_v4(),
    user_id         uuid not null references auth.users(id) on delete cascade,
    raw_question    text not null,
    population      text,
    intervention    text,
    comparator      text,
    outcomes        jsonb,
    study_types     jsonb,
    date_range      jsonb,
    sources         jsonb,
    search_queries  jsonb,
    status          text not null default 'DRAFT'
                        check (status in ('DRAFT','QUEUED','RUNNING','COMPLETED','PARTIAL','FAILED')),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index if not exists idx_research_queries_user on research_queries(user_id);

create table if not exists research_jobs (
    id                  uuid primary key default uuid_generate_v4(),
    research_query_id   uuid not null references research_queries(id) on delete cascade,
    status              text not null default 'QUEUED'
                            check (status in ('QUEUED','RUNNING','COMPLETED','PARTIAL','FAILED')),
    started_at          timestamptz,
    completed_at        timestamptz,
    failure_summary     text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists idx_research_jobs_query on research_jobs(research_query_id);

-- ============================================================
-- AGENT EXECUTION LOG
-- ============================================================

create table if not exists agent_runs (
    id              uuid primary key default uuid_generate_v4(),
    research_job_id uuid not null references research_jobs(id) on delete cascade,
    agent_name      text not null,
    status          text not null default 'pending'
                        check (status in ('pending','running','completed','failed')),
    input           jsonb,
    output          jsonb,
    error           text,
    retry_count     integer not null default 0,
    started_at      timestamptz,
    completed_at    timestamptz,
    created_at      timestamptz not null default now()
);
create index if not exists idx_agent_runs_job on agent_runs(research_job_id);

-- ============================================================
-- SOURCES + STUDIES
-- ============================================================

create table if not exists sources (
    id                  uuid primary key default uuid_generate_v4(),
    research_job_id     uuid not null references research_jobs(id) on delete cascade,
    source_type         text not null
                            check (source_type in (
                                'PRIMARY_STUDY','SYSTEMATIC_REVIEW','META_ANALYSIS',
                                'CLINICAL_TRIAL','GUIDELINE','OFFICIAL_MEDICAL_SOURCE',
                                'SECONDARY_SOURCE','GENERAL_WEB','UNKNOWN'
                            )),
    origin              text not null check (origin in ('pubmed','clinicaltrials','tavily')),
    external_id         text,              -- PMID / NCT ID / URL hash
    title               text not null,
    url                 text,
    publisher           text,
    published_date      date,
    retrieved_at        timestamptz not null default now(),
    raw_metadata        jsonb,
    created_at          timestamptz not null default now()
);
create index if not exists idx_sources_job on sources(research_job_id);
-- Scoped per job, not globally: the same PMID/NCT ID legitimately recurs
-- across different users' (or repeated) research jobs. What must not
-- happen is the *same job* inserting the same external source twice.
create unique index if not exists uq_sources_job_origin_external
    on sources(research_job_id, origin, external_id) where external_id is not null;

create table if not exists studies (
    id              uuid primary key default uuid_generate_v4(),
    source_id       uuid not null references sources(id) on delete cascade,
    study_type      text,
    population      text,
    sample_size     integer,
    intervention    text,
    comparator      text,
    outcomes        jsonb,
    follow_up       text,
    methodology     text,
    findings        text,
    effect_size     text,
    limitations     text,
    conclusion      text,
    relevance_score numeric,
    created_at      timestamptz not null default now()
);
create index if not exists idx_studies_source on studies(source_id);

create table if not exists study_findings (
    id              uuid primary key default uuid_generate_v4(),
    study_id        uuid not null references studies(id) on delete cascade,
    outcome         text not null,
    effect_direction text check (effect_direction in ('BENEFIT','HARM','NO_EFFECT','UNCLEAR')),
    effect_size     text,
    confidence      text check (confidence in ('HIGH','MODERATE','LOW')),
    created_at      timestamptz not null default now()
);
create index if not exists idx_study_findings_study on study_findings(study_id);

-- ============================================================
-- EVIDENCE VERIFICATION + CONFLICTS
-- ============================================================

create table if not exists evidence_claims (
    id                  uuid primary key default uuid_generate_v4(),
    research_job_id     uuid not null references research_jobs(id) on delete cascade,
    claim_text          text not null,
    verification_status text not null
                            check (verification_status in
                                ('SUPPORTED','PARTIALLY_SUPPORTED','NOT_SUPPORTED','CONFLICTING')),
    confidence          numeric,
    created_at          timestamptz not null default now()
);
create index if not exists idx_evidence_claims_job on evidence_claims(research_job_id);

create table if not exists evidence_links (
    id                  uuid primary key default uuid_generate_v4(),
    evidence_claim_id   uuid not null references evidence_claims(id) on delete cascade,
    study_id            uuid references studies(id) on delete set null,
    source_id           uuid references sources(id) on delete set null,
    excerpt             text,
    created_at          timestamptz not null default now()
);
create index if not exists idx_evidence_links_claim on evidence_links(evidence_claim_id);

create table if not exists conflicts (
    id                  uuid primary key default uuid_generate_v4(),
    research_job_id     uuid not null references research_jobs(id) on delete cascade,
    study_a_id          uuid not null references studies(id) on delete cascade,
    study_b_id          uuid not null references studies(id) on delete cascade,
    conflicting_outcome text not null,
    finding_a           text not null,
    finding_b           text not null,
    possible_explanation text,
    confidence          numeric,
    created_at          timestamptz not null default now()
);
create index if not exists idx_conflicts_job on conflicts(research_job_id);

-- ============================================================
-- RAG: DOCUMENTS + CHUNKS
-- ============================================================

create table if not exists documents (
    id          uuid primary key default uuid_generate_v4(),
    study_id    uuid not null references studies(id) on delete cascade,
    content     text not null,
    created_at  timestamptz not null default now()
);
create index if not exists idx_documents_study on documents(study_id);

create table if not exists document_chunks (
    id          uuid primary key default uuid_generate_v4(),
    document_id uuid not null references documents(id) on delete cascade,
    study_id    uuid not null references studies(id) on delete cascade, -- denormalized for scoped RAG queries
    chunk_index integer not null,
    content     text not null,
    embedding   vector(1536),
    created_at  timestamptz not null default now()
);
create index if not exists idx_document_chunks_study on document_chunks(study_id);
-- ivfflat index for cosine similarity search; requires ANALYZE after bulk insert
create index if not exists idx_document_chunks_embedding
    on document_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ============================================================
-- REPORTS + SAVED ITEMS
-- ============================================================

create table if not exists research_reports (
    id              uuid primary key default uuid_generate_v4(),
    research_job_id uuid not null references research_jobs(id) on delete cascade,
    sections        jsonb not null,   -- { executive_summary, methodology, key_findings, ... }
    citations       jsonb not null,   -- ordered list mapping [n] -> source/study id
    evidence_grade  text check (evidence_grade in ('STRONG','MODERATE','LIMITED','INSUFFICIENT')),
    created_at      timestamptz not null default now()
);
create index if not exists idx_reports_job on research_reports(research_job_id);

create table if not exists saved_studies (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    study_id    uuid not null references studies(id) on delete cascade,
    created_at  timestamptz not null default now(),
    unique(user_id, study_id)
);

create table if not exists saved_reports (
    id          uuid primary key default uuid_generate_v4(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    report_id   uuid not null references research_reports(id) on delete cascade,
    created_at  timestamptz not null default now(),
    unique(user_id, report_id)
);

-- ============================================================
-- Row Level Security
-- ============================================================

alter table research_queries enable row level security;
alter table saved_studies enable row level security;
alter table saved_reports enable row level security;

create policy "own research queries" on research_queries
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "own saved studies" on saved_studies
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "own saved reports" on saved_reports
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Note: research_jobs/sources/studies/etc. are accessed via the backend
-- service role (RLS bypassed there) and scoped in application code by
-- joining through research_queries.user_id — the backend never trusts a
-- client-supplied user_id.
