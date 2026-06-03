import { useEffect, useRef } from "react";
import type { TranscriptEntry } from "../types";
import { Panel } from "./Panel";

export function TranscriptPanel({ entries }: { entries: TranscriptEntry[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries.length]);

  return (
    <Panel title="Live Transcript">
      <div className="flex-1 overflow-y-auto pr-1">
        {entries.length === 0 ? (
          <p className="mt-8 text-center text-sm text-slate-400">
            Transcript will appear here once the call starts.
          </p>
        ) : (
          entries.map((e, i) => (
            <div key={i} className={`mb-3 flex ${e.role === "agent" ? "justify-end" : "justify-start"}`}>
              <div className="max-w-[85%]">
                <div className={`mb-0.5 text-[11px] text-slate-400 ${e.role === "agent" ? "text-right" : ""}`}>
                  {e.role === "agent" ? "Agent" : "Rep"}
                </div>
                <div
                  className={`rounded-2xl px-3.5 py-2 text-sm ${
                    e.role === "agent"
                      ? "bg-brand-100 text-brand-700"
                      : "bg-slate-100 text-slate-700"
                  }`}
                >
                  {e.text}
                </div>
              </div>
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>
    </Panel>
  );
}
