# Production Deployment Checklist: Clinical Evidence Intelligence

This checklist provides step-by-step guidance for deploying the Clinical Evidence Intelligence platform to production (Backend on Render/Railway/Fly.io, Frontend on Vercel, Database on Supabase).

---

## 1. Pre-Deployment Configuration

- [ ] **Rotate Exposed Secrets:**
  - Rotate OpenAI API keys, Supabase service keys, and Tavily API keys to invalidate any credentials previously stored in uncommitted development files.
- [ ] **Verify `.gitignore`:**
  - Ensure `.env` and `.env.local` files are ignored and never pushed to remote repositories.
- [ ] **Review CORS Origins:**
  - In `backend/.env` / Render environment variables, set `CORS_ALLOWED_ORIGINS` to the production frontend URL (e.g., `https://clinical-evidence.vercel.app`).

---

## 2. Supabase Database Setup

- [ ] **Create Supabase Project:**
  - Provision a PostgreSQL project on [supabase.com](https://supabase.com).
- [ ] **Execute Migrations in Order:**
  - `supabase/migrations/0001_init.sql` (Creates extensions `uuid-ossp`, `vector`, core tables, indexes)
  - `supabase/migrations/0002_fix_sources_unique_scope.sql` (Scopes source uniqueness per job)
  - `supabase/migrations/0003_add_evidence_grade_to_research_jobs.sql` (Adds `evidence_grade` column)
  - `supabase/migrations/0004_rag_document_metadata.sql` (Adds `document_type`, `char_count`, chunk index)
- [ ] **Verify Extensions:**
  - Ensure `vector` extension is enabled (`SELECT * FROM pg_extension WHERE extname = 'vector';`).
- [ ] **Obtain Connection String & JWT Secret:**
  - Copy transaction pooler connection string (`postgresql+asyncpg://...:6543/postgres`).
  - Copy JWT Secret from Project Settings -> API -> JWT Settings.

---

## 3. Backend Deployment (e.g. Render Docker Service)

- [ ] **Deploy via Blueprint or Docker Service:**
  - Use `render.yaml` or create a new Web Service using `backend/Dockerfile`.
- [ ] **Configure Environment Variables:**
  ```env
  ENVIRONMENT=production
  DATABASE_URL=postgresql+asyncpg://postgres:[PASSWORD]@[HOST]:5432/postgres
  SUPABASE_URL=https://[PROJECT-REF].supabase.co
  SUPABASE_SERVICE_KEY=[SUPABASE-SERVICE-ROLE-KEY]
  SUPABASE_JWT_SECRET=[SUPABASE-JWT-SECRET]
  LLM_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  OPENAI_MODEL=gpt-4.1
  OPENAI_EMBEDDING_MODEL=text-embedding-3-small
  TAVILY_API_KEY=tvly-...
  NCBI_EMAIL=admin@yourinstitution.org
  NCBI_API_KEY=[OPTIONAL]
  CORS_ALLOWED_ORIGINS=https://[YOUR-FRONTEND-DOMAIN]
  ```
- [ ] **Verify Health Check:**
  - Request `GET https://[BACKEND-URL]/health` -> Should return `{"status": "ok"}` with HTTP 200.

---

## 4. Frontend Deployment (e.g. Vercel)

- [ ] **Connect Repository:**
  - Import the repository on Vercel, set Root Directory to `frontend`.
- [ ] **Configure Environment Variables:**
  ```env
  NEXT_PUBLIC_API_URL=https://[YOUR-BACKEND-URL]
  NEXT_PUBLIC_SUPABASE_URL=https://[PROJECT-REF].supabase.co
  NEXT_PUBLIC_SUPABASE_ANON_KEY=[SUPABASE-ANON-PUBLISHABLE-KEY]
  ```
- [ ] **Verify Build:**
  - Build command: `npm run build`
  - Output directory: `.next`
- [ ] **Smoke Test End-to-End Flow:**
  - Open production URL -> Verify landing page renders without errors.
  - Visit `/login` -> Verify Supabase auth flow.
  - Submit research question -> Verify transition to `/research/[id]`.
  - Check real-time SSE progress stream.
  - Confirm Evidence Map, GRADE badge, and citation report load.
  - Test "Ask This Paper" Q&A on a study.
