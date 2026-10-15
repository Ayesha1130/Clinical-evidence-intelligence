"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { EvidenceMap } from "@/components/research/EvidenceMap";
import { ResearchProgress } from "@/components/research/ResearchProgress";
import { ResearchReport } from "@/components/research/ResearchReport";

export default function ResearchResultsPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [pipelineDone, setPipelineDone] = useState(false);

  return (
    <main className="min-h-screen bg-ivory px-4 py-8 sm:px-6 sm:py-12">
      <div className="mx-auto max-w-4xl space-y-8 sm:space-y-10">
        <ResearchProgress researchQueryId={params.id} onComplete={() => setPipelineDone(true)} />
        {pipelineDone && (
          <>
            <EvidenceMap researchQueryId={params.id} onSelectStudy={(studyId) => router.push(`/studies/${studyId}`)} />
            <ResearchReport researchQueryId={params.id} />
          </>
        )}
      </div>
    </main>
  );
}
