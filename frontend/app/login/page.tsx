"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setMessage(null);

    try {
      const supabase = createClient();

      if (isSignUp) {
        const { error, data } = await supabase.auth.signUp({
          email,
          password,
        });

        if (error) {
          setMessage({ type: "error", text: error.message });
        } else if (data.session) {
          setMessage({ type: "success", text: "Account created and logged in!" });
          router.push("/");
          router.refresh();
        } else {
          setMessage({
            type: "success",
            text: "Account registered. Please check your email to confirm your account before logging in.",
          });
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password,
        });

        if (error) {
          setMessage({ type: "error", text: error.message });
        } else {
          setMessage({ type: "success", text: "Signed in successfully." });
          router.push("/");
          router.refresh();
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error) {
        setMessage({ type: "error", text: err.message });
      } else {
        setMessage({ type: "error", text: "Authentication service unavailable." });
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-ivory px-4 py-12 sm:px-6 sm:py-16">
      <div className="mx-auto max-w-md">
        <div className="mb-6 text-center">
          <Link
            href="/"
            className="font-serif text-xl tracking-tight text-burgundy hover:text-terracotta"
          >
            Clinical Evidence Intelligence
          </Link>
          <p className="mt-2 text-xs uppercase tracking-widest text-charcoal/50">
            Secure Practitioner & Researcher Portal
          </p>
        </div>

        <div className="border border-charcoal/15 bg-white/70 p-6 sm:p-8 shadow-sm">
          <div className="flex border-b border-charcoal/15 pb-4">
            <button
              type="button"
              onClick={() => {
                setIsSignUp(false);
                setMessage(null);
              }}
              className={`flex-1 pb-2 text-center text-sm font-medium transition-colors ${
                !isSignUp
                  ? "border-b-2 border-burgundy text-burgundy font-serif"
                  : "text-charcoal/50 hover:text-charcoal"
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => {
                setIsSignUp(true);
                setMessage(null);
              }}
              className={`flex-1 pb-2 text-center text-sm font-medium transition-colors ${
                isSignUp
                  ? "border-b-2 border-burgundy text-burgundy font-serif"
                  : "text-charcoal/50 hover:text-charcoal"
              }`}
            >
              Create Account
            </button>
          </div>

          {message && (
            <div
              className={`mt-4 border-l-4 p-3 text-sm ${
                message.type === "error"
                  ? "border-terracotta bg-terracotta/10 text-charcoal"
                  : "border-sage bg-sage/10 text-charcoal"
              }`}
              role="alert"
            >
              {message.text}
            </div>
          )}

          <form onSubmit={handleSubmit} className="mt-6 space-y-5">
            <div>
              <label htmlFor="auth-email" className="block text-xs font-semibold uppercase tracking-wider text-charcoal/70">
                Email Address
              </label>
              <input
                id="auth-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="physician@hospital.org"
                className="mt-1 w-full border border-charcoal/20 bg-ivory/40 p-2.5 text-sm text-charcoal focus:border-terracotta focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="auth-password" className="block text-xs font-semibold uppercase tracking-wider text-charcoal/70">
                Password
              </label>
              <input
                id="auth-password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                minLength={6}
                className="mt-1 w-full border border-charcoal/20 bg-ivory/40 p-2.5 text-sm text-charcoal focus:border-terracotta focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-burgundy py-3 text-sm font-medium text-ivory transition-colors hover:bg-terracotta disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading
                ? isSignUp
                  ? "Registering..."
                  : "Authenticating..."
                : isSignUp
                ? "Register Account"
                : "Sign In"}
            </button>
          </form>

          <div className="mt-6 border-t border-charcoal/10 pt-4 text-center">
            <Link
              href="/"
              className="text-xs text-charcoal/60 underline hover:text-burgundy"
            >
              Continue exploring without signing in
            </Link>
          </div>
        </div>

        <p className="mt-6 text-center text-xs text-charcoal/50">
          Clinical Evidence Intelligence &middot; Academic & Clinical Research Platform
        </p>
      </div>
    </main>
  );
}
