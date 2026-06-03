import type { CallPhase } from "../types";
import { Panel } from "./Panel";
import { StatusBadge } from "./StatusBadge";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onLoadSample: () => void;
  onParse837: () => void;
  onStart: () => void;
  onEnd: () => void;
  phase: CallPhase;
  statusMessage?: string;
}

export function ClaimsPanel({
  value,
  onChange,
  onLoadSample,
  onParse837,
  onStart,
  onEnd,
  phase,
  statusMessage,
}: Props) {
  const inCall = phase === "connecting" || phase === "active";

  return (
    <Panel
      title="Claims"
      actions={
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onLoadSample}
            className="rounded-md bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700 hover:bg-brand-100"
          >
            Load sample
          </button>
          <button
            type="button"
            onClick={onParse837}
            className="rounded-md bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700 hover:bg-brand-100"
          >
            Parse 837
          </button>
        </div>
      }
    >
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
        className="flex-1 resize-none rounded-lg border border-slate-200 p-3 font-mono text-xs leading-relaxed focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
      />
      <p className="mt-2 text-xs text-slate-500">
        A CallRequest JSON (payer_name + 1–3 claims), or parse the bundled 837.
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onStart}
          disabled={inCall}
          className="flex-1 rounded-lg bg-brand-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-brand-100"
        >
          Start Call
        </button>
        <button
          type="button"
          onClick={onEnd}
          disabled={!inCall}
          className="flex-1 rounded-lg border border-rose-300 bg-white px-4 py-2.5 text-sm font-semibold text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          End Call
        </button>
      </div>
      <div className="mt-3">
        <StatusBadge phase={phase} message={statusMessage} />
      </div>
    </Panel>
  );
}
