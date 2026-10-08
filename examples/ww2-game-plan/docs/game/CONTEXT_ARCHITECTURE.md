# Context architecture

Status: design contract for the game workstream; no new implementation is claimed. The existing runtime observations below are verified from the named files; the five-layer router is planned as a new, separately testable component. A design requirement here does not establish that production enforcement already exists.

## Purpose and boundaries

The root coordinator retains the global plan, dependency map, open decisions, and acceptance criteria. A specialist receives the smallest sufficient packet for its assigned work. Neither every specialist nor every invocation receives the master specification. Domain ownership forms a dependency graph; it is not a fixed `Tank → Gun → NEXT` execution chain.

The product is a game centered on presence: inhabiting a compelling role, doing meaningful things, understanding the world and wanting to continue. Context efficiency serves that experience; a technically correct graph, historical exhibit or source browser alone does not satisfy the product goal. The task packet includes the current experience hypothesis and the smallest relevant playtest criteria. An independent ExperienceReviewer can block promotion even when contracts, historical checks and rendering pass.

Three namespaces remain separate throughout retrieval, memory, and output: **historical truth** (source-backed claims and their verification state), **reconstruction** (explicit assumptions or estimated missing detail), and **gameplay** (rules, balance, presentation, and fictional state). Retrieval relevance, a valid schema, or an agent's confidence cannot promote one namespace into another. Progressive fidelity means increasing detail when justified by evidence, usefulness, and budget; unavailable detail remains an explicit gap.

Game contracts and the local router run independently of Deliver. A future Deliver adapter may transport the same contracts and usage receipts; installing or using Deliver is not a prerequisite for the game, its tests, or deterministic simulation.

## Five-layer ContextPack

`ContextPack` is the resolved payload consumed by an agent. `ContextManifest` is the auditable selection receipt containing references, hashes, decisions, estimates, and scope. Keep its schema versioned. References alone do not authorize fetching content.

The initial draft manifest uses `schema_version`, `manifest_id`, `task_id`, `agent_role`, `domain`, `policy_version`, `index_snapshot_hash`, `items`, `readable_scope`, `writable_scope`, `excluded_domains`, `expected_output`, `input_budget_tokens`, `estimated_tokens`, `usage_quality`, `expansion_requests`, and `metrics`. Each selected item records `item_id`, `layer`, `domain`, `ref`, `sha256`, `token_estimate`, and `reason`. `readable_scope` must carry or reference the effective entities/time/geography/knowledge grants; a role/domain string alone is insufficient. The fuller audit and approval semantics below are requirements for a production adapter, not a claim that the draft schema enforces them. Deterministic index selection is not an OS sandbox.

| Layer | Required contents | Explicit exclusions |
|---|---|---|
| `GlobalInvariantContext` | Tiny, versioned capsule: namespace separation, provenance, uncertainty, cost authorization, scoped access, NPC knowledge rule, output contract | Master specification, domain catalog text, full global memory |
| `DomainContext` | Domain definition, assigned module excerpts, relevant symbols, constraints, owned interfaces, acceptance criteria | Other domains' implementations and unrelated domain chapters |
| `TaskContext` | Objective, task ID, entity IDs, requested time/geography, allowed fidelity, expected output, stopping criteria, scoped grants and budgets | Unbounded conversation replay or unrelated prior tasks |
| `DependencyContext` | Versioned input/output interfaces, units, coordinate/time conventions, relevant dependency result or fixture, validity limits | Whole dependency implementations or transitive histories |
| `EvidenceContext` | Only relevant, permitted claims with complete source references, locators, verification state, temporal/geographic meaning, contradictions and gaps | Whole source libraries, unattributed summaries, speculative confidence |

Suggested initial global capsule target: at most 400 estimated tokens. This is an engineering target to measure, not a statement of actual tokenizer usage. Mandatory instructions and provenance must not be silently truncated to meet it. If the required packet exceeds its budget, return a gap before dispatch.

