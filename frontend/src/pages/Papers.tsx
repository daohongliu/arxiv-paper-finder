import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Badge, Btn, ErrorBanner, Input, Select, Spinner, statusTone } from "../ui";

const STATUSES = ["", "fetched", "affiliated", "filtered_out", "unresolved", "screened_included", "screened_excluded", "needs_review", "screen_error"];
const CATEGORIES = ["", "alignment", "robustness", "monitoring", "systemic_safety"];
const DIRECTIONS = ["alignment", "robustness", "monitoring", "systemic_safety", "survey"];
const SUBCATEGORIES: Record<string, string[]> = {
  monitoring: ["interpretability", "evaluations", "other"],
};

// Remember the last Papers filter/page state in memory so switching tabs (or going
// back from a paper) restores it even when the URL has no query string.
let lastPapersParams: Record<string, string> = {};

export default function Papers() {
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const getParam = (key: string) => searchParams.get(key) ?? lastPapersParams[key] ?? "";

  const status = getParam("status");
  const category = getParam("category");
  const china = getParam("china");
  const q = getParam("q");
  const dateFrom = getParam("date_from");
  const dateTo = getParam("date_to");
  const gt = getParam("gt");
  const included = getParam("included");
  const page = Number(getParam("page") || "1") || 1;

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [direction, setDirection] = useState("alignment");
  const [subcategory, setSubcategory] = useState("");

  const updateParams = (updates: Record<string, string | undefined>, resetPage = false) => {
    const next = new URLSearchParams(lastPapersParams);
    for (const [k, v] of searchParams.entries()) next.set(k, v);
    for (const [k, v] of Object.entries(updates)) {
      if (v === undefined || v === "") next.delete(k);
      else next.set(k, v);
    }
    if (resetPage) next.set("page", "1");
    lastPapersParams = Object.fromEntries(next.entries());
    setSearchParams(next);
  };
  const setFilter = (key: string, value: string) => updateParams({ [key]: value }, true);
  const goPage = (p: number) => updateParams({ page: String(p) });

  // On mount, reconcile memory with the URL: restore the URL from memory when Papers is
  // reached via a bare /papers link, otherwise sync memory from the URL (refresh / back).
  useEffect(() => {
    if (searchParams.toString() === "") {
      if (Object.keys(lastPapersParams).length > 0) setSearchParams(lastPapersParams, { replace: true });
    } else {
      lastPapersParams = Object.fromEntries(searchParams.entries());
    }
  }, []);

  const { data, isLoading, error } = useQuery({
    queryKey: ["papers", status, category, china, gt, included, q, dateFrom, dateTo, page],
    queryFn: () =>
      api.papers({
        status: status || undefined,
        category: category || undefined,
        china: china === "" ? undefined : china === "1",
        gt: gt === "" ? undefined : gt === "1",
        included: included === "" ? undefined : included === "1",
        q: q || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page,
        page_size: 50,
      }),
  });

  const { data: stats } = useQuery({ queryKey: ["stats"], queryFn: api.stats });

  const applyGtIncluded = (g: string, inc: string) => {
    updateParams({ gt: g, included: inc }, true);
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const bulk = useMutation({
    mutationFn: (included: boolean) =>
      api.bulkReview([...selected], {
        included,
        category: included ? direction : null,
        subcategory: included && direction === "monitoring" ? subcategory || "other" : null,
        note: "bulk review from Papers tab",
      }),
    onSuccess: () => {
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["papers"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const quickExclude = useMutation({
    mutationFn: (id: number) => api.review(id, { included: false, note: "quick exclude" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["papers"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const deleteOne = useMutation({
    mutationFn: (id: number) => api.deletePaper(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["papers"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const bulkDelete = useMutation({
    mutationFn: () => api.bulkDelete([...selected]),
    onSuccess: () => {
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["papers"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const confirmDeleteOne = (id: number, title: string) => {
    if (window.confirm(`Delete "${title}" from the database and remove its cached PDF?`)) {
      deleteOne.mutate(id);
    }
  };

  const confirmBulkDelete = () => {
    if (window.confirm(`Delete ${selected.size} selected paper(s) from the database and remove their cached PDFs?`)) {
      bulkDelete.mutate();
    }
  };

  const toggle = (id: number) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const pageIds = useMemo(() => data?.items.map((p) => p.id) ?? [], [data]);
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const togglePage = () => {
    setSelected((s) => {
      const next = new Set(s);
      if (allPageSelected) pageIds.forEach((id) => next.delete(id));
      else pageIds.forEach((id) => next.add(id));
      return next;
    });
  };

  const downloadExport = () => {
    window.location.href = api.exportCsvUrl(dateFrom || undefined, dateTo || undefined);
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Papers</h1>
        <Btn variant="primary" onClick={downloadExport}>
          Export CSV{dateFrom || dateTo ? ` (${dateFrom || "…"} → ${dateTo || "…"})` : " (all dates)"}
        </Btn>
      </div>

      <div className="flex flex-wrap items-end gap-2 rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
        <Select value={status} onChange={(e) => setFilter("status", e.target.value)}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s === "" ? "All statuses" : s.replaceAll("_", " ")}</option>
          ))}
        </Select>
        <Select value={category} onChange={(e) => setFilter("category", e.target.value)}>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c === "" ? "All categories" : c.replaceAll("_", " ")}</option>
          ))}
        </Select>
        <Select value={china} onChange={(e) => setFilter("china", e.target.value)}>
          <option value="">China: any</option>
          <option value="1">China: yes</option>
          <option value="0">China: no</option>
        </Select>
        <Select value={gt} onChange={(e) => setFilter("gt", e.target.value)}>
          <option value="">GT: any</option>
          <option value="1">GT: in ground truth</option>
          <option value="0">GT: not in ground truth</option>
        </Select>
        <Select value={included} onChange={(e) => setFilter("included", e.target.value)}>
          <option value="">Included: any</option>
          <option value="1">Included: yes</option>
          <option value="0">Included: no</option>
        </Select>
        <Input type="date" value={dateFrom} onChange={(e) => setFilter("date_from", e.target.value)} />
        <span className="text-zinc-600">→</span>
        <Input type="date" value={dateTo} onChange={(e) => setFilter("date_to", e.target.value)} />
        <Input placeholder="Search title/abstract/id…" value={q} onChange={(e) => setFilter("q", e.target.value)} className="w-64" />
        <div className="ml-auto flex items-center gap-2 text-sm text-zinc-400">
          <span className="rounded-lg bg-zinc-800 px-2.5 py-1 font-semibold text-emerald-300">
            {data ? data.total : "…"} {data && data.total === 1 ? "paper" : "papers"}
          </span>
        </div>
      </div>

      {stats && stats.ground_truth.total > 0 && (
        <div className="flex flex-wrap items-center gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
          <div className="text-xs uppercase tracking-wider text-zinc-400">
            Ground truth × included{" "}
            <span className="text-zinc-500">({stats.ground_truth.total} GT papers)</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {(
              [
                { label: "GT · included", g: "1", inc: "1", v: stats.ground_truth.matrix.in_gt_included },
                { label: "GT · not included", g: "1", inc: "0", v: stats.ground_truth.matrix.in_gt_not_included },
                { label: "not GT · included", g: "0", inc: "1", v: stats.ground_truth.matrix.not_in_gt_included },
                { label: "not GT · not included", g: "0", inc: "0", v: stats.ground_truth.matrix.not_in_gt_not_included },
              ] as const
            ).map((c) => {
              const active = gt === c.g && included === c.inc;
              return (
                <button
                  key={c.label}
                  onClick={() => applyGtIncluded(c.g, c.inc)}
                  title={`Filter: ${c.label}`}
                  className={`rounded-lg border px-3 py-1.5 text-right tabular-nums transition-colors ${active ? "border-emerald-500 bg-emerald-950/40" : "border-zinc-700 bg-zinc-800 hover:border-zinc-500"}`}
                >
                  <span className="block text-[11px] leading-tight text-zinc-500">{c.label}</span>
                  <span className={`font-semibold ${active ? "text-emerald-300" : "text-zinc-100"}`}>{c.v}</span>
                </button>
              );
            })}
          </div>
          {(gt !== "" || included !== "") && (
            <button onClick={() => applyGtIncluded("", "")} className="text-xs text-zinc-500 hover:text-zinc-300">
              clear GT filter
            </button>
          )}
        </div>
      )}

      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-emerald-900 bg-emerald-950/30 p-3">
          <span className="text-sm font-medium text-emerald-300">{selected.size} selected</span>
          <Select value={direction} onChange={(e) => { setDirection(e.target.value); setSubcategory(""); }}>
            {DIRECTIONS.map((d) => (
              <option key={d} value={d}>{d === "survey" ? "Survey or Position Paper" : d.replaceAll("_", " ")}</option>
            ))}
          </Select>
          {direction === "monitoring" && (
            <Select value={subcategory} onChange={(e) => setSubcategory(e.target.value)}>
              <option value="">subcategory…</option>
              {(SUBCATEGORIES.monitoring).map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
          )}
          <Btn
            variant="primary"
            disabled={bulk.isPending || (direction === "monitoring" && !subcategory)}
            onClick={() => bulk.mutate(true)}
          >
            Mark included
          </Btn>
          <Btn variant="danger" disabled={bulk.isPending} onClick={() => bulk.mutate(false)}>
            Mark excluded
          </Btn>
          <Btn variant="danger" disabled={bulkDelete.isPending} onClick={confirmBulkDelete}>
            {bulkDelete.isPending ? "Deleting…" : "Delete"}
          </Btn>
          <Btn variant="ghost" onClick={() => setSelected(new Set())}>Clear</Btn>
          {(bulk.isError || bulkDelete.isError) && <ErrorBanner error={bulk.error ?? bulkDelete.error} />}
        </div>
      )}

      {error && <ErrorBanner error={error} />}
      {isLoading ? (
        <Spinner />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-900 text-left text-xs uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="w-8 px-3 py-2">
                  <input type="checkbox" checked={allPageSelected} onChange={togglePage} className="accent-emerald-500" />
                </th>
                <th className="px-3 py-2">arXiv</th>
                <th className="px-3 py-2">Title</th>
                <th className="px-3 py-2">Submitted</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Category</th>
                <th className="px-3 py-2">Conf.</th>
                <th className="px-3 py-2">PDF</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/60">
              {data?.items.map((p) => (
                <tr key={p.id} className={`hover:bg-zinc-900/60 ${selected.has(p.id) ? "bg-emerald-950/20" : ""}`}>
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} className="accent-emerald-500" />
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-zinc-400">
                    <Link to={`/papers/${p.id}`} className="hover:text-emerald-400">{p.arxiv_id}</Link>
                  </td>
                  <td className="max-w-xl px-3 py-2">
                    <Link to={`/papers/${p.id}`} className="hover:text-emerald-400">{p.title}</Link>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {p.in_gt && (
                        <Badge tone="pink">{p.gt_category ? `GT: ${p.gt_category}` : "GT"}</Badge>
                      )}
                      {p.queries.slice(0, 3).map((qq) => (
                        <Badge key={qq} tone="violet">{qq}</Badge>
                      ))}
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-zinc-400">{p.submitted.slice(0, 10)}</td>
                  <td className="px-3 py-2"><Badge tone={statusTone(p.status)}>{p.status.replaceAll("_", " ")}</Badge></td>
                  <td className="px-3 py-2 text-zinc-300">
                    {p.category === "survey" ? "Survey or Position Paper" : p.category ?? "—"}
                    {p.subcategory ? <span className="text-zinc-500"> / {p.subcategory}</span> : null}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-zinc-400">{p.confidence != null ? p.confidence.toFixed(2) : "—"}</td>
                  <td className="px-3 py-2">
                    <Badge tone={p.pdf_cached ? "green" : "zinc"}>{p.pdf_cached ? "downloaded" : "not cached"}</Badge>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    {p.status !== "screened_excluded" && (
                      <button
                        title="Quick exclude"
                        className="rounded px-1.5 py-0.5 text-xs text-zinc-500 hover:bg-red-950 hover:text-red-400"
                        onClick={() => quickExclude.mutate(p.id)}
                        disabled={quickExclude.isPending}
                      >
                        ✗ exclude
                      </button>
                    )}
                    <button
                      title="Delete paper (DB + cached PDF)"
                      className="ml-1 rounded px-1.5 py-0.5 text-xs text-zinc-500 hover:bg-red-950 hover:text-red-400"
                      onClick={() => confirmDeleteOne(p.id, p.title)}
                      disabled={deleteOne.isPending}
                    >
                      delete
                    </button>
                  </td>
                </tr>
              ))}
              {data && data.items.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-zinc-500">No papers match these filters.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center gap-3">
        <Btn onClick={() => goPage(Math.max(1, page - 1))} disabled={page <= 1}>← Prev</Btn>
        <span className="text-sm text-zinc-400">Page {page} / {pages}</span>
        <Btn onClick={() => goPage(Math.min(pages, page + 1))} disabled={page >= pages}>Next →</Btn>
      </div>
    </div>
  );
}
