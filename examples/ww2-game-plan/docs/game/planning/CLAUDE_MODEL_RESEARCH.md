# Claude model research for scoped game agents

Verified: **2026-09-27**. Status: planning evidence, not an execution configuration or project benchmark. Scope: Anthropic's current public model documentation, Claude Code model controls, and billing distinctions. Only official pages were opened; no model inference, account login, credential inspection, purchases, or paid execution were performed. Local architectural context: [MASTER_ARCHITECTURE](../MASTER_ARCHITECTURE.md), dated 2026-09-27. This note changes no game contracts or schemas.

## Verified model choices

Prices are standard first-party Claude API USD per **1 million tokens**, input/output, before extra tools or pricing modifiers. Availability in documentation is not proof of availability on the user's account.

| Display name | Pinned Claude API model ID | Input / output | Context / max output | Thinking and effort |
|---|---|---:|---|---|
| Claude Fable 5.1 | `claude-fable-5-1` | $10 / $50 | 1M / 128K | Adaptive always on; default `high` |
| Claude Opus 5.5 | `claude-opus-5-5` | $4 / $20 | 1M / 128K | Adaptive always on; default `medium` |
| Claude Sonnet 5 | `claude-sonnet-5` | $2 / $10 | 1M / 128K | Adaptive on by default, can be disabled; default `high` |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | $1 / $5 | 200K / 64K | Manual extended thinking with `budget_tokens`; effort unsupported |

