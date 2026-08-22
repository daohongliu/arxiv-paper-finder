import { useRef, useState } from "react";
import { api, type EvalReport } from "../api";
import { Badge, Btn, Card, ErrorBanner, Stat } from "../ui";

export default function Eval() {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const onUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await api.importLabels(file));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Eval vs ground truth</h1>
      <p className="max-w-3xl text-sm text-zinc-500">
        Upload the human-labeled dataset (CSV or JSONL with an arXiv-ID column and a category column, e.g{" "}
        <code className="rounded bg-zinc-800 px-1">arxiv_id,category</code> with values like{" "}
        <code className="rounded bg-zinc-800 px-1">Alignment</code>,{" "}
        <code className="rounded bg-zinc-800 px-1">Monitoring (interpretability)</code>). The report shows how many
        ground-truth papers the pipeline recovers, where the rest were lost in the funnel, and category agreement.
        Importing also stores each paper's ground-truth membership, so the <strong>Papers</strong> tab can filter by
        "ground truth × included".
      </p>

      <div className="flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
        <input ref={fileRef} type="file" accept=".csv,.jsonl" className="text-sm text-zinc-400 file:mr-3 file:rounded-lg file:border-0 file:bg-zinc-800 file:px-3 file:py-1.5 file:text-sm file:text-zinc-200" />
        <Btn variant="primary" onClick={onUpload} disabled={busy || !fileRef.current?.files?.length}>
          {busy ? "Evaluating…" : "Run evaluation"}
        </Btn>
      </div>

      {error && <ErrorBanner error={new Error(error)} />}

      {report && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Ground-truth papers" value={report.total_gt} sub={`${report.rows_parsed ?? ""} rows parsed`} />
            <Stat label="Recovered by pipeline" value={report.included} />
            <Stat label="Recovery rate" value={`${(report.recovery * 100).toFixed(1)}%`} />
            <Stat label="Category accuracy" value={report.category_accuracy != null ? `${(report.category_accuracy * 100).toFixed(1)}%` : "—"} sub="among recovered & labeled" />
          </div>

          <Card title="Where ground-truth papers were lost">
            {Object.keys(report.dropped_at).length === 0 ? (
              <p className="text-sm text-emerald-400">Nothing lost — every ground-truth paper was included.</p>
            ) : (
              <div className="flex flex-col gap-2">
                {Object.entries(report.dropped_at).map(([stage, ids]) => (
                  <div key={stage} className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                      <Badge tone={stage === "not_fetched" ? "red" : "amber"}>{stage.replaceAll("_", " ")}</Badge>
                      <span className="text-xs text-zinc-500">{ids.length} papers</span>
                      {stage === "not_fetched" && <span className="text-xs text-zinc-600">→ keyword queries missed these; check search clauses / date window</span>}
                      {stage === "filtered_out" && <span className="text-xs text-zinc-600">→ China filter dropped them; check affiliation extraction</span>}
                      {stage === "unresolved" && <span className="text-xs text-zinc-600">→ PDF/extraction failed; retry affiliations</span>}
                      {stage === "screened_excluded" && <span className="text-xs text-zinc-600">→ LLM screening excluded; review prompt / thresholds</span>}
                      {stage === "needs_review" && <span className="text-xs text-zinc-600">→ waiting in the review queue</span>}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {ids.map((aid) => (
                        <span key={aid} className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[11px] text-zinc-400">{aid}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="Category confusion (ground truth → pipeline)">
            {Object.keys(report.category_matrix).length === 0 ? (
              <p className="text-sm text-zinc-500">No labeled recovered papers.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="text-sm">
                  <thead className="text-left text-xs uppercase tracking-wider text-zinc-500">
                    <tr>
                      <th className="px-2 py-1">GT ↓ / pipeline →</th>
                      {["alignment", "robustness", "monitoring", "systemic_safety", "(none)"].map((c) => (
                        <th key={c} className="px-2 py-1">{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/60">
                    {Object.entries(report.category_matrix).map(([gt, cols]) => (
                      <tr key={gt}>
                        <td className="px-2 py-1.5 font-medium text-zinc-300">{gt}</td>
                        {["alignment", "robustness", "monitoring", "systemic_safety", "(none)"].map((c) => {
                          const n = cols[c] ?? 0;
                          const isDiag = gt === c;
                          return (
                            <td key={c} className={`px-2 py-1.5 tabular-nums ${n === 0 ? "text-zinc-700" : isDiag ? "font-semibold text-emerald-400" : "text-red-400"}`}>
                              {n}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
