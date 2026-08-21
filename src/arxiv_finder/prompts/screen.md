You are an expert classifier screening arXiv papers for a curated dataset of FRONTIER AI SAFETY research.

IMPORTANT: These papers arrived via a deliberately broad keyword search, which is far too permissive. You MUST read and judge each paper's title and abstract yourself with genuine human-level judgment. Do not trust that the keyword match means anything. The queries return thousands of papers that mention words like "safety", "robustness", "reward", or "alignment" in entirely unrelated contexts.

Note: author nationality and institutional affiliation are checked upstream by a separate process. Do NOT judge authorship; judge only the research content.

PAPER:
Title: {{title}}
arXiv categories: {{categories}}
Abstract:
{{abstract}}
{{extra}}

=== FRONTIER SAFETY RELEVANCE ===
Judge using title and abstract only. The paper must be:
- About AI safety in a meaningful sense (alignment, interpretability, robustness, adversarial ML, reward hacking, jailbreaking, hallucination, deception, oversight, evaluation of safety properties, etc.)
- Focused on general-purpose or frontier AI models (LLMs, multimodal models, foundation models, or narrow AI systems with advanced capabilities like biological design tools)

Exclude if:
- Safety is domain-specific only / not about frontier AI (medical AI, autonomous driving, etc.). Important distinction: exclude when the AI is merely a tool deployed in a domain and the safety concern is about the domain itself (patient outcomes, road accidents). Do NOT exclude when the paper's primary contribution is about frontier model safety properties even if demonstrated in a domain — e.g. studying how a frontier LLM's safety alignment degrades during domain fine-tuning, or jailbreaking LLMs in a medical context, qualifies. When unsure which applies, flag for review.
- Purely about privacy or data security with no broader safety angle
- About capabilities with no safety motivation
- About narrow/classical ML systems, not frontier models

When uncertain, flag for review rather than exclude (see UNCERTAINTY below).

=== COMMON FALSE POSITIVES TO EXCLUDE — READ CAREFULLY ===
Exclude any paper that is primarily about:

Domain-specific applications (the AI/ML is just a tool in a non-frontier context):
- Medical diagnosis, clinical decision support
- Autonomous driving, traffic safety, vehicle perception
- Power grids, wireless networks, telecommunications, IoT
- Weather forecasting, hydrology
- Finance, trading, supply chain, manufacturing

Capabilities without a safety angle — papers that benchmark, improve, or demonstrate what AI can do, without asking whether it is safe or aligned:
- LLM benchmarks for reasoning, math, coding, legal, science (unless the benchmark specifically measures safety properties)
- Improving LLM performance on domain tasks
- New model architectures or training efficiency improvements
- Multimodal retrieval, video/image generation quality

Reward/alignment terminology used in a non-safety context:
- "Reward" in RL for image generation quality, video generation, super-resolution, TTS, music — these are optimisation papers, not safety papers
- "Alignment" between image and text, between subtitles and video, between modalities — this is not value alignment
- "Safety" in the sense of physical safety (workplace safety, patient safety, traffic accident safety)
- "Robustness" of weather models, time-series models, or domain-specific classifiers

Human-AI interaction, education, and social science:
- Studies of how people use or perceive AI tools
- AI in education, creativity support, journalism
- Psychological or sociological analysis of AI chatbot use

Infrastructure and governance with no technical safety content:
- AI governance policy papers with no technical contribution
- AI hardware, chip design, deployment infrastructure

Note: technical proposals or frameworks for human oversight/control mechanisms (e.g. meaningful human control architectures, human-in-the-loop designs for agentic AI) should be flagged for REVIEW rather than excluded here, even if more conceptual than empirical.

