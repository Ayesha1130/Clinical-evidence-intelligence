"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api/client";

interface ResearchQueryResponse {
  id: string;
  raw_question: string;
  status: string;
}

function NewResearchForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";

  const [question, setQuestion] = useState(initialQuery);
  const [population, setPopulation] = useState("");
  const [intervention, setIntervention] = useState("");
  const [comparator, setComparator] = useState("");
  const [outcomes, setOutcomes] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([
    "pubmed",
    "clinical_trials",
    "tavily",
  ]);
  const [showPico, setShowPico] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialQuery && !question) {
      setQuestion(initialQuery);
    }
  }, [initialQuery, question]);

  const toggleSource = (source: string) => {
    setSelectedSources((prev) =>
      prev.includes(source)
        ? prev.filter((s) => s !== source)
        : [...prev, source]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) {
      setError("Please enter a research question.");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const outcomeList = outcomes
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

      // 1. Create the query draft
      const query = await api.post<ResearchQueryResponse>("/api/research", {
        raw_question: question.trim(),
        population: population.trim() || null,
        intervention: intervention.trim() || null,
        comparator: comparator.trim() || null,
        outcomes: outcomeList,
        study_types: [],
        date_range: null,
        sources: selectedSources,
      });

      // 2. Start the pipeline
      await api.post(`/api/research/${query.id}/start`);

      // 3. Navigate to the live investigation screen
      router.push(`/research/${query.id}`);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        setError("You must be logged in to conduct research. Please log in first.");
      } else if (err instanceof Error) {
        setError(err.message || "Failed to initiate research pipeline.");
      } else {
        setError("An unexpected error occurred. Please try again.");
      }
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6 flex items-center justify-between">
        <Link
          href="/"
          className="text-xs uppercase tracking-widest text-charcoal/60 hover:text-burgundy"
        >
          &larr; Back to Overview
        </Link>
        <span className="text-xs text-charcoal/50">Step 1 of 2: Configure Inquiry</span>
      </div>

      <div className="border border-charcoal/15 bg-white/70 p-6 sm:p-8 shadow-sm">
        <h1 className="font-serif text-2xl text-burgundy sm:text-3xl">
          Initiate Evidence Investigation
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-charcoal/70">
          Formulate your clinical or scientific question. Our multi-agent intelligence
          will retrieve primary literature, analyze study designs, verify claims against
          ground truth excerpts, and detect conflicting findings.
        </p>

        {error && (
          <div
            className="mt-6 border-l-4 border-terracotta bg-terracotta/10 p-4 text-sm text-charcoal"
            role="alert"
          >
            <p className="font-medium text-terracotta">Notice</p>
            <p className="mt-1">{error}</p>
            {error.includes("log in") && (
              <Link
                href="/login"
                className="mt-2 inline-block font-medium text-burgundy underline hover:text-terracotta"
              >
                Go to Login &rarr;
              </Link>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-6 space-y-6">
          <div>
            <label
              htmlFor="research-question-input"
              className="block font-serif text-base text-charcoal"
            >
              Primary Research Question <span className="text-terracotta">*</span>
            </label>
            <textarea
              id="research-question-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. Does semaglutide reduce all-cause mortality in non-diabetic obesity?"
              rows={3}
              required
              className="mt-2 w-full border border-charcoal/20 bg-ivory/50 p-3 font-serif text-base text-charcoal placeholder:text-charcoal/40 focus:border-terracotta focus:outline-none"
            />
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowPico(!showPico)}
              className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-charcoal/70 hover:text-burgundy"
            >
              <span>{showPico ? "\u25be" : "\u25b8"}</span>
              <span>Advanced PICO Framing (Optional)</span>
            </button>

            {showPico && (
              <div className="mt-4 space-y-4 border border-charcoal/10 bg-ivory/30 p-4 text-sm">
                <p className="text-xs text-charcoal/60">
                  You can specify constraints directly, or let our Query Analyzer agent infer them from your question.
                </p>
                <div>
                  <label htmlFor="pico-population" className="block text-xs font-medium text-charcoal/70">
                    Population (P)
                  </label>
                  <input
                    id="pico-population"
                    type="text"
                    value={population}
                    onChange={(e) => setPopulation(e.target.value)}
                    placeholder="e.g. Adults \u2265 18 with BMI \u2265 30"
                    className="mt-1 w-full border border-charcoal/20 bg-white/80 p-2 text-sm text-charcoal focus:border-terracotta focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="pico-intervention" className="block text-xs font-medium text-charcoal/70">
                    Intervention (I)
                  </label>
                  <input
                    id="pico-intervention"
                    type="text"
                    value={intervention}
                    onChange={(e) => setIntervention(e.target.value)}
                    placeholder="e.g. Semaglutide 2.4 mg subcutaneous weekly"
                    className="mt-1 w-full border border-charcoal/20 bg-white/80 p-2 text-sm text-charcoal focus:border-terracotta focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="pico-comparator" className="block text-xs font-medium text-charcoal/70">
                    Comparator (C)
                  </label>
                  <input
                    id="pico-comparator"
                    type="text"
                    value={comparator}
                    onChange={(e) => setComparator(e.target.value)}
                    placeholder="e.g. Placebo or standard lifestyle counseling"
                    className="mt-1 w-full border border-charcoal/20 bg-white/80 p-2 text-sm text-charcoal focus:border-terracotta focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="pico-outcomes" className="block text-xs font-medium text-charcoal/70">
                    Target Outcomes (O) (comma separated)
                  </label>
                  <input
                    id="pico-outcomes"
                    type="text"
                    value={outcomes}
                    onChange={(e) => setOutcomes(e.target.value)}
                    placeholder="e.g. All-cause mortality, major cardiovascular events, weight loss percentage"
                    className="mt-1 w-full border border-charcoal/20 bg-white/80 p-2 text-sm text-charcoal focus:border-terracotta focus:outline-none"
                  />
                </div>
              </div>
            )}
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-charcoal/70">
              Evidence Sources to Query
            </label>
            <div className="mt-3 flex flex-wrap gap-4 text-sm">
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={selectedSources.includes("pubmed")}
                  onChange={() => toggleSource("pubmed")}
                  className="accent-burgundy"
                />
                <span>PubMed (NCBI)</span>
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={selectedSources.includes("clinical_trials")}
                  onChange={() => toggleSource("clinical_trials")}
                  className="accent-burgundy"
                />
                <span>ClinicalTrials.gov (API v2)</span>
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={selectedSources.includes("tavily")}
                  onChange={() => toggleSource("tavily")}
                  className="accent-burgundy"
                />
                <span>Web Research (Tavily)</span>
              </label>
            </div>
          </div>

          <div className="pt-4">
            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-burgundy px-6 py-3.5 font-medium text-ivory transition-colors hover:bg-terracotta disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? "Dispatching Research Pipeline..." : "Begin Investigation"}
            </button>
            <p className="mt-2 text-center text-xs text-charcoal/50">
              Pipeline runs autonomously with live real-time progress via Server-Sent Events.
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function NewResearchPage() {
  return (
    <main className="min-h-screen bg-ivory px-4 py-8 sm:px-6 sm:py-12">
      <Suspense fallback={<div className="text-center text-sm text-charcoal/60">Loading research form...</div>}>
        <NewResearchForm />
      </Suspense>
    </main>
  );
}
