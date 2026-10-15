"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { EvidenceMapNode, EvidenceMapOut } from "@/types/report";

interface EvidenceMapProps {
  researchQueryId: string;
  onSelectStudy?: (studyId: string) => void;
}

const DIRECTION_STYLES: Record<string, string> = {
  BENEFIT: "border-sage text-sage",
  HARM: "border-terracotta text-terracotta",
  NO_EFFECT: "border-charcoal/30 text-charcoal/60",
  UNCLEAR: "border-gold text-gold",
};

const DIRECTION_LABEL: Record<string, string> = {
  BENEFIT: "Benefit",
  HARM: "Harm",
  NO_EFFECT: "No effect",
  UNCLEAR: "Unclear",
};

export function EvidenceMap({ researchQueryId, onSelectStudy }: EvidenceMapProps) {
  const [map, setMap] = useState<EvidenceMapOut | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api
      .get<EvidenceMapOut>(`/api/research/${researchQueryId}/evidence-map`)
      .then((m) => !cancelled && setMap(m))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [researchQueryId]);

  if (loading) return <p className="text-sm text-charcoal/60">Loading evidence map&hellip;</p>;
  if (!map) return null;

  const questionNode = map.nodes.find((n) => n.type === "question");
  const studyNodes = map.nodes.filter((n): n is EvidenceMapNode & { type: "study" } => n.type === "study");

  if (studyNodes.length === 0) {
    return (
      <div className="border border-charcoal/15 bg-white/60 px-6 py-10 text-center">
        <p className="text-sm text-charcoal/60">No studies to map yet.</p>
      </div>
    );
  }

  return (
    <div className="border border-charcoal/15 bg-white/60 px-4 py-6 sm:px-6 sm:py-8">
      <div className="mx-auto max-w-md border-2 border-burgundy px-6 py-4 text-center">
        <p className="text-xs uppercase tracking-widest text-terracotta">Research question</p>
        <p className="mt-1 font-serif text-lg text-burgundy">{questionNode?.label}</p>
      </div>

      <div className="mx-auto mt-6 h-8 w-px bg-charcoal/20" />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {studyNodes.map((node) => {
          const style = node.effect_direction
            ? DIRECTION_STYLES[node.effect_direction]
            : "border-charcoal/20 text-charcoal/50";
          return (
            <button
              key={node.id}
              onClick={() => onSelectStudy?.(node.id)}
              className={`border ${style} bg-white/70 px-4 py-3 text-left transition-shadow hover:shadow-sm`}
            >
              <p className="line-clamp-2 font-serif text-sm text-charcoal">{node.label}</p>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                {node.effect_direction && (
                  <span className={`border px-1.5 py-0.5 ${style}`}>{DIRECTION_LABEL[node.effect_direction]}</span>
                )}
                {node.has_conflict && (
                  <span className="border border-terracotta px-1.5 py-0.5 text-terracotta">Conflict</span>
                )}
                {node.year && <span className="text-charcoal/50">{node.year}</span>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
