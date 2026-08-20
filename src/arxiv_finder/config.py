from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SearchClause(BaseModel):
    name: str
    query: str


class SearchConfig(BaseModel):
    clauses: list[SearchClause] = Field(
        default_factory=lambda: [
            SearchClause(
                name="safety_phrases",
                query=(
                    'all:"AI safety"'
                    ' OR all:"artificial intelligence safety"'
                    ' OR all:"artificial intelligence alignment"'
                    ' OR all:"AI alignment"'
                    ' OR all:"reward hacking"'
                    ' OR all:"reward misspecification"'
                ),
            ),
            SearchClause(name="interpretability_ai", query="all:interpretability AND all:AI"),
            SearchClause(name="explainability_ai", query="all:explainability AND all:AI"),
            SearchClause(name="robustness_ai", query="all:robustness AND all:AI"),
            SearchClause(name="adversarial_ai", query="all:adversarial AND all:AI"),
            SearchClause(name="biological_ai", query="all:biological AND all:AI"),
            SearchClause(name="cyber_ai", query="all:cyber AND all:AI"),
        ]
    )
    page_size: int = 200
    min_interval_sec: float = 3.0
    max_slice_results: int = 4000
    arxiv_base_url: str = "https://export.arxiv.org/api/query"


class ExtractionConfig(BaseModel):
    min_text_chars: int = 150
    max_first_page_chars: int = 7000
    vision_fallback: bool = True
    concurrency: int = 50
    pdf_concurrency: int = 8


class ChinaFilterConfig(BaseModel):
    min_count: int = 1
    min_fraction: float = 0.0
    anchor_rule: bool = False
    anchor_last_n_small: int = 2
    anchor_last_n_large: int = 3
    anchor_small_author_cutoff: int = 5


class ScreenConfig(BaseModel):
    escalate_below: float = 0.6
    review_below: float = 0.5
    fulltext_page_limit: int = 15
    fulltext_max_chars: int = 60000
    double_judge: bool = False
    concurrency: int = 50


class ModelsConfig(BaseModel):
    extraction: str = "qwen3.8-max"
    screen_cheap: str = "qwen3.8-max"
    screen_strong: str = "qwen3.8-max"


class LLMClientConfig(BaseModel):
    base_url: str = ""
    api_key_env: str = "LLM_API_KEY"
    timeout_sec: float = 180.0
    max_retries: int = 4


class AppConfig(BaseModel):
    search: SearchConfig = Field(default_factory=SearchConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    china_filter: ChinaFilterConfig = Field(default_factory=ChinaFilterConfig)
    screen: ScreenConfig = Field(default_factory=ScreenConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    llm: LLMClientConfig = Field(default_factory=LLMClientConfig)

    @model_validator(mode="after")
    def _validate_ranges(self) -> AppConfig:
        if not self.search.clauses:
            raise ValueError("search.clauses must not be empty")
        if self.extraction.concurrency < 1 or self.extraction.pdf_concurrency < 1:
            raise ValueError("extraction concurrency values must be >= 1")
        if self.screen.concurrency < 1:
            raise ValueError("screen.concurrency must be >= 1")
        seen: set[str] = set()
        for clause in self.search.clauses:
            if clause.name in seen:
                raise ValueError(f"duplicate clause name: {clause.name}")
            seen.add(clause.name)
            if not clause.query.strip():
                raise ValueError(f"clause {clause.name} has empty query")
        cf = self.china_filter
        if cf.min_count < 0:
            raise ValueError("china_filter.min_count must be >= 0")
        if not 0.0 <= cf.min_fraction <= 1.0:
            raise ValueError("china_filter.min_fraction must be within [0, 1]")
        if not 0.0 <= self.screen.escalate_below <= 1.0:
            raise ValueError("screen.escalate_below must be within [0, 1]")
        if not 0.0 <= self.screen.review_below <= 1.0:
            raise ValueError("screen.review_below must be within [0, 1]")
        if self.screen.review_below > self.screen.escalate_below:
            raise ValueError("screen.review_below must be <= screen.escalate_below")
        return self


def default_config() -> AppConfig:
    return AppConfig()
