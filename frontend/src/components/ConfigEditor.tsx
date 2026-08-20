import type { ReactNode } from "react";
import type { AppConfig } from "../api";
import { Btn, Card, Field, Input } from "../ui";

function Num({ value, onChange, step = 1, min }: { value: number; onChange: (v: number) => void; step?: number; min?: number }) {
  return (
    <Input
      type="number"
      step={step}
      min={min}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-28"
    />
  );
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={`relative h-6 w-11 rounded-full transition-colors ${value ? "bg-emerald-600" : "bg-zinc-700"}`}
    >
      <span
        className="absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all"
        style={{ left: value ? "22px" : "2px" }}
      />
    </button>
  );
}

function Tip({ text }: { text: string }) {
  return (
    <span className="group relative ml-1 inline-flex align-middle">
      <span className="cursor-help select-none text-zinc-600 hover:text-zinc-300" title="">ⓘ</span>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 hidden w-64 -translate-x-1/2 rounded-lg border border-zinc-700 bg-zinc-900 p-2 text-[11px] font-normal normal-case leading-snug tracking-normal text-zinc-300 shadow-xl group-hover:block">
        {text}
      </span>
    </span>
  );
}

function L({ text, tip }: { text: string; tip: string }): ReactNode {
  return (
    <span className="inline-flex items-center">
      {text}
      <Tip text={tip} />
    </span>
  );
}