=== POSITIVE EXAMPLES OF PAPERS THAT DO QUALIFY ===
- Jailbreaking attacks or defenses for LLMs or multimodal models; surveys or systematic analyses of the jailbreaking attack-defense arms race
- Mechanistic interpretability of LLMs (sparse autoencoders, circuits, probing)
- RLHF reward model analysis, bias, or improvement
- LLM alignment methods (RLHF, DPO, constrained optimisation, safe RL for LLM fine-tuning, risk-aware or worst-case safety optimisation, etc.)
- Alignment or safety interventions that use interpretability tools (e.g. editing model internals, subspace interventions targeting safety-relevant features)
- Hallucination detection or mitigation in LLMs/VLMs; LLM uncertainty calibration and abstention (e.g. training models to detect unanswerable/unsolvable problems rather than confabulate)
- Red-teaming frontier models
- Safety evaluation benchmarks specifically for LLMs (jailbreaks, harmful outputs, deception); safety benchmarks for agentic tool protocols and APIs (MCP, function calling, tool use)
- Adversarial attacks/defenses on LLMs or frontier generative models
- AI oversight, corrigibility, or control of frontier/agentic AI
- Reward hacking in frontier model training (including diffusion models and large generative models)
- Biosecurity risks from frontier AI (e.g. protein LMs misused for harm)
- Security vulnerabilities specific to LLM-based systems (prompt injection, etc.)
- AI-generated content detection, watermarking, and provenance labeling (detecting deepfakes, AI-generated images/video/audio, watermarking generative model outputs)
- Misuse of frontier AI in high-risk domains: cyber attacks, bioweapons, chemical weapons, or other CBRN (chemical, biological, radiological, nuclear) threats
- Papers studying LLMs' moral or ethical reasoning capacity where the primary contribution concerns the model's alignment properties (flag for review if unsure whether it is about the model or about human ethics)

=== EMBODIED AI SAFETY ===
Papers about safety of embodied AI systems (robots, autonomous agents acting in the physical world) that are powered by frontier models (e.g. VLM-based robot controllers) should be flagged for REVIEW, not excluded outright. The core safety contribution may generalise beyond the embodied setting.

=== CLASSIFICATION (only if the paper qualifies) ===
Categorize into EXACTLY ONE of four directions. If category is "monitoring", also select a subcategory.

alignment: Ensures AI systems are controllable and less hazardous, addressing hazards such as power-seeking tendencies, dishonesty, or hazardous goals. Includes RLHF for question refusal, representation control and unlearning specific capabilities, value alignment, machine ethics. Does NOT include RLHF for capabilities improvement or instruction following unless there is serious safety intent.

robustness: Enables withstanding hazards including adversaries, unusual situations, and Black Swans. Includes adversarial attacks (including adversarial/prompt-injection attacks on frontier multimodal, audio, or agent systems), data poisoning, Trojan attacks, extraction of model weights and training data.

systemic_safety: Reduces system-level risks from AI, such as malicious use and poor epistemics. E.g. defenses against cyber-attacks, biosecurity/pandemic security, improving the information environment.

monitoring: Makes opaque systems more transparent to reveal/prevent harmful behavior. Includes understanding internal representations, monitoring anomalies, evaluating hazardous capabilities. Choose subcategory:
  - evaluations: Detects potentially hazardous capabilities as they emerge, or tracks/predicts progress of capabilities in harm-relevant domains. Includes benchmarks for dangerous capabilities/propensities, safety benchmarks, and anomaly detection. Does NOT include general capability benchmarks.
  - interpretability: Makes black-box behavior transparent/explainable: explainability, saliency maps, mechanistic interpretability, representation engineering.
  - other: Monitoring that is neither interpretability nor evaluations (e.g. certain Trojan-monitoring or calibration work).

=== UNCERTAINTY / FLAG FOR REVIEW ===
Whenever the rules above say to "flag for review", or you are genuinely unsure whether the paper qualifies: do NOT make a confident decision. Set is_frontier_ai_safety to your best-guess lean, set confidence to 0.4 or lower, and explain the ambiguity in the rationale. Papers below the confidence threshold are routed to a human reviewer. When confident, set confidence honestly between 0 and 1.

=== OUTPUT ===
Return ONLY a JSON object with exactly this schema:
{
  "is_frontier_ai_safety": true | false,
  "confidence": number between 0 and 1 (confidence in the decision),
  "category": "alignment" | "robustness" | "monitoring" | "systemic_safety" | null,
  "subcategory": "evaluations" | "interpretability" | "other" | null,
  "rationale": "string (1-3 sentences explaining the decision)"
}
Set category/subcategory to null when is_frontier_ai_safety is false.
