import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LandingPage from "@/app/page";

describe("LandingPage", () => {
  let originalLocation: Location;

  beforeEach(() => {
    originalLocation = window.location;
    // @ts-expect-error -- intentionally replacing window.location for the test
    delete window.location;
    window.location = { href: "" } as unknown as Location;
  });

  afterEach(() => {
    window.location = originalLocation;
  });

  it("renders the hero headline and research input", () => {
    render(<LandingPage />);
    expect(screen.getByText(/Understand the evidence\./)).toBeInTheDocument();
    expect(screen.getByLabelText(/what medical question are you investigating/i)).toBeInTheDocument();
  });

  it("navigates to /research/new with the typed question on submit", async () => {
    const user = userEvent.setup();
    render(<LandingPage />);

    const textarea = screen.getByLabelText(/what medical question are you investigating/i);
    await user.type(textarea, "Does metformin help?");
    await user.click(screen.getByRole("button", { name: /start research/i }));

    expect(window.location.href).toBe("/research/new?q=Does%20metformin%20help%3F");
  });

  it("lists all three research sources", () => {
    render(<LandingPage />);
    expect(screen.getByText("PubMed")).toBeInTheDocument();
    expect(screen.getByText("ClinicalTrials.gov")).toBeInTheDocument();
    expect(screen.getByText("Web research")).toBeInTheDocument();
  });

  it("includes the medical-safety disclaimer", () => {
    render(<LandingPage />);
    expect(screen.getByText(/does not diagnose conditions, prescribe treatment/i)).toBeInTheDocument();
  });

  it("has a skip-to-content link targeting the hero section", () => {
    render(<LandingPage />);
    const skipLink = screen.getByText(/skip to main content/i);
    expect(skipLink).toHaveAttribute("href", "#main-content");
  });
});
