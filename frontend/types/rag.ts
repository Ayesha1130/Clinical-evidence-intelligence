export type DocumentType = "ABSTRACT" | "TRIAL_SUMMARY" | "WEB_CONTENT" | "FULL_TEXT";

export interface Citation {
  document_id: string;
  chunk_id: string;
  excerpt: string;
  similarity: number;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  grounded: boolean;
  document_type: DocumentType | null;
}

export const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  ABSTRACT: "Abstract-level evidence",
  TRIAL_SUMMARY: "Trial registry summary",
  WEB_CONTENT: "Web content",
  FULL_TEXT: "Full text",
};
