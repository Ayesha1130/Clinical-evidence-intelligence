# Remaining Work & Future Roadmap: Clinical Evidence Intelligence

This document outlines items requiring external configuration, non-code administrative steps, and recommended feature enhancements for future iterations.

---

## 1. Credentials & External Services Setup (User Action Required)

The following items cannot be executed autonomously because they require credentials or third-party dashboard access:

1. **Supabase Database & Auth Configuration:**
   - Run the SQL migrations (`supabase/migrations/0001_init.sql` through `0004_rag_document_metadata.sql`) in your Supabase project's SQL editor.
   - Configure `SUPABASE_JWT_SECRET` in your backend `.env` (obtained from Supabase Project Settings -> API -> JWT Secret) to enable server-side signature validation.
   - Set the actual `DATABASE_URL` (direct or pooled transaction connection string) in `backend/.env`.

2. **OpenAI API Key:**
   - Ensure an active OpenAI API key with access to `gpt-4.1` and `text-embedding-3-small` is configured in `OPENAI_API_KEY`.
   - Rotate any API keys that were previously committed to version control before the `.gitignore` was added.

3. **NCBI E-Utilities Credentials:**
   - Set `NCBI_EMAIL` to your valid contact email in `backend/.env` (mandated by NCBI E-utilities fair usage policy).
   - Optionally register for an `NCBI_API_KEY` to increase the request limit from 3 req/s to 10 req/s.

4. **Tavily API Key:**
   - Configure `TAVILY_API_KEY` in `backend/.env` to enable wide-web medical literature and systematic review searches.

---

## 2. Recommended Production Enhancements

The following tasks are optional future feature improvements:

1. **Persistent Distributed Cache for Rate Limiting & SSE:**
   - Currently, the event bus and rate limiter operate in-process (ideal for single-container Render/Railway deployments). If scaling horizontally to multi-container clusters, transition the event bus to Redis Pub/Sub or Supabase Realtime, and rate limiting to Redis sliding window.

2. **Full-Text PDF Extraction Integration:**
   - The current ingestion pipeline primarily parses abstracts and structured clinical trial registry sections (flagged cleanly as `ABSTRACT` or `TRIAL_SUMMARY` in `documents.document_type`). Adding an open-access PMC full-text PDF parser would allow ingestion of entire 20-page papers when open-access PMCID is available.

3. **User Research History Dashboard:**
   - The backend already exposes `GET /api/research` with pagination. A dedicated frontend `/dashboard` or `/history` page could be added to allow clinicians to revisit and search through all past research queries and bookmarked studies (`SavedStudy`, `SavedReport`).

4. **Export Capabilities:**
   - Add a "Download PDF / Markdown" button on `ResearchReport.tsx` to generate an exportable clinical evidence brief with footnotes and citations.
