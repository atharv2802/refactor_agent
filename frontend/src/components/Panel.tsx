import type { ReactNode } from "react";

export function Panel({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</h2>
        {actions}
      </div>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden p-4">{children}</div>
    </section>
  );
}
