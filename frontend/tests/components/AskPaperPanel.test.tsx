import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AskPaperPanel } from "@/components/studies/AskPaperPanel";
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

describe("AskPaperPanel", () => {
  beforeEach(() => {
    vi.mocked(api.post).mockReset();
  });

  it("renders the study title and document type", () => {
    render(<AskPaperPanel studyId="s1" studyTitle="Metformin RCT" documentType="ABSTRACT" />);
    expect(screen.getByText("Metformin RCT")).toBeInTheDocument();
    expect(screen.getByText("Abstract-level evidence")).toBeInTheDocument();
  });

  it("submits a question and renders a grounded answer with its citation", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      answer: "The study enrolled 250 participants.",
      grounded: true,
      document_type: "ABSTRACT",
      citations: [
        { document_id: "d1", chunk_id: "c1", excerpt: "enrolled 250 participants", similarity: 0.87 },
      ],
    });

    const user = userEvent.setup();
    render(<AskPaperPanel studyId="s1" studyTitle="Metformin RCT" />);

    await user.type(screen.getByLabelText(/what do you want to know/i), "What was the sample size?");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByText("The study enrolled 250 participants.")).toBeInTheDocument();
    });
    expect(screen.getByText("Grounded in this paper")).toBeInTheDocument();
    expect(screen.getByRole("blockquote")).toHaveTextContent("enrolled 250 participants");
    expect(screen.getByText(/Similarity 87%/)).toBeInTheDocument();
    expect(api.post).toHaveBeenCalledWith("/api/studies/s1/ask", { question: "What was the sample size?" });
  });

  it("shows the not-grounded badge and no evidence excerpt when unsupported", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      answer: "This paper does not provide enough information to answer that question.",
      grounded: false,
      document_type: "ABSTRACT",
      citations: [],
    });

    const user = userEvent.setup();
    render(<AskPaperPanel studyId="s1" studyTitle="Metformin RCT" />);
    await user.type(screen.getByLabelText(/what do you want to know/i), "What was the weather like?");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByText("Not found in this paper")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Evidence/)).not.toBeInTheDocument();
  });

  it("shows an error message when the API call fails", async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(500, "Something broke"));

    const user = userEvent.setup();
    render(<AskPaperPanel studyId="s1" studyTitle="Metformin RCT" />);
    await user.type(screen.getByLabelText(/what do you want to know/i), "A question?");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByText("Something broke")).toBeInTheDocument();
    });
  });

  it("disables the ask button while the question is empty", () => {
    render(<AskPaperPanel studyId="s1" studyTitle="Metformin RCT" />);
    expect(screen.getByRole("button", { name: /ask/i })).toBeDisabled();
  });
});
