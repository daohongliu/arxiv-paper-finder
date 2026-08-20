import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type PaperSummary } from "../api";
import { Badge, ErrorBanner, Spinner, statusTone } from "../ui";

export default function Review() {
  const q1 = useQuery({ queryKey: ["review", "needs_review"], queryFn: () => api.papers({ status: "needs_review", page: 1, page_size: 200 }) });
  const q2 = useQuery({ queryKey: ["review", "unresolved"], queryFn: () => api.papers({ status: "unresolved", page: 1, page_size: 200 }) });
  const q3 = useQuery({ queryKey: ["review", "screen_error"], queryFn: () => api.papers({ status: "screen_error", page: 1, page_size: 200 }) });
  const queries = [q1, q2, q3];

  const loading = queries.some((q) => q.isLoading);
  const error = queries.find((q) => q.error)?.error;
  const items: PaperSummary[] = queries.flatMap((q) => q.data?.items ?? []);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Review queue</h1>
      <p className="text-sm text-zinc-500">
        Papers needing human adjudication: low-confidence screening, unresolved affiliation extraction, or screening errors.
        Open a paper to see the rationale and submit a verdict.
      </p>
      {error && <ErrorBanner error={error} />}
      {loading ? (
        <Spinner />
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-8 text-center text-zinc-500">
          Queue is empty.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {items.map((p) => (
            <Link
              key={p.id}
              to={`/papers/${p.id}`}
              className="flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-3 hover:border-zinc-700"
            >
              <span className="w-24 shrink-0 font-mono text-xs text-zinc-500">{p.arxiv_id}</span>
              <span className="flex-1 truncate text-sm text-zinc-200">{p.title}</span>
              <Badge tone={statusTone(p.status)}>{p.status.replaceAll("_", " ")}</Badge>
              {p.confidence != null && <span className="w-12 text-right text-xs tabular-nums text-zinc-500">{p.confidence.toFixed(2)}</span>}
              <span className="w-24 text-right text-xs text-zinc-500">{p.submitted.slice(0, 10)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
