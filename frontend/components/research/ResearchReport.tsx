"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { GRADE_LABEL, ReportOut } from "@/types/report";

interface ResearchReportProps {
  researchQueryId: string;
}

function withCitationLinks(text: string) {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (!match) return <span key={i}>{part}</span>;
    return (
      <a key={i} href={`#citation-${match[1]}`} className="text-terracotta no-underline hover:underline">
        {part}
      </a>
    );
  });
}

export function ResearchReport({ researchQueryId }: ResearchReportProps) {
  const [report, setReport] = useState<ReportOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get<ReportOut>(`/api/research/${researchQueryId}/report`)
      .then((r) => !cancelled && setReport(r))
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof ApiError && err.status === 404
            ? "No report has been generated for this research yet."
            : "Could not load the report."
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [researchQueryId]);

  if (loading) {
    return <p className="text-sm text-charcoal/60">Loading report&hellip;</p>;
  }
  if (error) {
    return <p className="text-sm text-charcoal/60">{error}</p>;
  }
  if (!report) return null;

  const { sections } = report;

  return (
    <article className="border border-charcoal/15 bg-white/60 px-5 py-8 sm:px-8 sm:py-10">
      <p className="text-xs uppercase tracking-widest text-terracotta">Research report</p>
      <h1 className="mt-2 font-serif text-3xl leading-snug text-burgundy">{sections.research_question}</h1>

      <div className="mt-4 inline-block border border-gold px-3 py-1 text-sm text-gold">
        {GRADE_LABEL[sections.evidence_strength] ?? sections.evidence_strength}
      </div>

      <Section title="Executive summary">{withCitationLinks(sections.executive_summary)}</Section>
      <Section title="Search methodology">{sections.search_methodology}</Section>
      <Section title="Key findings">{withCitationLinks(sections.key_findings)}</Section>

      <Section title="Studies analyzed">
        <ul className="divide-y divide-charcoal/10 border-y border-charcoal/10">
          {sections.studies_analyzed.map((s) => (
            <li key={s.id} className="py-3">
              <p className="font-serif text-base text-charcoal">{s.title}</p>
              <p className="mt-1 text-xs text-charcoal/60">
                {s.origin} &middot; {s.study_type ?? s.source_type}
                {s.relevance_score !== null && ` \u00b7 relevance ${(s.relevance_score * 100).toFixed(0)}%`}
              </p>
              {s.conclusion && <p className="mt-1 text-sm text-charcoal/80">{s.conclusion}</p>}
            </li>
          ))}
          {sections.studies_analyzed.length === 0 && (
            <li className="py-3 text-sm text-charcoal/60">No studies were analyzed for this research.</li>
          )}
        </ul>
      </Section>

      {sections.conflicting_evidence.length > 0 && (
        <Section title="Conflicting evidence">
          <ul className="space-y-3">
            {sections.conflicting_evidence.map((c, i) => (
              <li key={i} className="border-l-2 border-terracotta pl-4">
                <p className="text-sm text-charcoal">
                  On <span className="italic">{c.outcome}</span>: {c.finding_a} vs {c.finding_b}
                </p>
                <p className="mt-1 text-xs text-charcoal/60">{c.explanation}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Evidence gaps">{sections.evidence_gaps}</Section>
      <Section title="Limitations">{sections.limitations}</Section>
      <Section title="Conclusion">{sections.conclusion}</Section>

      <Section title="Sources">
        <ol className="space-y-2">
          {report.citations.map((c) => (
            <li key={c.number} id={`citation-${c.number}`} className="text-sm text-charcoal/80">
              <span className="text-terracotta">[{c.number}]</span> {c.claim_text}{" "}
              <span className="text-charcoal/50">&mdash; {c.study_title}</span>
              {c.source_url && (
                <a href={c.source_url} target="_blank" rel="noreferrer" className="ml-1 text-sage underline">
                  view source
                </a>
              )}
            </li>
          ))}
          {report.citations.length === 0 && (
            <li className="text-sm text-charcoal/60">No verified claims were available to cite.</li>
          )}
        </ol>
      </Section>

      <p className="mt-10 text-xs text-charcoal/50">
        This report provides AI-assisted evidence research for informational purposes. It does not
        diagnose conditions, prescribe treatment, or replace professional medical judgment. Evidence
        strength shown here is an AI-assisted assessment, not an official clinical guideline grading
        framework.
      </p>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="font-serif text-xl text-burgundy">{title}</h2>
      <div className="mt-2 text-sm leading-relaxed text-charcoal/85">{children}</div>
    </section>
  );
}
