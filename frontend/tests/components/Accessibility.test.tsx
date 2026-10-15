import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { axe } from "jest-axe";
import { AskPaperPanel } from "@/components/studies/AskPaperPanel";
import { ResearchReport } from "@/components/research/ResearchReport";
import { EvidenceMap } from "@/components/research/EvidenceMap";
import LandingPage from "@/app/page";
import { api } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

describe("Accessibility (axe-core)", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    vi.mocked(api.post).mockReset();
  });

  it("landing page has no detectable accessibility violations", async () => {
    const { container } = render(<LandingPage />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("AskPaperPanel has no detectable accessibility violations", async () => {
    const { container } = render(
      <AskPaperPanel studyId="s1" studyTitle="Metformin RCT" documentType="ABSTRACT" />
    );
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("AskPaperPanel with a rendered answer has no violations", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      answer: "The study enrolled 250 participants.",
      grounded: true,
      document_type: "ABSTRACT",
      citations: [{ document_id: "d1", chunk_id: "c1", excerpt: "enrolled 250 participants", similarity: 0.87 }],
    });
    const { container } = render(<AskPaperPanel studyId="s1" studyTitle="Metformin RCT" />);
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("ResearchReport has no detectable accessibility violations once loaded", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      id: "r1",
      research_job_id: "j1",
      evidence_grade: "MODERATE",
      created_at: "2026-01-01T00:00:00Z",
      citations: [],
      sections: {
        research_question: "Does metformin help?",
        executive_summary: "Some summary.",
        search_methodology: "Searched PubMed.",
        evidence_strength: "MODERATE",
        key_findings: "Some findings.",
        studies_analyzed: [],
        high_quality_evidence: [],
        conflicting_evidence: [],
        evidence_gaps: "Some gaps.",
        limitations: "Some limitations.",
        conclusion: "Some conclusion.",
        sources: [],
      },
    });
    const { container } = render(<ResearchReport researchQueryId="q1" />);
    await waitFor(() => container.querySelector("h1"));
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("EvidenceMap has no detectable accessibility violations", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      nodes: [
        { id: "research_question", type: "question", label: "Does metformin help?" },
        { id: "s1", type: "study", label: "Benefit Study", effect_direction: "BENEFIT", has_conflict: false },
      ],
      edges: [{ source: "research_question", target: "s1", type: "informs" }],
    });
    const { container } = render(<EvidenceMap researchQueryId="q1" />);
    await waitFor(() => container.querySelector("button"));
    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});
