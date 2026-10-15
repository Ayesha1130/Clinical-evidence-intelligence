import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import StudyPage from "@/app/studies/[id]/page";
import { api } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

describe("StudyPage", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
  });

  it("shows a loading state, then the real study title and conclusion", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      id: "s1",
      title: "Metformin RCT",
      document_type: "ABSTRACT",
      origin: "pubmed",
      publisher: "Diabetes Care",
      published_date: "2023-01-01",
      conclusion: "Supports a cardiovascular benefit.",
      url: "https://pubmed.ncbi.nlm.nih.gov/123/",
    });

    render(<StudyPage params={{ id: "s1" }} />);
    expect(screen.getByText(/loading study/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1, name: "Metformin RCT" })).toBeInTheDocument();
    });
    expect(screen.getByText("Supports a cardiovascular benefit.")).toBeInTheDocument();
    expect(screen.getByText("View original source")).toHaveAttribute(
      "href",
      "https://pubmed.ncbi.nlm.nih.gov/123/"
    );
    expect(api.get).toHaveBeenCalledWith("/api/studies/s1");
  });

  it("shows a not-found message when the study can't be loaded", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("404"));
    render(<StudyPage params={{ id: "missing" }} />);

    await waitFor(() => {
      expect(screen.getByText(/could not be found/i)).toBeInTheDocument();
    });
  });
});