export default function ConfigEditor({
  config,
  onChange,
}: {
  config: AppConfig;
  onChange: (cfg: AppConfig) => void;
}) {
  const upd = <K extends keyof AppConfig>(section: K, patch: Partial<AppConfig[K]>) =>
    onChange({ ...config, [section]: { ...config[section], ...patch } });

  const updClause = (i: number, field: "name" | "query", value: string) => {
    const clauses = config.search.clauses.map((c, idx) => (idx === i ? { ...c, [field]: value } : c));
    onChange({ ...config, search: { ...config.search, clauses } });
  };

  const addClause = () =>
    onChange({ ...config, search: { ...config.search, clauses: [...config.search.clauses, { name: "new_clause", query: "" }] } });

  const removeClause = (i: number) =>
    onChange({ ...config, search: { ...config.search, clauses: config.search.clauses.filter((_c, idx) => idx !== i) } });

  return (
    <div className="flex flex-col gap-4">
      <Card title="Search keywords">
        <p className="mb-2 text-xs text-zinc-500">
          Each clause is an arXiv query fragment over the <code>all:</code> field; they are OR-combined and
          AND-combined with the date window. Example: <code>all:"AI safety"</code> or{" "}
          <code>all:interpretability AND all:AI</code>
        </p>
        <div className="flex flex-col gap-2">
          {config.search.clauses.map((c, i) => (
            <div key={i} className="flex gap-2">
              <Input value={c.name} onChange={(e) => updClause(i, "name", e.target.value)} className="w-44" />
              <Input value={c.query} onChange={(e) => updClause(i, "query", e.target.value)} className="flex-1 font-mono text-xs" />
              <Btn variant="ghost" onClick={() => removeClause(i)} disabled={config.search.clauses.length <= 1}>
                ✕
              </Btn>
            </div>
          ))}
        </div>
        <div className="mt-2">
          <Btn onClick={addClause}>+ Add keyword clause</Btn>
        </div>
      </Card>

      <details className="rounded-xl border border-zinc-800 bg-zinc-900/60">
        <summary className="cursor-pointer select-none p-4 text-sm font-semibold uppercase tracking-wider text-zinc-400">
          Advanced settings
        </summary>
        <div className="flex flex-col gap-4 px-4 pb-4">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Affiliation extraction</h3>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <Field label={<L text="Min text chars" tip="How much text must be extracted from the PDF's first page before it is considered readable. Below this, the vision fallback kicks in (the page is rendered as an image and sent to the model instead)." />}>
                <Num value={config.extraction.min_text_chars} onChange={(v) => upd("extraction", { min_text_chars: v })} min={0} />
              </Field>
              <Field label={<L text="Max first-page chars" tip="Character cap on the first-page text sent to the LLM for affiliation extraction. Affiliations live in the paper header, so the rest of the page is not needed; the cap keeps token cost down." />}>
                <Num value={config.extraction.max_first_page_chars} onChange={(v) => upd("extraction", { max_first_page_chars: v })} min={0} />
              </Field>
              <Field label={<L text="LLM concurrency" tip="Maximum number of affiliation-extraction LLM calls running in parallel. Higher is faster but puts more load on the LLM endpoint (and may hit rate limits)." />}>
                <Num value={config.extraction.concurrency} onChange={(v) => upd("extraction", { concurrency: v })} min={1} />
              </Field>
              <Field label={<L text="PDF download concurrency" tip="Maximum number of arXiv PDF downloads running in parallel. Keep this modest to stay polite to arXiv's servers." />}>
                <Num value={config.extraction.pdf_concurrency} onChange={(v) => upd("extraction", { pdf_concurrency: v })} min={1} />
              </Field>
              <Field label={<L text="Vision fallback" tip="If the first page yields too little text (e.g. unusual layouts), render it as an image and let the model read affiliations visually. Disable to use text extraction only." />}>
                <Toggle value={config.extraction.vision_fallback} onChange={(v) => upd("extraction", { vision_fallback: v })} />
              </Field>
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">China-affiliation rule</h3>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
              <Field label={<L text="Min mainland count" tip="Minimum number of authors with a mainland-China institution required for a paper to pass this filter. Default 1: any mainland-affiliated author passes." />}>
                <Num value={config.china_filter.min_count} onChange={(v) => upd("china_filter", { min_count: v })} min={0} />
              </Field>
              <Field label={<L text="Min fraction" tip="Additionally required share of mainland-affiliated authors among all authors (0 disables). E.g. 0.33 with count 2 enforces the original paper's '2+ AND 33%+' rule." />}>
                <Num value={config.china_filter.min_fraction} onChange={(v) => upd("china_filter", { min_fraction: v })} step={0.05} min={0} />
              </Field>
              <Field label={<L text="Anchor rule" tip="Also pass a paper if one of its 'anchor' authors (the last N listed — usually senior/corresponding authors) is mainland-affiliated, even if the count/fraction rule fails." />}>
                <Toggle value={config.china_filter.anchor_rule} onChange={(v) => upd("china_filter", { anchor_rule: v })} />
              </Field>
              <Field label={<L text="Anchor n (small)" tip="How many of the last-listed authors count as anchors on small papers (author count at or below the cutoff). Original procedure: last 2–3 authors." />}>
                <Num value={config.china_filter.anchor_last_n_small} onChange={(v) => upd("china_filter", { anchor_last_n_small: v })} min={0} />
              </Field>
              <Field label={<L text="Anchor n (large)" tip="How many of the last-listed authors count as anchors on large papers (author count above the cutoff)." />}>
                <Num value={config.china_filter.anchor_last_n_large} onChange={(v) => upd("china_filter", { anchor_last_n_large: v })} min={0} />
              </Field>
              <Field label={<L text="Small-author cutoff" tip="Author-count threshold separating 'small' from 'large' papers for anchor selection (≤ cutoff uses Anchor n small, > uses Anchor n large)." />}>
                <Num value={config.china_filter.anchor_small_author_cutoff} onChange={(v) => upd("china_filter", { anchor_small_author_cutoff: v })} min={0} />
              </Field>
            </div>
            <p className="mt-1 text-xs text-zinc-600">Default (min count 1, fraction 0): any mainland-affiliated author passes.</p>
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">Screening & classification</h3>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
              <Field label={<L text="Escalate below" tip="If the model's confidence in its include/exclude decision on the abstract is below this, the paper is escalated: the full text is extracted and screened again with the strong model." />}>
                <Num value={config.screen.escalate_below} onChange={(v) => upd("screen", { escalate_below: v })} step={0.05} min={0} />
              </Field>
              <Field label={<L text="Review below" tip="After full-text escalation, if confidence is still below this, the paper goes to the human Review queue instead of being decided automatically." />}>
                <Num value={config.screen.review_below} onChange={(v) => upd("screen", { review_below: v })} step={0.05} min={0} />
              </Field>
              <Field label={<L text="Fulltext pages" tip="How many pages of the PDF are extracted for full-text screening. More pages = more context = more tokens." />}>
                <Num value={config.screen.fulltext_page_limit} onChange={(v) => upd("screen", { fulltext_page_limit: v })} min={1} />
              </Field>
              <Field label={<L text="Fulltext max chars" tip="Hard character cap on the full text sent to the model during escalation, regardless of page count." />}>
                <Num value={config.screen.fulltext_max_chars} onChange={(v) => upd("screen", { fulltext_max_chars: v })} min={1000} />
              </Field>
              <Field label={<L text="LLM concurrency" tip="Maximum number of screening LLM calls running in parallel." />}>
                <Num value={config.screen.concurrency} onChange={(v) => upd("screen", { concurrency: v })} min={1} />
              </Field>
              <Field label={<L text="Double judge" tip="Run a second independent screening call on abstracts; if the two judgments disagree, confidence is lowered (pushing borderline cases to review). Roughly doubles screening calls." />}>
                <Toggle value={config.screen.double_judge} onChange={(v) => upd("screen", { double_judge: v })} />
              </Field>
            </div>
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">LLM endpoint & default models</h3>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label={<L text="Base URL" tip="OpenAI-compatible endpoint used for LLM calls. Leave empty to use the LLM_BASE_URL environment variable (currently loaded from .env)." />}>
                <Input value={config.llm.base_url} onChange={(e) => upd("llm", { base_url: e.target.value })} />
              </Field>
              <Field label={<L text="API key env var" tip="Name of the environment variable that holds the API key. The key itself is never stored in the database or shown here." />}>
                <Input value={config.llm.api_key_env} onChange={(e) => upd("llm", { api_key_env: e.target.value })} />
              </Field>
              <Field label={<L text="Timeout" tip="Per-request timeout (seconds) for LLM calls. Long full-text calls may need a generous timeout." />}>
                <Num value={config.llm.timeout_sec} onChange={(v) => upd("llm", { timeout_sec: v })} min={1} />
              </Field>
              <Field label={<L text="Max retries" tip="How many times a failed LLM request is retried (rate limits / server errors), with exponential backoff between attempts." />}>
                <Num value={config.llm.max_retries} onChange={(v) => upd("llm", { max_retries: v })} min={0} />
              </Field>
              <Field label={<L text="Default extraction model" tip="Model used for affiliation extraction when no model is picked on the run itself." />}>
                <Input value={config.models.extraction} onChange={(e) => upd("models", { extraction: e.target.value })} />
              </Field>
              <Field label={<L text="Default screen (cheap)" tip="Model used for the abstract-level frontier-AI-safety screening." />}>
                <Input value={config.models.screen_cheap} onChange={(e) => upd("models", { screen_cheap: e.target.value })} />
              </Field>
              <Field label={<L text="Default screen (strong)" tip="Model used for full-text escalation screening." />}>
                <Input value={config.models.screen_strong} onChange={(e) => upd("models", { screen_strong: e.target.value })} />
              </Field>
            </div>
            <p className="mt-1 text-xs text-zinc-600">The model picker on a run overrides these for that run.</p>
          </div>

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">arXiv API</h3>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label={<L text="Page size" tip="How many results to request per arXiv API page. Larger = fewer requests, but arXiv recommends ≤ 200." />}>
                <Num value={config.search.page_size} onChange={(v) => upd("search", { page_size: v })} min={1} />
              </Field>
              <Field label={<L text="Min interval (sec)" tip="Minimum pause between arXiv API requests. arXiv asks for ≥ 3 seconds; going lower risks rate limiting." />}>
                <Num value={config.search.min_interval_sec} onChange={(v) => upd("search", { min_interval_sec: v })} step={0.5} min={0} />
              </Field>
              <Field label={<L text="Max slice results" tip="Safety cap on results processed per clause per month-slice, to avoid runaway queries." />}>
                <Num value={config.search.max_slice_results} onChange={(v) => upd("search", { max_slice_results: v })} min={1} />
              </Field>
              <Field label={<L text="arXiv base URL" tip="The arXiv export API endpoint. Only change if you run a mirror." />}>
                <Input value={config.search.arxiv_base_url} onChange={(e) => upd("search", { arxiv_base_url: e.target.value })} />
              </Field>
            </div>
          </div>
        </div>
      </details>
    </div>
  );
}
