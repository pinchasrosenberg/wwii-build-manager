# Agent roles and collaboration contracts

Status: proposed role registry and activation policy. Roles below are available responsibilities, not a promise that persistent agents or a Deliver integration exist today.

## Operating model

The root owns global intent, architecture, domain assignments, dependency versions, resource allocations, acceptance criteria, and integration. It creates a small number of bounded specialist tasks when independent work helps. Role registration does not start an agent. A simple tank question can run as one deterministic capability or one domain worker; it must not activate the complete registry.

The root's product goal is a playable sense of presence: a compelling role, meaningful activities, understandable consequences, and a reason to continue. An accurate historical display or graph view alone is insufficient. Experience review is a separate promotion gate, not a final cosmetic check.

Specialists receive a five-layer packet described in [CONTEXT_ARCHITECTURE.md](CONTEXT_ARCHITECTURE.md), scoped to their actual task. The root receives concise result contracts, relevant evidence, changed interfaces, and unresolved gaps rather than every worker's full conversation. A root may consult a specific global design section without distributing it to all workers.

There is no compulsory Tank → Gun → NEXT chain. A task graph can fork independent terrain and logistics checks, join their interface results, retry a failed bounded capability, or finish immediately when acceptance criteria are met. Relationships describe requirements and data flow; they do not prescribe permanent execution order.

## Finite role registry

Domain definitions and precise access boundaries are in [DOMAIN_REGISTRY.md](DOMAIN_REGISTRY.md). The domain specialist is one parameterized role with a registered domain, not an unbounded generic expert.

| Role ID | Responsibility and allowed output | Minimum packet and limits |
|---|---|---|
| `root_coordinator` | Task decomposition, scoped grants, dependency arbitration, budget allocation, integration and acceptance decisions | Global plan/index metadata and relevant domain summaries. Does not confer truth authority or paid authorization. |
| `domain_specialist` | Work inside one declared domain; produce versioned data, code/design changes or capability results with evidence/gaps | Domain/task slices plus approved dependency interfaces. A tanks assignment does not grant naval, aviation, or global evidence access. |
| `evidence_curator` | Resolve sources, preserve locators and contradictions, report observed verification states | Named sources/entities/time/area only. Produces evidence records, not unsourced historical certainty. |
| `reconstruction_designer` | Fill a stated fidelity gap with explicit assumptions, alternatives and reversible parameters | Scoped evidence and reconstruction policy. Outputs remain reconstruction; cannot promote into historical truth. |
| `gameplay_designer` | Specify rules, controls, scenarios and balance goals against an approved game scope | Relevant simulation interfaces and playtest criteria. Historical deviations are explicit gameplay choices. |
| `integration_engineer` | Implement versioned adapters, resolve units/types, integrate deterministic components | Interface dependency closure and assigned code files. Whole remote domains are unnecessary unless explicitly granted. |
| `verification_reviewer` | Evaluate contracts, provenance separation, determinism, knowledge isolation, budget enforcement and acceptance tests | Changed interfaces/files, relevant fixtures and expected behavior. A review does not authorize production mutation. |
| `experience_reviewer` (`ExperienceReviewer`) | Independently gate promotion on compelling role, meaningful activities, pacing/quiet time, readability, responsiveness, curiosity and desire to continue | Playable slice or reviewable interaction sequence, intended audience/profile, observed playtest evidence and current experience hypothesis. Does not accept technical/historical correctness as a substitute for play quality. |
| `npc_decision_actor` | Choose actions/orders from the actor's delivered observations, orders and memory | Actor-specific knowledge packet only. No root memory, future research, hidden world state, or unrestricted tools. |

Use at most the root plus the workers required by the current dependency graph and resource limits. Concurrency is an execution setting, not the number of registered roles. A capability can be deterministic code; use a model only when its contribution and cost are justified. Research and in-world NPC execution have different principals even if the same model or role implementation serves both.

## Assignment and handoff

Every assignment carries a task/request ID, role/domain, precise objective, owned files or entities, truth/reconstruction/gameplay namespace, time/area, input and output schema versions, mandatory constraints, permitted interfaces, acceptance criteria, budget, and stopping rule. The root records conflicts in file/entity ownership before concurrent writes begin.

`CapabilityRequest`, `CapabilityResult`, and `CapabilityGap` are reusable versioned wire contracts. Their schemas are maintained separately from these narrative docs. An execution adapter must validate them on both sides.

| Contract | Required meaning |
|---|---|
| `CapabilityRequest` | What bounded capability is needed, caller/task binding, domain/entity/time/area/knowledge scope, input references, dependency versions, desired output, evidence policy, budget, quote/authorization reference when paid |
| `CapabilityResult` | Request binding, terminal status, schema version, output references/hashes, actual used evidence, assumptions, contradictions, gaps, validation results, usage receipt, changed interfaces and suggested next steps |
| `CapabilityGap` | Typed missing evidence/access/dependency/fidelity/budget/capability; blocking effect; smallest requested expansion; alternatives; estimated benefit/cost with uncertainty; responsible owner |