Row sources: [Fable 5.1](https://platform.claude.com/docs/en/models/fable-5-1/overview), [Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview), [Sonnet 5](https://platform.claude.com/docs/en/models/sonnet-5/overview), [Haiku 4.5](https://platform.claude.com/docs/en/models/haiku-4-5/overview). The [current lineup](https://platform.claude.com/docs/en/models/overview) recommends starting with Opus 5.5 for most workloads and considering Fable 5.1 for harder reasoning or long tasks when higher-effort Opus evaluations fall short. Mythos 5.1 is invitation-only through Project Glasswing; it is not a general default for this project.

Fable 5.1, Opus 5.5, and Sonnet 5 support **`low`, `medium`, `high`, `xhigh`, `max`**. Set the API field `output_config.effort`. `adaptive` is a thinking mode, not an effort value; `ultra` is not in this Claude effort set. Effort is a behavioral control, not a hard token ceiling, and the same label is not a cross-model or cross-provider quantity. Choose levels through project evaluations rather than translating GPT effort names mechanically. [Effort reference](https://platform.claude.com/docs/en/build-with-claude/effort)

Thinking tokens are charged as output even when hidden, and consume `max_tokens` alongside the visible response. Fable 5.1 and Opus 5.5 reject disabled thinking. Sonnet 5 allows it. [Thinking reference](https://platform.claude.com/docs/en/build-with-claude/thinking)

## Pinning and Claude Code

Dateless IDs from the 4.6 generation onward identify pinned versions; the absence of a date does not imply a moving alias. Haiku's convenience alias `claude-haiku-4-5` resolves to the dated ID above. [Model IDs and versioning](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions)

Claude Code family aliases move with releases and vary by provider. Currently `opus`/`sonnet` resolve to Opus 5.5/Sonnet 5 on the Anthropic API; some cloud providers resolve Sonnet to 4.6 or 4.5 and Foundry resolves Opus to 4.6. Pin full IDs for reviewed runs. `opusplan` switches from Opus planning to Sonnet execution and therefore is not one pinned model. Fable 5.1 needs Claude Code ≥2.1.257, Sonnet 5 ≥2.1.197, Opus 5.5 ≥2.1.280. Claude Code accepts session `--model` and `--effort`; its `ultracode` setting adds workflow orchestration with `xhigh`, rather than defining a new API effort. [Claude Code model configuration](https://code.claude.com/docs/en/model-config)

Custom Claude Code subagents accept full-ID `model` and separate `effort` frontmatter. Model inheritance, per-invocation overrides, environment settings, and organization restrictions can affect resolution. Record the actual run model, not only the requested model; `/tasks` exposes subagent model and specified effort. Thinking otherwise inherits from the session, with no separate per-subagent thinking field. [Subagent configuration](https://code.claude.com/docs/en/sub-agents)

## Proposed routing — project judgment

These are starting choices for the historical Godot/typed-GDScript project, **not claims of measured superiority on this repository**. Root model routing owns the combined Claude/Codex matrix.

| Agent work | Claude starting choice | Escalation or boundary |
|---|---|---|
| Orchestrator; architecture and interfaces | Opus 5.5, `high` | Fable 5.1, `high`, for unresolved architecture or prolonged integration work; consider `xhigh` after bounded evaluation |
| Scoped Godot implementation; asset pipeline scripts | Sonnet 5, `high` | Opus 5.5, `high`, for difficult bugs or cross-domain changes requested through owners |
| Historical research and conflicting evidence | Opus 5.5, `high` | Fable 5.1 for unresolved multistep source problems; model confidence never promotes evidence |
| Experience concepts; dialogue drafts; visual briefs | Sonnet 5, `high` | Opus 5.5 for difficult consistency reviews; human ExperienceReview remains independent |
| Extraction, indexing, metadata formatting | Haiku 4.5, no effort field | Only bounded transformations with source locators and deterministic validation; Sonnet/Opus resolves ambiguity |
| Historical, provenance, architecture, integration reviewer | Opus 5.5, `high` | Separate run from builder; use a qualified Codex reviewer for Claude-built changes and Claude for Codex-built changes where practical |
| Critical unresolved review | Fable 5.1, `high` | Raise to `xhigh`/`max` only against a specific unresolved question and approved spending ceiling |

Changing provider may expose different mistakes, but does not itself establish reviewer independence or correctness. The reviewer needs the locked evidence/contract versions and acceptance criteria, not the builder's conclusion as authority. Keep historical, provenance, simulation/integration, and human experience gates distinct. Models operate on scoped five-layer context packs outside simulation ticks; no automatic NEXT chain is implied.

All four current models accept text/images and return text. They can inspect reference images and write procedural code or tool instructions, but these interface specifications do **not** establish native mesh, rig, animation, material, or audio manufacture. Separate asset tools and import/visual/performance checks remain necessary. This is an architectural inference from the [documented modalities](https://platform.claude.com/docs/en/models/overview). Vision coordinates, object counts, and difficult image interpretations can be inaccurate; do not infer precise dimensions, equipment variants, or historical truth from unchecked visual output. [Vision limitations](https://platform.claude.com/docs/en/build-with-claude/vision)

## Cost and execution boundary

The table is not a per-agent quote. A quote must include cumulative inputs across turns, visible and thinking output, tool costs, retries, concurrency, and the selected billing surface. Caching and batch discounts can change the result; premium modes and geography can add cost. Standard first-party Opus 5.5 fast mode is $8/$40 per million, compared with $4/$20 standard. [API pricing](https://platform.claude.com/docs/en/about-claude/pricing)

Claude subscriptions and raw API/Console billing are separate products. [Billing distinction](https://support.claude.com/en/articles/9876003-i-have-a-paid-claude-subscription-pro-max-team-or-enterprise-plans-why-do-i-have-to-pay-separately-to-use-the-claude-api-and-console). In Claude Code, an `ANTHROPIC_API_KEY` environment setting takes precedence over subscription authentication; `/status` identifies the active method without printing the secret. [Authentication priority](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code)

The SDK help page's **top update pauses the announced June 15 change**: Agent SDK, `claude -p`, and third-party app usage still draw from subscription limits, and the announced separate monthly SDK credit is unavailable. The obsolete announcement remains lower on that page; do not quote it as active policy. [Current SDK billing notice](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)

Fable can consume additional usage credits depending on plan. Claude Code's noninteractive/SDK execution does not show the interactive Fable billing consent prompt. Therefore this project's quote-before-paid requirement must be enforced before dispatch, not delegated to a prompt expected inside the worker. [Fable usage-credit behavior](https://code.claude.com/docs/en/model-config#fable-and-usage-credits)

Actual account entitlement and installed Claude Code version remain **unknown**. Confirm them through the user's authenticated `/model`, `/status`, and version display before execution. The current Codex collaboration tool's model allowlist contains OpenAI models only: this session cannot spawn a Claude worker through that tool. Claude routing is a proposed external executor configuration, not a claim that Claude agents were run.
