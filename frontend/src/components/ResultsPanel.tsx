import { useState } from "react";
import type {
  CallResult,
  ClaimStatus,
  ClaimStatusResult,
  ClaimLineResult,
} from "../types";
import { Panel } from "./Panel";

const STATUS_STYLE: Record<ClaimStatus, string> = {
  adjusted: "bg-emerald-100 text-emerald-700",
  pending: "bg-amber-100 text-amber-700",
  not_found: "bg-slate-200 text-slate-600",
  unresolved: "bg-rose-100 text-rose-700",
};

const LINE_STYLE: Record<string, string> = {
  paid: "bg-emerald-50 text-emerald-700 border-emerald-200",
  denied: "bg-rose-50 text-rose-700 border-rose-200",
};

function money(value?: number | null): string | null {
  return value == null ? null : `$${value.toLocaleString()}`;
}

function Field({ label, value }: { label: string; value?: string | number | null }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between gap-3 py-0.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{String(value)}</span>
    </div>
  );
}

function LineRow({ line }: { line: ClaimLineResult }) {
  return (
    <div className={`rounded-md border px-2.5 py-1.5 text-xs ${LINE_STYLE[line.status] ?? "border-slate-200"}`}>
      <div className="flex items-center justify-between">
        <span className="font-mono">{line.procedure_code ?? line.line_number ?? "line"}</span>
        <span className="font-semibold uppercase">{line.status}</span>
      </div>
      {line.status === "paid" && money(line.paid_amount) && (
        <div className="mt-0.5 text-slate-600">Paid {money(line.paid_amount)}</div>
      )}
      {line.status === "denied" && (
        <div className="mt-0.5 text-slate-600">
          {line.denial_reason_code ? `${line.denial_reason_code}: ` : ""}
          {line.denial_reason_description}
        </div>
      )}
    </div>
  );
}

function ClaimCard({ claim }: { claim: ClaimStatusResult }) {
  return (
    <div
      className={`rounded-lg border p-3 ${
        claim.needs_human_review ? "border-amber-300 bg-amber-50/40" : "border-slate-200"
      }`}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-xs text-slate-500">{claim.claim_id}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[claim.status]}`}>
          {claim.status}
        </span>
      </div>

      {claim.needs_human_review && (
        <div className="mb-2 rounded-md border border-amber-300 bg-amber-100 px-2.5 py-1.5 text-xs text-amber-900">
          <span className="font-semibold">⚑ Needs human review</span>
          {claim.review_reasons && claim.review_reasons.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {claim.review_reasons.map((reason, i) => (
                <li key={i}>{reason}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {claim.status === "pending" && (
        <>
          <Field label="Reason" value={claim.pending_reason} />
          <Field label="Timeline" value={claim.pending_timeline} />
        </>
      )}

      {claim.lines.length > 0 && (
        <div className="mb-2 space-y-1">
          {claim.lines.map((line, i) => (
            <LineRow key={i} line={line} />
          ))}
        </div>
      )}

      <Field label="Total paid" value={money(claim.total_paid_amount)} />
      <Field label="Payment date" value={claim.payment_date} />
      <Field label="Check / EFT" value={claim.check_or_eft_number} />
      <Field label="Appeal deadline" value={claim.appeal_deadline} />
      <Field label="Details" value={claim.status_details} />
    </div>
  );
}

type Tab = "cards" | "transcript" | "json";

export function ResultsPanel({ result }: { result: CallResult | null }) {
  const [tab, setTab] = useState<Tab>("cards");

  const tabButton = (id: Tab, label: string) => (
    <button
      type="button"
      onClick={() => setTab(id)}
      className={`rounded-md px-2.5 py-1 text-xs font-medium ${
        tab === id ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
      }`}
    >
      {label}
    </button>
  );

  return (
    <Panel
      title="Extracted Result"
      actions={
        result && (
          <div className="flex gap-1.5">
            {tabButton("cards", "Cards")}
            {tabButton("transcript", "Transcript")}
            {tabButton("json", "JSON")}
          </div>
        )
      }
    >
      {!result ? (
        <p className="mt-8 text-center text-sm text-slate-400">
          Complete a call to see structured, 835-mapped output.
        </p>
      ) : tab === "json" ? (
        <pre className="flex-1 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
          {JSON.stringify(result, null, 2)}
        </pre>
      ) : tab === "transcript" ? (
        <div className="flex-1 space-y-2 overflow-y-auto pr-1">
          {result.transcript.length === 0 ? (
            <p className="mt-8 text-center text-sm text-slate-400">No transcript captured.</p>
          ) : (
            result.transcript.map((t, i) => (
              <div key={i} className="text-sm">
                <span className={`font-semibold ${t.role === "agent" ? "text-brand-700" : "text-slate-600"}`}>
                  {t.role === "agent" ? "Agent" : "Rep"}:
                </span>{" "}
                <span className="text-slate-700">{t.text}</span>
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="flex-1 space-y-3 overflow-y-auto pr-1">
          <div className="rounded-lg bg-slate-50 p-3">
            <Field label="Payer" value={result.payer_name} />
            <Field label="Rep" value={result.rep_name} />
            <Field label="Reference #" value={result.reference_number} />
          </div>
          {result.claims.map((c) => (
            <ClaimCard key={c.claim_id} claim={c} />
          ))}
        </div>
      )}
    </Panel>
  );
}
