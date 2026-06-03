import { useState } from "react";
import type { CallResult, ClaimStatus, ClaimStatusResult } from "../types";
import { Panel } from "./Panel";

const STATUS_STYLE: Record<ClaimStatus, string> = {
  paid: "bg-emerald-100 text-emerald-700",
  denied: "bg-rose-100 text-rose-700",
  pending: "bg-amber-100 text-amber-700",
  in_review: "bg-amber-100 text-amber-700",
  not_found: "bg-slate-200 text-slate-600",
  other: "bg-slate-200 text-slate-600",
};

function Field({ label, value }: { label: string; value?: string | number | null }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between gap-3 py-0.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-800">{String(value)}</span>
    </div>
  );
}

function ClaimCard({ claim }: { claim: ClaimStatusResult }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-xs text-slate-500">{claim.claim_id}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[claim.status]}`}>
          {claim.status}
        </span>
      </div>
      <Field label="Paid amount" value={claim.paid_amount != null ? `$${claim.paid_amount.toLocaleString()}` : null} />
      <Field label="Payment date" value={claim.payment_date} />
      <Field label="Check / EFT" value={claim.check_or_eft_number} />
      <Field label="Denial code" value={claim.denial_reason_code} />
      <Field label="Denial reason" value={claim.denial_reason_description} />
      <Field label="Appeal deadline" value={claim.appeal_deadline} />
      <Field label="Details" value={claim.status_details} />
    </div>
  );
}

export function ResultsPanel({ result }: { result: CallResult | null }) {
  const [raw, setRaw] = useState(false);

  return (
    <Panel
      title="Extracted Result"
      actions={
        result && (
          <button
            type="button"
            onClick={() => setRaw((r) => !r)}
            className="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
          >
            {raw ? "Cards" : "Raw JSON"}
          </button>
        )
      }
    >
      {!result ? (
        <p className="mt-8 text-center text-sm text-slate-400">
          Complete a call to see structured, 835-mapped output.
        </p>
      ) : raw ? (
        <pre className="flex-1 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
          {JSON.stringify(result, null, 2)}
        </pre>
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
