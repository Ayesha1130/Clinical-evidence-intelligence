"use client";

import { useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type AgentStatus = "pending" | "running" | "completed" | "failed";

const STAGE_ORDER = [
  { agent: "query_analyzer", label: "Query Analyzer" },
  { agent: "pubmed_research", label: "PubMed Search" },
  { agent: "clinical_trials_research", label: "Clinical Trials" },
  { agent: "web_research", label: "Web Research" },
  { agent: "document_indexing", label: "Document Indexing" },
  { agent: "study_analysis", label: "Study Analysis" },
  { agent: "evidence_verification", label: "Evidence Verification" },
  { agent: "conflict_detection", label: "Conflict Detection" },
  { agent: "evidence_grading", label: "Evidence Grading" },
  { agent: "report_generation", label: "Report Generation" },
] as const;

interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
  timestamp: string;
}

interface ResearchProgressProps {
  researchQueryId: string;
  onComplete?: (status: string) => void;
}

const STATUS_ICON: Record<AgentStatus, string> = {
  pending: "\u25cb",
  running: "\u25cf",
  completed: "\u2713",
  failed: "\u2717",
};

const STATUS_COLOR: Record<AgentStatus, string> = {
  pending: "text-charcoal/30",
  running: "text-gold",
  completed: "text-sage",
  failed: "text-terracotta",
};

const STATUS_LABEL: Record<AgentStatus, string> = {
  pending: "Pending",
  running: "In progress",
  completed: "Completed",
  failed: "Failed",
};

export function ResearchProgress({ researchQueryId, onComplete }: ResearchProgressProps) {
  const [statuses, setStatuses] = useState<Record<string, AgentStatus>>({});
  const [notices, setNotices] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    const controller = new AbortController();

    async function checkExistingJob(): Promise<boolean> {
      try {
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const supabase = createClient();
        const {
          data: { session },
        } = await supabase.auth.getSession();
        if (!session) return false;

        const res = await fetch(`${apiUrl}/api/research/${researchQueryId}/job`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
          signal: controller.signal,
        });
        if (res.ok) {
          const job = await res.json();
          if (job.status === "COMPLETED" || job.status === "PARTIAL") {
            const completedStatuses: Record<string, AgentStatus> = {};
            for (const item of STAGE_ORDER) {
              completedStatuses[item.agent] = "completed";
            }
            setStatuses(completedStatuses);
            setDone(true);
            onCompleteRef.current?.(job.status);
            return true;
          } else if (job.status === "FAILED") {
            setDone(true);
            if (job.failure_summary) {
              setNotices([job.failure_summary]);
            }
            onCompleteRef.current?.(job.status);
            return true;
          }
        }
      } catch {
        // Continue to SSE subscription
      }
      return false;
    }

    async function subscribe() {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!session) return;

      const response = await fetch(`${apiUrl}/api/research/${researchQueryId}/events`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
        signal: controller.signal,
      });
      if (!response.body) return;

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });

        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);

          const dataLine = rawEvent.split("\n").find((l) => l.startsWith("data: "));
          if (!dataLine) continue;
          const parsed: SSEEvent = JSON.parse(dataLine.slice("data: ".length));
          handleEvent(parsed);
        }
      }
    }

    function handleEvent(evt: SSEEvent) {
      const agent = evt.data.agent as string | undefined;

      if (evt.event === "agent_started" && agent) {
        setStatuses((prev) => ({ ...prev, [agent]: "running" }));
      } else if (evt.event === "agent_completed" && agent) {
        setStatuses((prev) => ({ ...prev, [agent]: "completed" }));
      } else if (evt.event === "agent_failed" && agent) {
        setStatuses((prev) => ({ ...prev, [agent]: "failed" }));
      } else if (evt.event === "study_found") {
        setNotices((prev) => [...prev, `Found ${evt.data.count} result(s) from ${evt.data.origin}`]);
      } else if (evt.event === "conflict_found") {
        setNotices((prev) => [...prev, `Conflict detected: ${evt.data.outcome}`]);
      } else if (evt.event === "report_ready") {
        setNotices((prev) => [...prev, "Research report is ready"]);
      } else if (evt.event === "pipeline_completed") {
        setDone(true);
        onCompleteRef.current?.(evt.data.status as string);
      }
    }

    checkExistingJob().then((alreadyDone) => {
      if (!alreadyDone && !controller.signal.aborted) {
        subscribe().catch(() => {
          /* connection closed or aborted */
        });
      }
    });

    return () => controller.abort();
  }, [researchQueryId]);

  return (
    <div className="border border-charcoal/15 bg-white/60 px-6 py-6" role="status" aria-live="polite">
      <p className="text-xs uppercase tracking-widest text-terracotta">
        {done ? "Research complete" : "Research in progress"}
      </p>

      <ul className="mt-4 space-y-2">
        {STAGE_ORDER.map(({ agent, label }) => {
          const s = statuses[agent] ?? "pending";
          return (
            <li key={agent} className="flex items-center gap-3">
              <span aria-hidden="true" className={`w-4 text-center ${STATUS_COLOR[s]}`}>
                {STATUS_ICON[s]}
              </span>
              <span className={s === "pending" ? "text-charcoal/40" : "text-charcoal"}>
                {label}
                <span className="sr-only"> — {STATUS_LABEL[s]}</span>
              </span>
            </li>
          );
        })}
      </ul>


      {notices.length > 0 && (
        <ul className="mt-5 space-y-1 border-t border-charcoal/10 pt-4 text-xs text-charcoal/60">
          {notices.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
