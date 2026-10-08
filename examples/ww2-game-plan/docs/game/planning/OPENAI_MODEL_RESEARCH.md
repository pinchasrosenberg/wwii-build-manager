# OpenAI model selection evidence — 2026-09-27

This is model-selection research, not a migration or a claim that new models were enabled in this session. Official OpenAI documentation was searched and opened. The recommendation for a particular game role is project judgment, not a published benchmark for WWII simulation development.

| Verified API model | Relevant role | Supported effort used in this plan | Standard input/output USD per 1M tokens |
|---|---|---|---|
| `gpt-6-astra` | Architecture, difficult cross-domain reasoning and critical review | high, xhigh; max for a bounded escalation | 10 / 50 |
| `gpt-6-sol` | Coding and agentic implementation | medium or high | 2 / 10 |
| `gpt-6-luna` | Focused extraction/classification and small repeatable transformations | low or medium | 0.10 / 0.50 |

These are short-context standard API rates, not subscription charges or a run quote. Cache, long-context, tool and processing-tier pricing differs. Sources: [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [Sol](https://developers.openai.com/api/docs/models/gpt-6-sol), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna).

Codex is an agent environment, not another model family. The official model guide recommends Sol for implementation and Luna for focused repeatable work, while availability depends on rollout/client/account. [Codex model selection](https://learn.chatgpt.com/docs/models).

The current session's exposed collaboration tool allows `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, and `gpt-5.5`. It does **not** list GPT-6 Sol/Luna or Claude. Therefore this plan distinguishes an intended current-model route from an executable-here fallback: Sol6→Sol5.6 for substantial implementation; Luna6→Luna5.6 for bounded extraction. These fallbacks are not asserted to have equal quality, latency or price. Their local availability comes from the tool schema, not an API account check.

Use a separate run and independent evidence for review. A second provider can reduce correlated mistakes but does not establish historical verification. Models that accept images can inspect a map crop or rendered asset; tool-mediated image generation is not proof that the language model natively outputs rigged 3D meshes or audio.

No account credentials, API availability probe, paid model call, CLI model switch or subscription change was performed. Before a future launch, resolve the exact permitted model/effort and record it; a fallback must be explicit. Do not attach the full repository merely because a provider offers a large context window.
