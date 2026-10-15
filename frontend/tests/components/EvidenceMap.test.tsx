import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EvidenceMap } from "@/components/research/EvidenceMap";
import { api } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

describe("EvidenceMap", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("shows an empty state when there are no studies", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      nodes: [{ id: "research_question", type: "question", label: "Does X help?" }],
      edges: [],
    });
    render(<EvidenceMap researchQueryId="q1" />);

    await waitFor(() => {
      expect(screen.getByText("No studies to map yet.")).toBeInTheDocument();
    });
  });

  it("renders the question and each study with its effect direction label", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      nodes: [
        { id: "research_question", type: "question", label: "Does metformin help?" },
        { id: "s1", type: "study", label: "Benefit Study", effect_direction: "BENEFIT", has_conflict: false },
        { id: "s2", type: "study", label: "Harm Study", effect_direction: "HARM", has_conflict: true },
      ],
      edges: [
        { source: "research_question", target: "s1", type: "informs" },
        { source: "research_question", target: "s2", type: "informs" },
        { source: "s1", target: "s2", type: "conflict", outcome: "cardiovascular events" },
      ],
    });
    render(<EvidenceMap researchQueryId="q1" />);

    await waitFor(() => {
      expect(screen.getByText("Does metformin help?")).toBeInTheDocument();
    });
    expect(screen.getByText("Benefit Study")).toBeInTheDocument();
    expect(screen.getByText("Harm Study")).toBeInTheDocument();
    expect(screen.getByText("Benefit")).toBeInTheDocument();
    expect(screen.getByText("Harm")).toBeInTheDocument();
    expect(screen.getAllByText("Conflict")).toHaveLength(1);
  });

  it("calls onSelectStudy with the study id when a study card is clicked", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      nodes: [
        { id: "research_question", type: "question", label: "Does X help?" },
        { id: "s1", type: "study", label: "Some Study", effect_direction: null, has_conflict: false },
      ],
      edges: [{ source: "research_question", target: "s1", type: "informs" }],
    });
    const onSelectStudy = vi.fn();
    const user = userEvent.setup();
    render(<EvidenceMap researchQueryId="q1" onSelectStudy={onSelectStudy} />);

    await waitFor(() => screen.getByText("Some Study"));
    await user.click(screen.getByText("Some Study"));

    expect(onSelectStudy).toHaveBeenCalledWith("s1");
  });
});
