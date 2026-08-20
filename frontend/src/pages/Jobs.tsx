import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AppConfig } from "../api";
import ConfigEditor from "../components/ConfigEditor";
import { Badge, Btn, Card, ErrorBanner, Field, Input, Select, Spinner } from "../ui";

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthAgoISO(): string {
  const d = new Date();
  d.setMonth(d.getMonth() - 1);
  return d.toISOString().slice(0, 10);
}

function kindTone(status: string): string {
  if (status === "done") return "green";
  if (status === "running") return "blue";
  if (status === "failed") return "red";
  if (status === "cancelled") return "amber";
  return "zinc";
}

function RunPanel() {
  const qc = useQueryClient();
  const { data: cfgData, isLoading: cfgLoading, error: cfgError } = useQuery({
    queryKey: ["config"],
    queryFn: api.config,
  });
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [dateFrom, setDateFrom] = useState(monthAgoISO());
  const [dateTo, setDateTo] = useState(todayISO());
  const [model, setModel] = useState<string>("");
  const [modelOverride, setModelOverride] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const modelsQ = useQuery({ queryKey: ["models"], queryFn: api.models, retry: false });

  const current = cfg ?? cfgData?.config ?? null;
  const dirty = cfg != null && cfgData != null && JSON.stringify(cfg) !== JSON.stringify(cfgData.config);
  const effectiveModel = modelOverride ? model : current?.models.extraction ?? "";

  const run = useMutation({
    mutationFn: async () => {
      if (!dateFrom || !dateTo) throw new Error("both dates are required");
      if (dateFrom > dateTo) throw new Error("date-from must be before date-to");
      if (cfg != null && dirty) {
        await api.saveConfig(cfg, "updated from run panel");
        qc.invalidateQueries({ queryKey: ["config"] });
        qc.invalidateQueries({ queryKey: ["configVersions"] });
      }
      const params: Record<string, unknown> = { date_from: dateFrom, date_to: dateTo };
      if (effectiveModel) params.model = effectiveModel;
      return api.createJob("pipeline", params);
    },
    onSuccess: (res) => {
      setMsg(`Pipeline job #${res.job_id} queued — it runs fetch → affiliations → screen.`);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  if (cfgLoading) return <Spinner />;
  if (cfgError || !current) return <ErrorBanner error={cfgError ?? new Error("config unavailable")} />;

  return (
    <Card title="Run pipeline (fetch → affiliations → screen)">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="From">
          <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </Field>
        <Field label="To (inclusive)">
          <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </Field>
        <Field label="Model">
          {!modelOverride && modelsQ.data?.models && modelsQ.data.models.length > 0 ? (
            <div className="flex items-center gap-2">
              <Select value={effectiveModel} onChange={(e) => setModel(e.target.value)}>
                {!modelsQ.data.models.includes(current.models.extraction) && (
                  <option value={current.models.extraction}>{current.models.extraction}</option>
                )}
                {modelsQ.data.models.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </Select>
              <button className="text-xs text-zinc-500 hover:text-zinc-300" onClick={() => { setModelOverride(true); setModel(effectiveModel); }}>
                custom
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Input
                value={effectiveModel}
                placeholder="model name, e.g. qwen3.8-max"
                onChange={(e) => { setModelOverride(true); setModel(e.target.value); }}
                className="w-72"
              />
              {!modelsQ.isLoading && modelsQ.isError && (
                <span className="text-xs text-zinc-600" title={modelsQ.error instanceof Error ? modelsQ.error.message : ""}>
                  (model list unavailable)
                </span>
              )}
            </div>
          )}
        </Field>
        <Btn variant="primary" onClick={() => run.mutate()} disabled={run.isPending || !dateFrom || !dateTo}>
          {run.isPending ? "Queuing…" : "Run"}
        </Btn>
      </div>
      {dirty && (
        <p className="mt-2 text-xs text-amber-400">
          Unsaved config changes below will be saved automatically when you press Run.
        </p>
      )}
      {run.isError && <div className="mt-2"><ErrorBanner error={run.error} /></div>}
      {msg && <p className="mt-2 text-sm text-emerald-400">{msg}</p>}

      <div className="mt-4">
        <ConfigEditor config={current} onChange={(next) => setCfg(next)} />
      </div>
    </Card>
  );
}

function JobRow({ job }: { job: { id: number; kind: string; status: string; created_at: string; error: string | null; params?: Record<string, unknown>; progress?: { done: number; total: number; current: string } | null; log_tail: string | null } }) {
  const qc = useQueryClient();
  const [showLog, setShowLog] = useState(false);
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(job.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });

  const progress = job.progress;
  const pct = progress && progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : null;
  const params = job.params ?? {};
  const desc =
    job.kind === "pipeline" || job.kind === "fetch"
      ? `${params.date_from ?? ""}`.slice(0, 10) + " → " + `${params.date_to ?? ""}`.slice(0, 10) + (params.model ? ` · ${params.model}` : "")
      : JSON.stringify(params);

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
      <div className="flex items-center gap-3">
        <span className="w-10 font-mono text-xs text-zinc-500">#{job.id}</span>
        <Badge tone="violet">{job.kind}</Badge>
        <Badge tone={kindTone(job.status)}>{job.status}</Badge>
        <span className="truncate text-xs text-zinc-500">{desc}</span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-zinc-500">{job.created_at.replace("T", " ").replace("+00:00", "")}</span>
          {(job.status === "queued" || job.status === "running") && (
            <Btn variant="danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>Cancel</Btn>
          )}
        </div>
      </div>

      {pct != null && (
        <div className="mt-2 flex items-center gap-2">
          <div className="h-2 flex-1 overflow-hidden rounded bg-zinc-800">
            <div className="h-full bg-sky-600 transition-all" style={{ width: `${pct}%` }} />
          </div>
          <span className="w-24 text-right text-xs tabular-nums text-zinc-400">
            {progress!.done}/{progress!.total}
          </span>
        </div>
      )}
      {progress?.current && <div className="mt-1 truncate text-xs text-zinc-500">{progress.current}</div>}
      {job.error && <div className="mt-1 text-xs text-red-400">{job.error}</div>}

      {job.log_tail && (
        <div className="mt-2">
          <button className="text-xs text-zinc-500 hover:text-zinc-300" onClick={() => setShowLog(!showLog)}>
            {showLog ? "hide log" : "show log"}
          </button>
          {showLog && (
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-zinc-950 p-2 text-[11px] leading-relaxed text-zinc-400">
              {job.log_tail}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

export default function Jobs() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs,
    refetchInterval: 3000,
  });

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Jobs</h1>
      <RunPanel />
      <h2 className="mt-2 text-sm font-semibold uppercase tracking-wider text-zinc-400">History</h2>
      {error && <ErrorBanner error={error} />}
      {isLoading ? (
        <Spinner />
      ) : data && data.items.length === 0 ? (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-8 text-center text-zinc-500">No jobs yet.</div>
      ) : (
        <div className="flex flex-col gap-2">
          {data?.items.map((job) => <JobRow key={job.id} job={job} />)}
        </div>
      )}
    </div>
  );
}
