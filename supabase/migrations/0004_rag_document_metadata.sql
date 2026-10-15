-- Phase 6 (RAG). The vector column added in 0001_init.sql is already
-- `vector(1536)`, which matches OpenAI's text-embedding-3-small (1536
-- dimensions) — the embedding model this build uses. No dimension change
-- is required; this is confirmed, not assumed (see README "Embedding
-- model" section).
--
-- What IS genuinely needed:
-- 1. documents.document_type — so the system (and the UI) always knows
--    whether it's looking at an abstract, a trial registry summary, web
--    content, or (if ever available in the future) full text. Never
--    implicitly treated as a full paper.
-- 2. document_chunks.char_count — chunk-size metadata, useful for
--    diagnosing chunking behavior and avoiding meaninglessly tiny chunks.
-- 3. A uniqueness constraint on (document_id, chunk_index) — indexing the
--    same document twice must not create duplicate chunk rows.

alter table documents
    add column if not exists document_type text
        check (document_type in ('ABSTRACT', 'TRIAL_SUMMARY', 'WEB_CONTENT', 'FULL_TEXT'));

alter table document_chunks
    add column if not exists char_count integer;

create unique index if not exists uq_document_chunks_document_chunk_index
    on document_chunks(document_id, chunk_index);
