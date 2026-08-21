from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SearchClause(BaseModel):
    name: str
    query: str


_SAFETY_WORDS = "(all:safety OR all:safe OR all:safer)"
_LM_TERMS = 'all:"language model" OR all:LLM OR all:MLLM'
_LM = f"({_LM_TERMS})"
_VLM = '(all:"vision-language" OR all:VLM OR all:multimodal OR all:"multi-modal" OR all:LVLM)'
_AGENTS = '(all:agent OR all:agents OR all:agentic OR all:"multi-agent")'
_DETECT = "(all:detection OR all:detector OR all:detecting)"


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
                    ' OR all:"reward tampering"'
                    " OR all:superalignment"
                ),
            ),
            SearchClause(name="safety_lm", query=f"{_SAFETY_WORDS} AND {_LM}"),
            SearchClause(name="safety_vlm", query=f"{_SAFETY_WORDS} AND {_VLM}"),
            SearchClause(name="safety_agents", query=f"{_SAFETY_WORDS} AND {_AGENTS}"),
            SearchClause(
                name="safety_gen_models",
                query=(
                    f"{_SAFETY_WORDS} AND "
                    '(all:diffusion OR all:"text-to-image" OR all:"text-to-video"'
                    ' OR all:"image generation" OR all:"video generation"'
                    ' OR all:embodied OR all:"reasoning model" OR all:deepseek)'
                ),
            ),
            SearchClause(name="alignment_lm", query=f"all:alignment AND {_LM}"),
            SearchClause(
                name="alignment_agents",
                query="all:alignment AND (all:agent OR all:agents OR all:embodied OR all:robotic)",
            ),
            SearchClause(
                name="alignment_values",
                query=(
                    "all:alignment AND (all:value OR all:values OR all:ethics OR all:ethical"
                    " OR all:moral OR all:cultural OR all:culture OR all:personality"
                    ' OR all:"social norm")'
                ),
            ),
            SearchClause(name="weak_to_strong", query='all:"weak-to-strong"'),
            SearchClause(
                name="rlhf_preference",
                query=(
                    "all:RLHF OR all:RLAIF"
                    ' OR all:"reinforcement learning from human feedback"'
                    ' OR all:"direct preference optimization"'
                    ' OR all:"reward model"'
                    ' OR all:"preference optimization"'
                    ' OR all:"preference alignment"'
                ),
            ),
            SearchClause(name="jailbreak", query="all:jailbreak"),
            SearchClause(
                name="red_teaming",
                query='all:"red teaming" OR all:"red-teaming" OR all:"red team"',
            ),
            SearchClause(name="prompt_injection", query='all:"prompt injection"'),
            SearchClause(name="backdoor_attack", query="all:backdoor AND all:attack"),
            SearchClause(
                name="robustness_lm",
                query=f'all:robustness AND ({_LM_TERMS} OR all:"vision-language")',
            ),
            SearchClause(
                name="adversarial_lm",
                query=f"all:adversarial AND ({_LM_TERMS} OR all:\"vision-language\" OR all:multimodal)",
            ),
            SearchClause(
                name="interpretability_lm",
                query=f"all:interpretability AND ({_LM_TERMS} OR all:\"vision-language\" OR all:LVLM)",
            ),
            SearchClause(
                name="mechanistic_interp",
                query='all:"mechanistic interpretability" OR all:"sparse autoencoder"',
            ),
            SearchClause(
                name="explainability_lm",
                query=f'all:explainability AND ({_LM_TERMS} OR all:AI)',
            ),
            SearchClause(
                name="hallucination_lm",
                query=f"all:hallucination AND ({_LM_TERMS} OR all:VLM OR all:LVLM)",
            ),
            SearchClause(
                name="factuality_lm",
                query=f'all:factuality AND ({_LM_TERMS} OR all:"text-to-image")',
            ),
            SearchClause(
                name="unlearning_lm",
                query=f"all:unlearning AND ({_LM_TERMS} OR all:diffusion)",
            ),
            SearchClause(name="watermarking", query="all:watermarking"),
            SearchClause(
                name="aigc_detect",
                query=(
                    f'(all:"AI-generated" AND {_DETECT})'
                    f' OR (all:"generated image" AND {_DETECT})'
                    f' OR (all:"generated text" AND {_DETECT})'
                    " OR all:forgery"
                    ' OR all:"fake video" OR all:"manipulation detection"'
                    ' OR all:"synthetic image"'
                    ' OR (all:"AI-generated" AND all:video)'
                    " OR all:deepfake"
                ),
            ),
            SearchClause(name="trustworthy_lm", query=f"all:trustworthy AND {_LM}"),
            SearchClause(
                name="toxicity_lm",
                query=f'all:toxicity AND ({_LM_TERMS} OR all:agent)',
            ),
            SearchClause(
                name="deception_ai",
                query=(
                    "(all:deception OR all:deceptive) AND "
                    '(all:LLM OR all:"language model" OR all:agent OR all:AI)'
                ),
            ),
            SearchClause(name="sycophancy", query="all:sycophancy"),
            SearchClause(name="guardrail", query="all:guardrail"),
            SearchClause(name="frontier_safety", query="all:frontier AND (all:safety OR all:risk)"),
            SearchClause(name="existential_risk", query="all:existential AND all:AI"),
            SearchClause(name="human_control_ai", query='all:"human control" AND all:AI'),
            SearchClause(
                name="security_llm",
                query=f'all:security AND ({_LM_TERMS} OR all:"large model")',
            ),
            SearchClause(
                name="vulnerability_llm",
                query=f"all:vulnerability AND {_LM}",
            ),
            SearchClause(name="manipulation_ai", query="all:manipulation AND all:AI"),
            SearchClause(name="social_engineering_ai", query='all:"social engineering" AND all:AI'),
            SearchClause(
                name="values_terms",
                query=(
                    'all:"value orientation" OR all:"values judgment"'
                    f' OR all:"social norms" AND ({_LM_TERMS} OR all:agent)'
                ),
            ),
            SearchClause(name="honesty_lm", query=f"all:honesty AND {_LM}"),
            SearchClause(name="tom_lm", query=f'all:"theory of mind" AND {_LM}'),
            SearchClause(name="calibration_lm", query=f"all:calibration AND {_LM}"),
            SearchClause(name="cultural_lm", query=f"all:cultural AND {_LM}"),
            SearchClause(
                name="causal_lm",
                query=f'all:causal AND ({_LM_TERMS} OR all:LRM)',
            ),
            SearchClause(name="transparency_lm", query=f"all:transparency AND {_LM}"),
            SearchClause(
                name="oversight_lm",
                query=f'all:oversight AND ({_LM_TERMS} OR all:AI)',
            ),
            SearchClause(name="bias_agents_llm", query="all:bias AND all:agent AND all:LLM"),
            SearchClause(
                name="rare_phrases",
                query=(
                    'all:"catastrophic inheritance" OR all:"prompt stealing"'
                    ' OR all:"human-like behavior" OR all:"concept bottleneck"'
                    ' OR all:"self-driving laboratory"'
                    ' OR all:"evaluation of large language models"'
                    ' OR all:"self-modification"'
                ),
            ),
            SearchClause(name="white_box_transformer", query='all:"white-box" AND all:transformer'),
            SearchClause(
                name="information_flow_lm",
                query='all:"information flow" AND (all:LVLM OR all:LLM OR all:"language model")',
            ),
            SearchClause(
                name="penetration_testing_llm",
                query='all:"penetration testing" AND (all:LLM OR all:agent)',
            ),
            SearchClause(name="knowledge_editing_align", query='all:"knowledge editing" AND all:alignment'),
            SearchClause(name="sft_alignment", query='all:alignment AND all:"supervised fine-tuning"'),
            SearchClause(name="task_transferability", query='all:"task transferability"'),
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
