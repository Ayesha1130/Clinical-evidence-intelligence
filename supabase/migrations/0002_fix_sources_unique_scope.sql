-- Fixes a Phase 1 bug: the original uq_sources_origin_external index was
-- unique across the ENTIRE sources table, meaning the same PMID/NCT ID
-- could only ever be stored once system-wide. That breaks as soon as two
-- research jobs (different users, or the same user re-running a query)
-- retrieve the same source. Uniqueness should be scoped per research_job_id.
--
-- Safe to run whether or not 0001_init.sql already created the old index.

drop index if exists uq_sources_origin_external;

create unique index if not exists uq_sources_job_origin_external
    on sources(research_job_id, origin, external_id) where external_id is not null;