Domain documents are human-readable source material, not automatic prompt attachments. The context index stores bounded excerpts or symbol-level units; each unit identifies its parent document and version. The full master remains discoverable by the root for targeted decisions, rather than copied into every packet.

## Router contract and decision order

Input: `agent_role`, `task`, `domain`, `entity_ids`, `time`, `geography`, and `dependencies`, bound to a caller identity, policy version, index snapshot, task-scoped authorization, knowledge principal, and budget. Output: `ContextManifest` plus a bounded resolved `ContextPack`, or a typed `CapabilityGap`. An input role name is not proof of authority; derive effective permissions from trusted task grants.

The router is deterministic for identical canonical input, policy, and index snapshot. It performs no model invocation, external paid call, or factual promotion.

1. **Validate the request.** Verify role, task binding, requested namespace, entity IDs, time precision, geography convention, dependency declarations, and nonnegative budgets. Do not infer missing access from an ambiguous request.
2. **Apply hard exclusions first.** Check authorization, domain ownership, explicit dependency grants, requested time/geography, namespace, evidence visibility, and the recipient's knowledge restrictions. Denied content never reaches a relevance scorer, embedding call, summary generator, or packet. Audit logs visible to the requester redact inaccessible titles, entities, content, and source details.
3. **Resolve mandatory context.** Select the invariant capsule, task contract, required domain interface, and explicitly required evidence bundles. A claim and every reference needed to interpret it form an indivisible provenance bundle. Closure adds references only if they are independently permitted. A forbidden reference blocks the bundle; it does not cause an automatic permission expansion.
4. **Rank eligible optional units.** Use explicit ordered signals: exact task entity/symbol match; declared dependency interface match; temporal/geographic match; task type relevance; evidence quality as an observed status; measured historical usefulness when available; and estimated payload cost. The implementation publishes its ranking rule and coefficients, or lexicographic order, under a version. Break ties with stable item IDs. Embeddings may help find candidates within eligible partitions; they never authorize or rank across denied partitions.
5. **Pack within budget.** Reserve output and tool-envelope capacity first. Select complete bundles, estimate the serialized packet again, and remove the lowest-ranked optional bundle until it fits. Never remove mandatory invariants, split provenance, or overflow to satisfy relevance. A token estimate is not an enforceable provider limit.
6. **Emit a receipt.** Record snapshot and content hashes, included units and layers, permitted exclusion reasons, budget estimates and their method, unresolved gaps, dependency versions, and the selection trace. Record an empty result explicitly. Replaying the same inputs must reproduce selection order and content hashes.

Hard access and relevance are separate functions. A highly relevant naval document remains excluded from an ungranted tank task. A permitted ground-vehicle document may still be omitted because it is irrelevant or does not fit. Do not collapse these outcomes into a single numeric score.

## Context index

The index is a versioned local inventory, not merely an embedding database. Each unit records:

- Stable item ID, document/source reference and locator, content hash, namespace, domain owner, and sensitivity/access policy.
- Symbol/entity IDs and aliases, interfaces exported or required, explicit dependency edges, and units/conventions.
- Historical effective time with precision and interval evidence; scenario time; geographic footprint, coordinate system, or explicitly declared global applicability. Missing applicability is not equivalent to global applicability.
- Evidence state, provenance bundle IDs, supersession/conflict relationships, and index extraction version. A candidate's presence in the index does not verify it.
- Payload byte count, estimated tokens and estimator identity; retrieval/provider cost if known. Unknown cost remains unknown.
- Usefulness observations with evaluator, task class, sample count, measurement date, and uncertainty; estimates are labeled and do not become confidence facts.

Use separate partitions or indexes where knowledge/access policies demand isolation. A vector query over unrestricted content followed by prompt-side filtering is insufficient. Keep metadata needed for selection small; fetch bodies only after policy checks.

## Time, geography, and knowledge

