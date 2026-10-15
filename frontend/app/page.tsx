"use client";

import { useState } from "react";

const FLOW_STEPS = [
  { label: "Question", detail: "You ask what the evidence actually shows." },
  { label: "Research", detail: "Agents search PubMed, trial registries, and the wider literature." },
  { label: "Studies", detail: "Relevant studies are retrieved and normalized." },
  { label: "Evidence", detail: "Findings are extracted and checked against source text." },
  { label: "Conflicts", detail: "Disagreements between studies are surfaced, not hidden." },
  { label: "Insight", detail: "A cited report shows what's known, contested, and unclear." },
];

const SOURCES = [
  { name: "PubMed", detail: "Peer-reviewed literature via NCBI's E-utilities." },
  { name: "ClinicalTrials.gov", detail: "Registered trial records, status, and outcomes." },
  { name: "Web research", detail: "Systematic reviews and guideline sources via Tavily, quality-screened." },
];

export default function LandingPage() {
  const [question, setQuestion] = useState("");

  return (
    <main className="min-h-screen bg-ivory text-charcoal">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:bg-burgundy focus:px-4 focus:py-2 focus:text-sm focus:text-ivory"
      >
        Skip to main content
      </a>
      <header className="border-b border-charcoal/10">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <span className="font-serif text-lg tracking-tight text-burgundy">
            Clinical Evidence Intelligence
          </span>
          <nav className="hidden gap-8 text-sm text-charcoal/70 md:flex">
            <a href="#how-it-works" className="hover:text-burgundy">How it works</a>
            <a href="#sources" className="hover:text-burgundy">Sources</a>
            <a href="#safety" className="hover:text-burgundy">Safety</a>
            <a href="/login" className="hover:text-burgundy">Log in</a>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section id="main-content" className="mx-auto max-w-6xl px-6 pb-20 pt-16 md:pt-24">
        <div className="grid gap-12 md:grid-cols-[1.1fr_0.9fr]">
          <div>
            <h1 className="font-serif text-4xl leading-tight text-burgundy md:text-6xl">
              Understand the evidence.
              <br />
              Not just the answer.
            </h1>
            <p className="mt-6 max-w-md text-lg leading-relaxed text-charcoal/80">
              An evidence intelligence platform for exploring medical literature,
              comparing studies, and understanding where the evidence agrees
              — or conflicts.
            </p>

            <form
              className="mt-10 border border-charcoal/15 bg-white/60 p-5"
              onSubmit={(e) => {
                e.preventDefault();
                window.location.href = `/research/new?q=${encodeURIComponent(question)}`;
              }}
            >
              <label htmlFor="research-question" className="block text-sm text-charcoal/70">
                What medical question are you investigating?
              </label>
              <textarea
                id="research-question"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Does metformin reduce cardiovascular risk in patients with type 2 diabetes?"
                rows={2}
                className="mt-2 w-full resize-none border-b border-charcoal/20 bg-transparent py-2 font-serif text-lg text-charcoal outline-none placeholder:text-charcoal/40 focus:border-terracotta"
              />
              <div className="mt-4 flex flex-wrap items-center gap-4">
                <button
                  type="submit"
                  className="bg-burgundy px-6 py-3 text-sm font-medium text-ivory transition-colors hover:bg-terracotta"
                >
                  Start research
                </button>
                <a href="#how-it-works" className="text-sm text-charcoal/70 underline decoration-charcoal/30 underline-offset-4 hover:text-burgundy">
                  Explore how it works
                </a>
              </div>
            </form>
          </div>

          {/* Evidence flow — a real sequence, so numbering is earned here */}
          <div className="border-l border-charcoal/15 pl-8">
            {FLOW_STEPS.map((step, i) => (
              <div key={step.label} className="relative pb-8 last:pb-0">
                {i < FLOW_STEPS.length - 1 && (
                  <span className="absolute -left-[33px] top-6 h-full w-px bg-charcoal/15" aria-hidden />
                )}
                <span className="absolute -left-[38px] top-0 flex h-6 w-6 items-center justify-center border border-gold text-xs text-gold">
                  {i + 1}
                </span>
                <p className="font-serif text-lg text-burgundy">{step.label}</p>
                <p className="mt-1 text-sm text-charcoal/70">{step.detail}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="border-t border-charcoal/10 bg-white/40 py-20">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="font-serif text-3xl text-burgundy">How it works</h2>
          <div className="mt-10 grid gap-10 md:grid-cols-3">
            <div>
              <p className="font-serif text-xl text-charcoal">Ask, don&apos;t guess</p>
              <p className="mt-2 text-sm leading-relaxed text-charcoal/70">
                Describe your research question in plain language. The system
                extracts the population, intervention, comparator, and outcomes
                you actually care about.
              </p>
            </div>
            <div>
              <p className="font-serif text-xl text-charcoal">Search, don&apos;t skim</p>
              <p className="mt-2 text-sm leading-relaxed text-charcoal/70">
                Dedicated agents query PubMed, ClinicalTrials.gov, and the wider
                literature in parallel, then deduplicate and normalize what
                they find.
              </p>
            </div>
            <div>
              <p className="font-serif text-xl text-charcoal">Verify, don&apos;t assume</p>
              <p className="mt-2 text-sm leading-relaxed text-charcoal/70">
                Every claim in your report is checked against the source text
                it came from. Claims that can&apos;t be supported are labeled or
                removed, never invented.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Sources */}
      <section id="sources" className="py-20">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="font-serif text-3xl text-burgundy">Research sources</h2>
          <div className="mt-10 divide-y divide-charcoal/10 border-y border-charcoal/10">
            {SOURCES.map((s) => (
              <div key={s.name} className="flex flex-col gap-1 py-5 md:flex-row md:items-baseline md:gap-8">
                <span className="w-56 shrink-0 font-serif text-lg text-charcoal">{s.name}</span>
                <span className="text-sm text-charcoal/70">{s.detail}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Conflict detection + Ask This Paper + Evidence Map */}
      <section className="border-t border-charcoal/10 bg-white/40 py-20">
        <div className="mx-auto grid max-w-6xl gap-12 px-6 md:grid-cols-3">
          <div className="border-l-2 border-terracotta pl-5">
            <p className="font-serif text-xl text-burgundy">Conflict detection</p>
            <p className="mt-2 text-sm leading-relaxed text-charcoal/70">
              When one study finds a benefit and another finds none, that
              disagreement is surfaced explicitly — along with a candidate
              explanation, if the evidence supports one.
            </p>
          </div>
          <div className="border-l-2 border-sage pl-5">
            <p className="font-serif text-xl text-burgundy">Ask this paper</p>
            <p className="mt-2 text-sm leading-relaxed text-charcoal/70">
              Open any study and ask it a direct question. Answers are grounded
              only in that paper&apos;s own text, with the supporting excerpt shown.
            </p>
          </div>
          <div className="border-l-2 border-gold pl-5">
            <p className="font-serif text-xl text-burgundy">Evidence map</p>
            <p className="mt-2 text-sm leading-relaxed text-charcoal/70">
              See your research question at the center, connected to every
              study that informs it — color-coded by direction and strength
              of evidence.
            </p>
          </div>
        </div>
      </section>

      {/* Safety */}
      <section id="safety" className="py-20">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <p className="font-serif text-2xl text-burgundy">A research tool, not a clinician</p>
          <p className="mt-4 text-sm leading-relaxed text-charcoal/70">
            This platform provides AI-assisted evidence research for
            informational and research purposes. It does not diagnose
            conditions, prescribe treatment, or replace the judgment of a
            qualified healthcare professional. Evidence strength shown here is
            an AI-assisted assessment, not an official clinical guideline
            grading system.
          </p>
        </div>
      </section>

      <footer className="border-t border-charcoal/10 py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 text-sm text-charcoal/60 md:flex-row">
          <span>Clinical Evidence Intelligence</span>
          <span>For research use. Not medical advice.</span>
        </div>
      </footer>
    </main>
  );
}
