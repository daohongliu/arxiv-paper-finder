import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Card, ErrorBanner, Spinner, Stat } from "../ui";

const STATUS_LABELS: Record<string, string> = {
  fetched: "Fetched",
  affiliated: "Passed China filter",
  filtered_out: "Filtered out (no CN)",
  unresolved: "Unresolved",
  screened_included: "Included",
  screened_excluded: "Excluded",
  needs_review: "Needs review",
  screen_error: "Screen error",
};

function Overview() {
  const { data: stats, isLoading, error } = useQuery({ queryKey: ["stats"], queryFn: api.stats });

  if (isLoading) return <Spinner />;
  if (error || !stats) return <ErrorBanner error={error ?? new Error("no stats")} />;

  const included = stats.by_status["screened_included"] ?? 0;
  const excluded = stats.by_status["screened_excluded"] ?? 0;
  const review = stats.by_status["needs_review"] ?? 0;
  const unresolved = stats.by_status["unresolved"] ?? 0;
  const maxMonth = Math.max(1, ...stats.included_monthly.map((m) => m.n));
  const maxCat = Math.max(1, ...stats.by_category.map((c) => c.n));

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Papers total" value={stats.papers_total} />
        <Stat label="Included" value={included} sub={stats.papers_total ? `${((included / stats.papers_total) * 100).toFixed(1)}% of total` : undefined} />
        <Stat label="Excluded" value={excluded} />
        <Stat label="Needs review" value={review + unresolved} />
        <Stat label="Active jobs" value={stats.active_jobs} />
        <Stat label="LLM calls" value={stats.llm.calls} sub={`${((stats.llm.input_tokens + stats.llm.output_tokens) / 1e6).toFixed(2)}M tokens`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Pipeline funnel">
          <div className="flex flex-col gap-2">
            {Object.entries(stats.by_status)
              .sort((a, b) => b[1] - a[1])
              .map(([status, n]) => (
                <div key={status} className="flex items-center gap-2">
                  <div className="w-40 shrink-0 text-xs text-zinc-400">{STATUS_LABELS[status] ?? status}</div>
                  <div className="h-4 flex-1 overflow-hidden rounded bg-zinc-800">
                    <div
                      className={`h-full ${status === "screened_included" ? "bg-emerald-600" : status === "screened_excluded" ? "bg-zinc-600" : "bg-sky-700"}`}
                      style={{ width: `${stats.papers_total ? (n / stats.papers_total) * 100 : 0}%` }}
                    />
                  </div>
                  <div className="w-14 text-right text-xs tabular-nums text-zinc-300">{n}</div>
                </div>
              ))}
          </div>
        </Card>

        <Card title="Included by category">
          {stats.by_category.length === 0 ? (
            <p className="text-sm text-zinc-500">No included papers yet.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {stats.by_category.map((c) => (
                <div key={`${c.category}-${c.subcategory}`} className="flex items-center gap-2">
                  <div className="w-48 shrink-0 truncate text-xs text-zinc-400">
                    {c.category}
                    {c.subcategory ? <span className="text-zinc-600"> / {c.subcategory}</span> : null}
                  </div>
                  <div className="h-4 flex-1 overflow-hidden rounded bg-zinc-800">
                    <div className="h-full bg-violet-600" style={{ width: `${(c.n / maxCat) * 100}%` }} />
                  </div>
                  <div className="w-10 text-right text-xs tabular-nums text-zinc-300">{c.n}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Included papers per month">
        {stats.included_monthly.length === 0 ? (
          <p className="text-sm text-zinc-500">Nothing included yet.</p>
        ) : (
          <div className="flex h-40 items-end gap-1 overflow-x-auto">
            {stats.included_monthly.map((m) => (
              <div key={m.month} className="flex min-w-8 flex-col items-center gap-1">
                <div className="w-6 rounded-t bg-emerald-600" style={{ height: `${(m.n / maxMonth) * 128}px` }} title={`${m.month}: ${m.n}`} />
                <div className="text-[10px] text-zinc-500">{m.month.slice(2)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export default function Dashboard() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <Overview />
    </div>
  );
}