Historical time and knowledge availability are different dimensions. An archival fact about 6 June may have become known to an actor on 8 June. Scope intersection may make it relevant to an analyst task without making it visible to an NPC on 6 June. A dated source snapshot does not establish an interval or justify interpolated movement. Unsupported intervals, locations, and aliases remain gaps or labeled reconstruction.

Geographic matching uses declared geometry, coordinate system, and tolerances. An area of operations can grant a bounded buffer when declared in advance. Doctrine is eligible without local overlap only when its metadata explicitly declares applicable global or regional scope. Unknown time or geography is allowed only by an explicit task policy for investigating that unknown; it cannot be reported as a match.

NPC packets use an actor-specific knowledge principal and simulation cutoff. They contain only delivered observations, received orders, and retained memories available by that cutoff, each with delivery time, origin, reliability state, and access scope. A source's real-world truth does not override this restriction. Enemy truth, future events, later research, undelivered messages, and hidden simulation state are excluded even if useful to the decision. Lost communications and mistaken reports remain possible. NPC output is an order, belief, or decision; it does not mutate historical truth.

NPC identity, commitments, relationship changes and remembered interactions persist across scenes and saves under the same actor-specific boundary. Bounded memory selection preserves relevant continuity and records compression/forgetting explicitly; it cannot reset a relationship merely to save tokens. Deterministic behavior and authored dialogue can implement the core loop. An LLM is an optional extension that receives the same restricted packet and cannot become the authoritative store of identity, relationships or world state.

Root visibility is a development/research responsibility. It does not grant in-world omniscience to the root's NPC-facing packet builder. Development caches, source retrieval logs, and NPC memories are separate; cache keys include policy, principal, cutoff, namespace, and content versions.

## Expansion, dependencies, and cost

A specialist can return a `CapabilityGap` or scoped `CapabilityRequest`; it cannot silently load another domain, increase its budget, or fan out into agents. A request states the missing capability or evidence, why the current task needs it, the smallest additional entities/time/area/interface, expected benefit, estimated cost and method, alternatives, and what can continue independently.

The root resolves the request using existing grants when sufficient, requests an interface/result from the owning specialist, or issues a new narrow grant. An expansion receipt binds the original request, permitted scope, policy, expiry/task lifetime, maximum budget, and approving authority. A dependency grant exposes the approved interface/result only; it does not grant all documents in that domain. The router rechecks policy after expansion. NPC future-knowledge restrictions cannot be waived by ordinary root expansion; changing a scenario's knowledge rules requires an explicit scenario design change outside the NPC run.

Before any paid execution, present a concrete quote with capability, provider/model if applicable, scope, input/output and call assumptions, expected cost or a clear unknown, maximum authorized spend, and cancellation/retry implications. Execution requires an applicable user authorization or previously approved limit bound to that quote/scope. Internal root approval alone is not paid authorization. Local deterministic selection is free of model charges. Uncertain delivery is reconciled before retry; quoted, estimated, reserved, and actual usage remain distinct.

## Existing runtime: reuse and gaps

| Existing source | Verified behavior | Implication for the new router |
|---|---|---|
| `etl/driver_runtime/context.py` | `pack_context` retains mandatory input anchors, packs whole facts/candidates, labels token estimates, and stops if mandatory context exceeds budget | Reuse the provenance/budget discipline. Its `anchor` is everything outside facts/candidates; do not put the full master there. It does not establish domain, geography, or NPC access controls. |
| `etl/driver_runtime/contracts.py` | Strict frozen contracts; `EvidenceClaim`, `EvidenceRef`, `TemporalScope`, `RequestBinding`, `GraphPolicy`, `EvidencePolicy`, `BudgetPolicy`, `DriverResult` | Adapt bindings, evidence states and temporal semantics. Schema validity and model confidence confer no factual authority. Graph filter flags alone are not a context authorization boundary. |
| `etl/driver_runtime/README.md` | Describes bounded `TEXT_JSON_V1` transport and says the full Markdown specification is not attached to every request | Continue bounded transport. This documentation is operational context, not proof that new game isolation policies exist. |

