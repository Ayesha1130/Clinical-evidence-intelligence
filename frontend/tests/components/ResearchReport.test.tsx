import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ResearchReport } from "@/components/research/ResearchReport";
import { api, ApiError } from "@/lib/api/client";

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

const SAMPLE_REPORT = {
  id: "r1",
  research_job_id: "j1",
  evidence_grade: "MODERATE",
  created_at: "2026-01-01T00:00:00Z",
  citations: [
    {
      number: 1,
      claim_text: "Metformin reduced cardiovascular events.",
      verification_status: "SUPPORTED",
      confidence: 0.9,
      excerpt: "reduced cardiovascular events",
      study_id: "s1",
      study_title: "Metformin RCT",
      source_url: "https://pubmed.ncbi.nlm.nih.gov/123/",
      origin: "pubmed",
    },
  ],
  sections: {
    research_question: "Does metformin reduce cardiovascular risk?",
    executive_summary: "Evidence suggests a benefit [1].",
    search_methodology: "Searched PubMed and ClinicalTrials.gov.",
    evidence_strength: "MODERATE",
    key_findings: "Metformin reduced cardiovascular events [1].",
    studies_analyzed: [
      {
        id: "s1",
        title: "Metformin RCT",
        origin: "pubmed",
        source_type: "PRIMARY_STUDY",
        study_type: "randomized controlled trial",
        conclusion: "Supports a benefit.",
        relevance_score: 0.9,
      },
    ],
    high_quality_evidence: [],
    conflicting_evidence: [],
    evidence_gaps: "Long-term data was not available.",
    limitations: "Abstract-level evidence only.",
    conclusion: "Evidence points toward benefit.",
    sources: [],
  },
};

describe("ResearchReport", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("shows a loading state before the report arrives", () => {
    vi.mocked(api.get).mockReturnValue(new Promise(() => {}));
    render(<ResearchReport researchQueryId="q1" />);
    expect(screen.getByText(/loading report/i)).toBeInTheDocument();
  });

  it("renders all major sections once loaded", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(SAMPLE_REPORT);
    render(<ResearchReport researchQueryId="q1" />);

    await waitFor(() => {
      expect(screen.getByText("Does metformin reduce cardiovascular risk?")).toBeInTheDocument();
    });
    expect(screen.getByText("Moderate evidence")).toBeInTheDocument();
    expect(screen.getByText("Metformin RCT")).toBeInTheDocument();
    expect(screen.getByText("Supports a benefit.")).toBeInTheDocument();
    expect(screen.getByText(/Metformin reduced cardiovascular events\./)).toBeInTheDocument();
  });

  it("renders numbered citations as clickable anchors", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(SAMPLE_REPORT);
    render(<ResearchReport researchQueryId="q1" />);

    await waitFor(() => screen.getByText("Does metformin reduce cardiovascular risk?"));
    const citationLinks = screen.getAllByRole("link", { name: "[1]" });
    expect(citationLinks.length).toBeGreaterThan(0);
    expect(citationLinks[0]).toHaveAttribute("href", "#citation-1");
  });

  it("shows a friendly message when no report exists yet", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(404, "not found"));
    render(<ResearchReport researchQueryId="q1" />);

    await waitFor(() => {
      expect(screen.getByText(/no report has been generated/i)).toBeInTheDocument();
    });
  });

  it("shows a generic error message on non-404 failures", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(500, "server error"));
    render(<ResearchReport researchQueryId="q1" />);

    await waitFor(() => {
      expect(screen.getByText(/could not load the report/i)).toBeInTheDocument();
    });
  });
});
