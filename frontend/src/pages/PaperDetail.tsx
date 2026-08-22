import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, Btn, Card, ErrorBanner, Field, Input, Select, Spinner, statusTone } from "../ui";

const CATEGORIES = ["alignment", "robustness", "monitoring", "systemic_safety", "survey"];
const SUBCATEGORIES: Record<string, string[]> = {
  monitoring: ["interpretability", "evaluations", "other"],
};

function categoryLabel(c: string): string {
  return c === "survey" ? "Survey or Position Paper" : c.replaceAll("_", " ");
}

export default function PaperDetailPage() {
  const { id } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const backToPapers = () => {
    const state = window.history.state as { idx?: number } | null;
    if (state && typeof state.idx === "number" && state.idx > 0) navigate(-1);
    else navigate("/papers");
  };
  const { data: paper, isLoading, error } = useQuery({
    queryKey: ["paper", id],
    queryFn: () => api.paper(Number(id)),
    enabled: !!id,
  });

  const [included, setIncluded] = useState<boolean | null>(null);
  const [category, setCategory] = useState("");
  const [subcategory, setSubcategory] = useState("");
  const [note, setNote] = useState("");

  const del = useMutation({
    mutationFn: () => api.deletePaper(Number(id)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["papers"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      backToPapers();
    },
  });

  const review = useMutation({
    mutationFn: () =>
      api.review(Number(id), {
        included: included ?? false,
        category: included ? category || null : null,
        subcategory: included ? subcategory || null : null,
        note,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["paper", id] });
      setIncluded(null);
      setNote("");
    },
  });

  const invalidatePaper = () => {
    qc.invalidateQueries({ queryKey: ["paper", id] });
    qc.invalidateQueries({ queryKey: ["papers"] });
    qc.invalidateQueries({ queryKey: ["stats"] });
  };

  const affiliate = useMutation({
    mutationFn: () => api.affiliate(Number(id)),
    onSuccess: invalidatePaper,
  });

  const screen = useMutation({
    mutationFn: () => api.screen(Number(id)),
    onSuccess: invalidatePaper,
  });

  if (isLoading) return <Spinner />;
  if (error || !paper) return <ErrorBanner error={error ?? new Error("not found")} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="text-sm text-zinc-500">
          <button type="button" onClick={backToPapers} className="hover:text-zinc-300">← Papers</button>
        </div>
        <Btn
          variant="danger"
          disabled={del.isPending}
          onClick={() => {
            if (window.confirm(`Delete "${paper.title}" from the database and remove its cached PDF?`)) {
              del.mutate();
            }
          }}
        >
          {del.isPending ? "Deleting…" : "Delete paper"}
        </Btn>
      </div>
      {del.isError && <ErrorBanner error={del.error} />}

      <Card title="Run stages on this paper">
        <div className="flex flex-wrap items-center gap-3">
          <Btn
            variant="primary"
            disabled={affiliate.isPending || screen.isPending}
            onClick={() => affiliate.mutate()}
          >
            {affiliate.isPending ? "Affiliating…" : "Affiliate this paper"}
          </Btn>
          <Btn
            variant="primary"
            disabled={affiliate.isPending || screen.isPending}
            onClick={() => screen.mutate()}
          >
            {screen.isPending ? "Screening…" : "Screen this paper"}
          </Btn>
          <span className="text-xs text-zinc-500">
            Runs the LLM stage on this single paper (can take ~30s).
          </span>
        </div>
        {affiliate.isSuccess && affiliate.data && (
          <div className="mt-2 text-sm text-zinc-300">
            Affiliation result:{" "}
            <Badge tone={statusTone(affiliate.data.status)}>
              {affiliate.data.status.replaceAll("_", " ")}
            </Badge>
            {affiliate.data.likely_mainland_china && (
              <span className="text-zinc-500">
                {" "}· verdict {affiliate.data.likely_mainland_china}
              </span>
            )}
            {affiliate.data.detail && (
              <span className="text-zinc-500"> — {affiliate.data.detail}</span>
            )}
          </div>
        )}
        {screen.isSuccess && screen.data && (
          <div className="mt-2 text-sm text-zinc-300">
            Screening result:{" "}
            <Badge tone={statusTone(screen.data.status)}>
              {screen.data.status.replaceAll("_", " ")}
            </Badge>
            {screen.data.escalated && (
              <span className="text-zinc-500"> (full-text escalation)</span>
            )}
            {screen.data.error && (
              <span className="text-zinc-500"> — {screen.data.error}</span>
            )}
          </div>
        )}
        {affiliate.isError && <div className="mt-2"><ErrorBanner error={affiliate.error} /></div>}
        {screen.isError && <div className="mt-2"><ErrorBanner error={screen.error} /></div>}
      </Card>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm text-zinc-400">{paper.arxiv_id}v{paper.version}</span>
          <Badge tone={statusTone(paper.status)}>{paper.status.replaceAll("_", " ")}</Badge>
          {paper.category && <Badge tone="violet">{paper.category}{paper.subcategory ? ` / ${paper.subcategory}` : ""}</Badge>}
          {paper.in_gt && (
            <Badge tone="pink">
              in ground truth{paper.gt_category ? ` (${paper.gt_category}${paper.gt_subcategory ? `/${paper.gt_subcategory}` : ""})` : ""}
            </Badge>
          )}
          {paper.china_flag === 1 && <Badge tone="green">mainland-CN affiliated</Badge>}
          <Badge tone={paper.pdf_cached ? "green" : "zinc"}>{paper.pdf_cached ? "PDF downloaded" : "PDF not cached"}</Badge>
          {paper.confidence != null && <span className="text-xs text-zinc-500">confidence {paper.confidence.toFixed(2)}</span>}
        </div>
        <h1 className="text-xl font-semibold">{paper.title}</h1>
        <div className="text-sm text-zinc-400">
          {paper.submitted.slice(0, 10)} · {paper.categories.join(", ")} ·{" "}
          <a href={paper.abs_url} target="_blank" rel="noreferrer" className="text-emerald-400 hover:underline">abs</a>{" · "}
          <a href={paper.pdf_url} target="_blank" rel="noreferrer" className="text-emerald-400 hover:underline">pdf</a>
        </div>
        <div className="text-sm text-zinc-400">{paper.authors.join(", ")}</div>
        <div className="flex gap-1">
          {paper.queries.map((qq) => <Badge key={qq} tone="blue">{qq}</Badge>)}
        </div>
      </div>

      <Card title="Abstract">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-300">{paper.abstract}</p>
        {paper.rationale && (
          <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm text-zinc-400">
            <span className="font-medium text-zinc-300">LLM rationale: </span>
            {paper.rationale}
          </div>
        )}
      </Card>

      <Card title="Extracted affiliations">
        {!paper.affiliations ? (
          <p className="text-sm text-zinc-500">Not extracted yet — run the affiliations stage.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wider text-zinc-500">
                <tr>
                  <th className="px-2 py-1">Author</th>
                  <th className="px-2 py-1">Institution</th>
                  <th className="px-2 py-1">Country</th>
                  <th className="px-2 py-1">Mainland CN</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {paper.affiliations.authors.map((a, i) => (
                  <tr key={i}>
                    <td className="px-2 py-1.5">{a.name}</td>
                    <td className="px-2 py-1.5 text-zinc-300">{a.institution}</td>
                    <td className="px-2 py-1.5 text-zinc-400">{a.country}</td>
                    <td className="px-2 py-1.5">
                      <Badge tone={a.mainland_china === "yes" ? "green" : a.mainland_china === "unclear" ? "amber" : "zinc"}>
                        {a.mainland_china}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {paper.affiliations.likely_mainland_china && (
              <p className="mt-2 text-sm">
                Paper-level mainland-CN verdict:{" "}
                <Badge tone={paper.affiliations.likely_mainland_china === "yes" ? "green" : "zinc"}>
                  {paper.affiliations.likely_mainland_china}
                </Badge>
              </p>
            )}
            <p className="mt-2 text-xs text-zinc-500">
              model {paper.affiliations.model} · method {paper.affiliations.method} · {paper.affiliations.created_at}
            </p>
          </div>
        )}
      </Card>

      <Card title="Human review">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Verdict">
            <Select value={included == null ? "" : included ? "include" : "exclude"} onChange={(e) => setIncluded(e.target.value === "" ? null : e.target.value === "include")}>
              <option value="">Choose…</option>
              <option value="include">Include in dataset</option>
              <option value="exclude">Exclude</option>
            </Select>
          </Field>
          {included && (
            <>
              <Field label="Category">
                <Select value={category} onChange={(e) => { setCategory(e.target.value); setSubcategory(""); }}>
                  <option value="">Choose…</option>
                  {CATEGORIES.map((c) => <option key={c} value={c}>{categoryLabel(c)}</option>)}
                </Select>
              </Field>
              {SUBCATEGORIES[category] && (
                <Field label="Monitoring subcategory">
                  <Select value={subcategory} onChange={(e) => setSubcategory(e.target.value)}>
                    <option value="">Choose…</option>
                    {SUBCATEGORIES[category].map((s) => <option key={s} value={s}>{s}</option>)}
                  </Select>
                </Field>
              )}
            </>
          )}
          <Field label="Note">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional" className="w-64" />
          </Field>
          <Btn variant="primary" disabled={included == null || (included && !category) || review.isPending} onClick={() => review.mutate()}>
            {review.isPending ? "Saving…" : "Submit review"}
          </Btn>
        </div>
        {review.isError && <div className="mt-2"><ErrorBanner error={review.error} /></div>}
        {paper.labels.length > 0 && (
          <div className="mt-3 flex flex-col gap-1 text-xs text-zinc-500">
            {paper.labels.map((l, i) => (
              <div key={i}>
                [{l.source}] {l.included ? "included" : "excluded"}
                {l.category ? ` as ${l.category}${l.subcategory ? `/${l.subcategory}` : ""}` : ""}
                {l.note ? ` — ${l.note}` : ""} ({l.created_at})
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={`LLM call history (${paper.llm_calls.length})`}>
        {paper.llm_calls.length === 0 ? (
          <p className="text-sm text-zinc-500">No calls yet.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {paper.llm_calls.map((c, i) => (
              <details key={i} className="rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-sm">
                <summary className="cursor-pointer select-none text-zinc-300">
                  <span className="font-medium">{c.stage}</span>
                  <span className="ml-2 text-xs text-zinc-500">{c.model} · {c.request_summary}</span>
                  <span className="ml-2 text-xs text-zinc-600">{c.input_tokens}→{c.output_tokens} tok · {c.latency_ms}ms</span>
                </summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-xs text-zinc-400">{c.response_text}</pre>
              </details>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
