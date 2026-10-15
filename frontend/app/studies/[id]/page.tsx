"use client";

import { useEffect, useState } from "react";
import { AskPaperPanel } from "@/components/studies/AskPaperPanel";
import { api } from "@/lib/api/client";
import { DocumentType } from "@/types/rag";

interface StudyDetail {
  id: string;
  title: string;
  document_type: DocumentType | null;
  origin: string;
  publisher: string | null;
  published_date: string | null;
  conclusion: string | null;
  url: string | null;
}

export default function StudyPage({ params }: { params: { id: string } }) {
  const [study, setStudy] = useState<StudyDetail | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .get<StudyDetail>(`/api/studies/${params.id}`)
      .then((s) => !cancelled && setStudy(s))
      .catch(() => {
        /* study not found or inaccessible — the "could not be found" branch below covers this */
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  return (
    <main className="min-h-screen bg-ivory px-4 py-8 sm:px-6 sm:py-12">
      <div className="mx-auto max-w-2xl space-y-6">
        {loading && <p className="text-sm text-charcoal/60">Loading study&hellip;</p>}

        {!loading && study && (
          <div className="border border-charcoal/15 bg-white/60 px-5 py-6 sm:px-6">
            <p className="text-xs uppercase tracking-widest text-terracotta">{study.origin}</p>
            <h1 className="mt-1 font-serif text-xl text-burgundy">{study.title}</h1>
            {study.conclusion && <p className="mt-3 text-sm text-charcoal/80">{study.conclusion}</p>}
            {study.url && (
              <a
                href={study.url}
                target="_blank"
                rel="noreferrer"
                className="mt-3 inline-block text-sm text-sage underline"
              >
                View original source
              </a>
            )}
          </div>
        )}

        {!loading && !study && <p className="text-sm text-charcoal/60">This study could not be found.</p>}

        {!loading && study && (
          <AskPaperPanel studyId={study.id} studyTitle={study.title} documentType={study.document_type} />
        )}
      </div>
    </main>
  );
}