Keep existing `pack_context` behavior unchanged until an explicit adapter and regression checks exist. New game-specific contracts wrap or translate existing values rather than changing historical truth semantics. Existing `minimum_confidence` or model-estimated metrics do not substitute for evidence verification.

## Telemetry and acceptance

The selected experience profile is an explicit gameplay field: `Easy/Experience`, `Standard`, `Simulation`, or `High Fidelity`. Profiles can change assistance, explanations, control burden, simulation detail and transparently labeled subjective lethality settings. They do not rewrite historical facts, source verification, identities or chronology. A reconstructed quantity remains reconstructed at every profile; a higher fidelity label is not evidence. Profile-specific playtest criteria travel in `TaskContext`, while the historical invariants remain unchanged.

For every selection, record estimated packet tokens and estimation method; actual provider input/output/cached usage when returned; selected item/source/domain counts; dependency interface count; excluded counts by reason; expansions requested/granted/denied; mandatory overflow; and routing time. Report actual usage as unavailable when absent.

After execution, record evidence IDs actually used in assertions, task success against named acceptance criteria, evaluator and status, unresolved uncertainty, and an `unused_context_estimate` with method. Merely loading an evidence item is not using it. Attribution cites only evidence supporting the particular assertion; the manifest separately records everything made available. An agent's self-report can inform an estimate but cannot prove causal usefulness. Compare task success and uncertainty alongside token savings; low token count alone is not success.

Product review records a nine-axis quality vector: historical quality, visual quality, simulation quality, character quality, interaction density, atmosphere, interest, world coherence, and performance. Each axis has observable criteria, evaluation method and uncertainty rather than invented scores. Interaction density includes the value of deliberate quiet time; it is not an instruction to maximize actions per minute. An aggregate score cannot hide a failed experience gate or a violated historical/knowledge invariant.

Minimum acceptance cases for the prototype and later adapter:

| Case | Expected result |
|---|---|
| Tank task, naval source is the strongest keyword/embedding match | Naval source is excluded before scoring; no body/title leaks in the tank-facing output. |
| Tank needs ship transport load limits | Only the named transport interface/result enters `DependencyContext` under a narrow logistics/naval grant. Naval fire-control implementation remains excluded. |
| Correct entity, wrong date or outside granted area | Excluded by hard scope policy; similarity cannot rescue it. |
| Snapshot followed by a later snapshot | No invented continuous interval or interpolated position. |
| NPC can read a received order but an accurate enemy report arrives later | Order included; later report and hidden enemy state excluded. |
| NPC cache was generated for another actor or later cutoff | Cache miss/rejection, never reuse. |
| Required evidence refers to a denied source | Entire evidence bundle withheld; explicit permitted gap returned. |
| Mandatory packet exceeds input allowance after output reserve | `CapabilityGap`; no paid call, silent truncation, or budget overflow. |
| Optional bundle exceeds remaining budget | Complete bundle omitted and counted, with provenance intact for retained bundles. |
| Input/index order shuffled with identical canonical data | Identical ordered selected IDs and packet hash. |
| An approved expansion is replayed for another task or after expiry | Rejected; existing authorization does not transfer implicitly. |
| Agent cites one of three supplied sources | Answer attributes the used source; manifest retains all three; unused metric is an estimate. |
| A profile increases assistance or changes subjective lethality | The choice is visible as gameplay; historical facts and evidence state remain identical. |
| An NPC resumes after a scene/save boundary | Relevant commitments and relationships persist without exposing future or another actor's memories. |
| A slice is historically accurate but dull, confusing or unresponsive | ExperienceReviewer withholds promotion and returns specific observed gaps. |

These cases are requirements. The implementation/test report must name which are covered by executable tests and which remain design-only.
