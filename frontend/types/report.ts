export interface CitationEntry {
  number: number;
  claim_text: string;
  verification_status: string;
  confidence: number | null;
  excerpt: string | null;
  study_id: string | null;
  study_title: string;
  source_url: string | null;
  origin: string | null;
}

export interface StudySummary {
  id: string;
  title: string;
  origin: string;
  source_type: string;
  study_type: string | null;
  conclusion: string | null;
  relevance_score: number | null;
}

export interface ConflictSummary {
  outcome: string;
  finding_a: string;
  finding_b: string;
  explanation: string | null;
  confidence: number | null;
}

export interface ReportSections {
  research_question: string;
  executive_summary: string;
  search_methodology: string;
  evidence_strength: string;
  key_findings: string;
  studies_analyzed: StudySummary[];
  high_quality_evidence: StudySummary[];
  conflicting_evidence: ConflictSummary[];
  evidence_gaps: string;
  limitations: string;
  conclusion: string;
  sources: Array<{
    id: string;
    title: string;
    origin: string;
    url: string | null;
    external_id: string | null;
    publisher: string | null;
  }>;
}

export interface ReportOut {
  id: string;
  research_job_id: string;
  sections: ReportSections;
  citations: CitationEntry[];
  evidence_grade: string | null;
  created_at: string;
}

export interface EvidenceMapNode {
  id: string;
  type: "question" | "study";
  label: string;
  study_type?: string | null;
  origin?: string | null;
  year?: number | null;
  effect_direction?: "BENEFIT" | "HARM" | "NO_EFFECT" | "UNCLEAR" | null;
  relevance_score?: number | null;
  has_conflict?: boolean;
}

export interface EvidenceMapEdge {
  source: string;
  target: string;
  type: "informs" | "conflict";
  outcome?: string;
  explanation?: string | null;
}

export interface EvidenceMapOut {
  nodes: EvidenceMapNode[];
  edges: EvidenceMapEdge[];
}

export const GRADE_LABEL: Record<string, string> = {
  STRONG: "Strong evidence",
  MODERATE: "Moderate evidence",
  LIMITED: "Limited evidence",
  INSUFFICIENT: "Insufficient evidence",
};
