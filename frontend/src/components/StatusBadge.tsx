import type { CallPhase } from "../types";

const CONFIG: Record<CallPhase, { label: string; dot: string; text: string; bg: string }> = {
  idle: { label: "Idle", dot: "bg-slate-400", text: "text-slate-600", bg: "bg-slate-100" },
  connecting: { label: "Connecting", dot: "bg-amber-500 animate-pulse", text: "text-amber-700", bg: "bg-amber-50" },
  active: { label: "In call", dot: "bg-emerald-500 animate-pulse", text: "text-emerald-700", bg: "bg-emerald-50" },
  complete: { label: "Complete", dot: "bg-brand-500", text: "text-brand-700", bg: "bg-brand-50" },
  error: { label: "Error", dot: "bg-rose-500", text: "text-rose-700", bg: "bg-rose-50" },
};

export function StatusBadge({ phase, message }: { phase: CallPhase; message?: string }) {
  const c = CONFIG[phase];
  return (
    <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${c.bg} ${c.text}`}>
      <span className={`h-2.5 w-2.5 rounded-full ${c.dot}`} />
      <span className="font-medium">{message ?? c.label}</span>
    </div>
  );
}