Results use `SUCCEEDED`, `PARTIAL`, `FAILED`, or `RECONCILE` as defined by the executable schema; a blocked pre-dispatch task produces a typed gap, not an invented result status; a formatted result is not automatically a successful one. Partial progress and unresolved gaps are preserved. The root validates bindings and versions before integrating results, then evaluates the task's criteria. Suggested next actions are advisory; a worker cannot grant itself new domains or spend.

The root handles a cross-domain need by choosing the smallest suitable route: use an already granted interface; call the owning domain's bounded capability; or authorize a new task-scoped dependency grant. Scope changes rerun the context router. A quoted paid action can execute only under applicable user cost authorization. Reusing an existing grant is preferable to repeatedly asking the user about already authorized routine work.

## Memory, updates, and attribution

Persist short task results, decisions with their rationale/evidence, dependency versions, open gaps, and receipt IDs. Do not treat an entire prior conversation as mandatory memory. Memory is namespaced by actor/role, domain, scenario, time cutoff, evidence state and permissions. Source corrections or invalidated interfaces mark dependent memories stale.

NPC continuity includes stable identity, ongoing commitments, remembered interactions and relationships across scenes and saves. The characters domain owns durable state; `npc_decision_actor` reads a bounded projection and proposes validated updates. Memory compression records what was retained or deliberately forgotten; context budgets do not silently erase a relationship. The core loop works with deterministic logic or authored dialogue. An optional LLM can extend expression/decision behavior within the same contracts and knowledge boundary.

Future work listeners subscribe to task lifecycle events: assignment, result, accepted/rejected validation, capability gap, cancellation, and completion. Future context listeners subscribe to evidence/source changes, interface-version changes, scope/grant changes, and actor observation/order delivery. Both consume small deltas containing event ID, task/principal, changed references, before/after hashes or versions, and invalidation reason.

Listeners are compatible with a future Deliver adapter but first have a local, deterministic, testable interface. Delivery is idempotent by event ID; consumers reject stale or out-of-scope deltas, update only the affected view, and reroute context before subsequent work. A listener notification does not automatically spawn a worker, widen permissions, inject source text into every context, or trigger paid execution.

Track **available**, **selected**, **consumed**, and **cited** evidence separately. Final assertions cite supporting evidence actually used. Availability in the manifest is not attribution, and a source's inclusion in context does not prove it caused an answer. Citations preserve source/locator and evidence state; a reconstruction cites its inputs while clearly labeling the assumption.

## Future Deliver candidates

Potential reusable capability responsibilities include context selection, evidence resolution, domain evaluation, reconstruction proposals, gameplay evaluation, integration validation, and NPC decisions. These are responsibilities, not a competing API naming scheme or claims of existing registered Deliver services; adapters use the canonical API names in the master design and versioned schemas. Domain and role remain explicit arguments with independently enforced grants.

Transport adapters may provide job dispatch, quote acceptance, exact usage receipts, cancellations, idempotency and delivery reconciliation. Core game code receives the same request/result/gap contracts locally and remotely. A remote service is interchangeable only if it preserves policy, provenance, version binding, determinism requirements and NPC isolation; transport convenience is not sufficient.

## Experience promotion gate

An ExperienceReviewer returns pass, revise or not evaluated with observed evidence for: the role's appeal; meaningful activities and consequences; pacing including purposeful quiet; visual/control readability; responsiveness; curiosity; and willingness to continue. Prototype walkthroughs can support a provisional design review, but cannot be reported as actual playtest evidence. When implementation exists, promotion needs a playable observation. The builder's self-assessment alone does not satisfy the independent gate.

Review also reports the nine-axis quality vector: historical, visual, simulation, character, interaction density, atmosphere, interest, world coherence, and performance. Criteria and evidence are explicit; missing measurements remain unavailable. Scores, if adopted later, require a stated rubric and uncertainty. A high average cannot override a failed experience criterion or historical/knowledge invariant.

The four profiles are `Easy/Experience`, `Standard`, `Simulation`, and `High Fidelity`. They can vary assistance, explanation, control burden, simulation fidelity and transparently labeled subjective lethality. They share the same historical facts and provenance. Profile differences are declared gameplay rules, not claims that history changed. Review considers each intended profile separately; a more demanding profile is not presumed more interesting.

## Role-level acceptance scenarios

- A root assigns a tank suspension change. The specialist sees assigned tank entities, the terrain contact interface, units and fixtures; unrelated ship design is absent.
- A tank specialist needs amphibious loading data. It returns a bounded gap; a logistics/naval worker returns a loading-limit interface. Neither worker gets the other's full implementation or entire research history.
- Terrain and vehicle workers run independently, then the integration engineer checks shared units and schema versions. Their dependency graph has no mandatory global chain.
- An NPC actor receives a delayed order. Its decision packet changes only after delivery, even when a research worker already knows the order exists.
- An evidence correction invalidates a dependent result. The delta identifies the stale claim/interface; the root reruns only affected work after checking existing budget authorization.
- A result lists unused source references as citations or reports estimated tokens as measured usage. Validation rejects those claims while retaining the useful partial output.
- The technical reviewer passes a slice, but players cannot understand their role or meaningful choices. ExperienceReviewer requests revision and blocks promotion independently.
- An NPC's colleague recognizes an earlier promise after loading a save. The relationship persists while later undelivered news remains unavailable.

Executable coverage is recorded by the implementation, separately from this design acceptance list.
