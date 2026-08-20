# arXiv AI-Safety Paper Finder

Automates the construction of a dataset of **frontier AI-safety papers with Chinese-institution
contributions**, replacing a previously manual procedure. It searches arXiv for a configurable set
of keyword clauses, extracts author affiliations from PDFs with an LLM, applies a mainland-China
affiliation rule, screens each paper for "frontier AI safety" and categorizes it (alignment /
robustness / monitoring{interpretability, evaluations, other} / systemic safety), and exports the
result in the dataset's target CSV format.

## Pipeline

```
arXiv API (keyword clauses × date window)
   → papers.fetched
LLM affiliation extraction from PDF first pages (vision fallback) + mainland-China rule
   → papers.affiliated / filtered_out / unresolved
LLM frontier-AI-safety screening (abstract → full-text escalation → human review)
   → screened_included / screened_excluded / needs_review
Export (target CSV format, date-filtered)
```

Every stage's LLM decisions are auditable per paper (full call history in the UI), low-confidence
papers land in a human Review queue, and manual verdicts override the LLM.

## Requirements

- Python ≥ 3.13, [uv](https://github.com/astral-sh/uv), Node ≥ 20 (only to rebuild the frontend)
- An OpenAI-compatible LLM endpoint (configured via `.env`)

## Setup

```bash
uv sync                       # backend deps
cat > .env <<'EOF'
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_API_KEY=...
EOF
uv run arxiv-finder init      # create SQLite DB + seed config/prompts
```

## Running

```bash
uv run arxiv-finder worker &  # executes queued jobs
uv run arxiv-finder serve     # web UI + API at http://127.0.0.1:8000
```

**Web UI:**
- **Jobs** — pick a date range, pick the LLM model, edit search keyword clauses (advanced settings
  cover thresholds, concurrency, rules — all with tooltips), press **Run**. One job runs
  fetch → affiliations → screen end to end.
- **Papers** — filter/search, mark papers included/excluded (bulk or per row), delete papers
  (DB + cached PDF), see PDF cache status, export the target-format CSV for a date range.
- **Review** — adjudicate low-confidence and failed papers.
- **Dashboard** — funnel stats, category breakdown, token usage.
- **Eval** — upload a human-labeled ground-truth CSV and see recovery, per-stage drop-off, and
  category confusion.

CLI equivalents: `fetch`, `affiliations`, `screen`, `export`, `review-export`, `eval`, `stats`.

## Development

```bash
uv run pytest                 # backend tests
uv run ruff check src tests   # lint
uv run mypy src               # typecheck
cd frontend && npm install && npm run build   # rebuild UI (served by FastAPI from frontend/dist)
```

Data lives in `data/` (SQLite DB + PDF cache); `.env` and `data/` are gitignored.
