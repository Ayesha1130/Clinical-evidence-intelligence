import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import LoginPage from "@/app/login/page";
import NewResearchPage from "@/app/research/new/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    refresh: vi.fn(),
  }),
  useSearchParams: () => ({
    get: (key: string) => (key === "q" ? "metformin diabetes" : null),
  }),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      signInWithPassword: vi.fn().mockResolvedValue({ error: null }),
      signUp: vi.fn().mockResolvedValue({ data: { session: null }, error: null }),
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
    },
  }),
}));

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn().mockResolvedValue({ id: "q-123" }),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

describe("LoginPage Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders sign in form with email and password inputs", () => {
    render(<LoginPage />);
    expect(screen.getByLabelText(/Email Address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Sign In$/i }).length).toBeGreaterThanOrEqual(1);
  });


  it("switches to create account mode when clicked", () => {
    render(<LoginPage />);
    const createAccountTab = screen.getByRole("button", { name: /Create Account/i });
    fireEvent.click(createAccountTab);
    expect(screen.getByRole("button", { name: /Register Account/i })).toBeInTheDocument();
  });
});

describe("NewResearchPage Component", () => {
  it("renders research inquiry form pre-populated with search params", () => {
    render(<NewResearchPage />);
    const textarea = screen.getByRole("textbox", { name: /Primary Research Question/i });
    expect(textarea).toBeInTheDocument();
    expect((textarea as HTMLTextAreaElement).value).toBe("metformin diabetes");
  });

  it("toggles optional PICO framing inputs when clicked", () => {
    render(<NewResearchPage />);
    const toggleButton = screen.getByRole("button", { name: /Advanced PICO Framing/i });
    fireEvent.click(toggleButton);
    expect(screen.getByLabelText(/Population \(P\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Intervention \(I\)/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Comparator \(C\)/i)).toBeInTheDocument();
  });
});
