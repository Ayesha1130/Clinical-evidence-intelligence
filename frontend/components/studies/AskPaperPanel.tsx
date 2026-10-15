"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { AskResponse, DOCUMENT_TYPE_LABEL, DocumentType } from "@/types/rag";

interface AskPaperPanelProps {
  studyId: string;
  studyTitle: string;
  documentType?: DocumentType | null;
}

export function AskPaperPanel({ studyId, studyTitle, documentType }: AskPaperPanelProps) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AskResponse | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const result = await api.post<AskResponse>(`/api/studies/${studyId}/ask`, { question });
      setResponse(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="border border-charcoal/15 bg-white/60">
      <div className="border-b border-charcoal/10 px-6 py-4">
        <p className="text-xs uppercase tracking-widest text-terracotta">Ask this paper</p>
        <p className="mt-1 font-serif text-lg text-burgundy line-clamp-1">{studyTitle}</p>
        {documentType && (
          <p className="mt-1 text-xs text-charcoal/60">{DOCUMENT_TYPE_LABEL[documentType]}</p>
        )}
      </div>

      <form onSubmit={handleSubmit} className="px-6 py-5">
        <label htmlFor="ask-paper-question" className="block text-sm text-charcoal/70">
          What do you want to know about this paper?
        </label>
        <div className="mt-2 flex flex-col gap-3 sm:flex-row">
          <input
            id="ask-paper-question"
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="What was the primary outcome?"
            className="flex-1 border-b border-charcoal/20 bg-transparent py-2 font-serif text-base text-charcoal outline-none placeholder:text-charcoal/40 focus:border-terracotta"
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="w-full shrink-0 bg-burgundy px-5 py-2 text-sm font-medium text-ivory transition-colors hover:bg-terracotta disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
          >
            {loading ? "Asking\u2026" : "Ask"}
          </button>
        </div>
      </form>

      {error && (
        <div className="border-t border-charcoal/10 px-6 py-4 text-sm text-terracotta">{error}</div>
      )}

      {response && (
        <div className="border-t border-charcoal/10 px-6 py-5">
          <div className="flex items-center justify-between">
            <p className="text-xs uppercase tracking-widest text-charcoal/50">Answer</p>
            <GroundedBadge grounded={response.grounded} />
          </div>
          <p className="mt-2 font-serif text-base leading-relaxed text-charcoal">{response.answer}</p>

          {response.citations.length > 0 && (
            <div className="mt-5 border-l-2 border-gold pl-4">
              <p className="text-xs uppercase tracking-widest text-charcoal/50">Evidence</p>
              {response.citations.map((c) => (
                <blockquote key={c.chunk_id} className="mt-2">
                  <p className="font-serif text-sm italic leading-relaxed text-charcoal/80">
                    &ldquo;{c.excerpt}&rdquo;
                  </p>
                  <p className="mt-1 text-xs text-charcoal/50">
                    Similarity {(c.similarity * 100).toFixed(0)}%
                  </p>
                </blockquote>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function GroundedBadge({ grounded }: { grounded: boolean }) {
  if (grounded) {
    return (
      <span className="border border-sage px-2 py-0.5 text-xs text-sage">Grounded in this paper</span>
    );
  }
  return (
    <span className="border border-charcoal/20 px-2 py-0.5 text-xs text-charcoal/50">
      Not found in this paper
    </span>
  );
}
