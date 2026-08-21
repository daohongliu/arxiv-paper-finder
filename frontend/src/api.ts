export interface PaperSummary {
  id: number;
  arxiv_id: string;
  title: string;
  submitted: string;
  status: string;
  category: string | null;
  subcategory: string | null;
  confidence: number | null;
  china_flag: number;
  primary_category: string | null;
  queries: string[];
  abs_url: string;
  pdf_cached: boolean;
}

export interface AffiliationAuthor {
  name: string;
  institution: string;
  country: string;
  mainland_china: "yes" | "no" | "unclear";
}

export interface PaperDetail extends PaperSummary {
  version: number;
  abstract: string;
  authors: string[];
  categories: string[];
  updated: string;
  pdf_url: string;
  comments: string | null;
  rationale: string | null;
  affiliations: {
    model: string;
    method: string;
    status: string;
    authors: AffiliationAuthor[];
    likely_mainland_china: string | null;
    error: string | null;
    created_at: string;
  } | null;
  llm_calls: {
    stage: string;
    model: string;
    request_summary: string;
    response_text: string;
    input_tokens: number | null;
    output_tokens: number | null;
    latency_ms: number | null;
    created_at: string;
  }[];
  labels: {
    source: string;
    included: number;
    category: string | null;
    subcategory: string | null;
    note: string | null;
    created_at: string;
  }[];
}

export interface PaperListResponse {
  total: number;
  page: number;
  page_size: number;
  items: PaperSummary[];
}

export interface Job {
  id: number;
  kind: string;
  params_json: string;
  config_version_id: number | null;
  status: string;
  progress_json: string | null;
  log_tail: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  params?: Record<string, unknown>;
  progress?: { done: number; total: number; current: string } | null;
}

export interface Stats {
  papers_total: number;
  by_status: Record<string, number>;
  by_category: { category: string; subcategory: string | null; n: number }[];
  included_monthly: { month: string; n: number }[];
  llm: { calls: number; input_tokens: number; output_tokens: number };
  active_jobs: number;
}

export interface SearchClause {
  name: string;
  query: string;
}

export interface AppConfig {
  search: {
    clauses: SearchClause[];
    page_size: number;
    min_interval_sec: number;
    max_slice_results: number;
    arxiv_base_url: string;
  };
  extraction: {
    min_text_chars: number;
    max_first_page_chars: number;
    vision_fallback: boolean;
    concurrency: number;
    pdf_concurrency: number;
  };
  china_filter: {
    min_count: number;
    min_fraction: number;
    anchor_rule: boolean;
    anchor_last_n_small: number;
    anchor_last_n_large: number;
    anchor_small_author_cutoff: number;
  };
  screen: {
    escalate_below: number;
    review_below: number;
    fulltext_page_limit: number;
    fulltext_max_chars: number;
    double_judge: boolean;
    concurrency: number;
  };
  models: { extraction: string; screen_cheap: string; screen_strong: string };
  llm: { base_url: string; api_key_env: string; timeout_sec: number; max_retries: number };
}

export interface PromptItem {
  name: string;
  version: number;
  version_id: number;
  text: string;
  created_at: string;
}

export interface EvalReport {
  total_gt: number;
  included: number;
  recovery: number;
  dropped_at: Record<string, string[]>;
  category_accuracy: number | null;
  category_matrix: Record<string, Record<string, number>>;
  rows_parsed?: number;
  saved_to?: string;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: init?.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // ignore body parse errors
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  papers: (params: Record<string, string | number | boolean | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== null) qs.set(k, String(v));
    });
    return request<PaperListResponse>(`/api/papers?${qs.toString()}`);
  },
  paper: (id: number) => request<PaperDetail>(`/api/papers/${id}`),
  review: (id: number, body: { included: boolean; category?: string | null; subcategory?: string | null; note?: string }) =>
    request<{ ok: boolean; status: string }>(`/api/papers/${id}/review`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  bulkReview: (ids: number[], body: { included: boolean; category?: string | null; subcategory?: string | null; note?: string }) =>
    request<{ ok: boolean; updated: number }>(`/api/papers/bulk-review`, {
      method: "POST",
      body: JSON.stringify({ ids, ...body }),
    }),
  deletePaper: (id: number) =>
    request<{ ok: boolean; pdf_removed: boolean }>(`/api/papers/${id}`, { method: "DELETE" }),
  bulkDelete: (ids: number[]) =>
    request<{ ok: boolean; deleted: number; pdfs_removed: number }>(`/api/papers/bulk-delete`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  exportCsvUrl: (dateFrom?: string, dateTo?: string) => {
    const qs = new URLSearchParams();
    if (dateFrom) qs.set("date_from", dateFrom);
    if (dateTo) qs.set("date_to", dateTo);
    return `/api/export?${qs.toString()}`;
  },

  jobs: () => request<{ items: Job[] }>(`/api/jobs`),
  job: (id: number) => request<Job>(`/api/jobs/${id}`),
  createJob: (kind: string, params: Record<string, unknown>) =>
    request<{ job_id: number }>(`/api/jobs`, { method: "POST", body: JSON.stringify({ kind, params }) }),
  cancelJob: (id: number) => request<{ ok: boolean }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  pauseJob: (id: number) => request<{ ok: boolean }>(`/api/jobs/${id}/pause`, { method: "POST" }),
  resumeJob: (id: number) => request<{ ok: boolean }>(`/api/jobs/${id}/resume`, { method: "POST" }),
  models: () => request<{ models: string[] }>(`/api/models`),

  config: () => request<{ version_id: number; config: AppConfig }>(`/api/config`),
  saveConfig: (config: AppConfig, note: string) =>
    request<{ version_id: number }>(`/api/config`, { method: "PUT", body: JSON.stringify({ config, note }) }),
  configVersions: () => request<{ items: { id: number; created_at: string; note: string | null }[] }>(`/api/config/versions`),
  rollbackConfig: (id: number) => request<{ version_id: number }>(`/api/config/rollback/${id}`, { method: "POST" }),

  prompts: () => request<{ items: PromptItem[] }>(`/api/prompts`),
  savePrompt: (name: string, text: string) =>
    request<{ version_id: number }>(`/api/prompts/${name}`, { method: "PUT", body: JSON.stringify({ text }) }),

  stats: () => request<Stats>(`/api/stats`),

  importLabels: async (file: File): Promise<EvalReport> => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/labels/import", { method: "POST", body: fd });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
    }
    return res.json();
  },
};
