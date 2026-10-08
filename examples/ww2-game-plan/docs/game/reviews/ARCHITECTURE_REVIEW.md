# Independent architecture and Deliver consistency review

Reviewed: 2026-09-27. Scope: `MASTER_ARCHITECTURE`, `DELIVER_INTEGRATION`, `ECONOMY_AND_PRICING`, `EXPERIENCE_DESIGN`, `IMPLEMENTATION_SEQUENCE`, `REPO_MAP`, and the context/agent/domain contracts. Targeted cross-checks used historical anchor policy and the local Deliver registry fragment. This is a document/design review; no new runtime, payment, live Deliver integration or playtest was executed.

Verdict at this review snapshot: the principal boundaries are coherent, but three contract gaps below should be resolved before implementing the corresponding proof. Two narrower lifecycle/maturity clarifications should be recorded before declaring architecture completion. Findings are scoped fixes, not a request to build a larger marketplace or game now. File line references describe the reviewed snapshot and may move during correction.

## Findings

### AR-01 · P1 · Experience review is a predecessor of the thing it must observe

References: [MASTER_ARCHITECTURE.md](../MASTER_ARCHITECTURE.md), lines 55–58; [EXPERIENCE_DESIGN.md](../EXPERIENCE_DESIGN.md), lines 48–54; [IMPLEMENTATION_SEQUENCE.md](../IMPLEMENTATION_SEQUENCE.md), M1/M3 gates.

The master graph places the combined historical/integration/**experience** gate before the headless core and playable client. ExperienceReview explicitly requires an independent fresh human playtest, so the depicted dependency cannot be satisfied. It could also encourage substituting a document or scripted demo for actual play evidence.

Minimal correction: split **preflight** (schema, historical scope, provenance, permitted reconstruction, runnable contracts) from **release promotion**. Produce an unpromoted playable candidate after preflight; run simulation/integration validation and the fresh playtest; let independent review promote the immutable candidate or return bounded revision work. Include a feedback edge. Architecture review and synthetic technical fixtures can proceed before human play but cannot mark ExperienceReview complete.

Acceptance: a sample release record cannot have `ExperienceReview=passed` without a playable candidate digest and actual review evidence. Failed readability or desire-to-continue observations block promotion even when all automated validators pass.

### AR-02 · P1 · Order acceptance and delivered-result acceptance need separate states

References: [DELIVER_INTEGRATION.md](../DELIVER_INTEGRATION.md), lines 10–16 and 39–43; [ECONOMY_AND_PRICING.md](../ECONOMY_AND_PRICING.md), lines 7–13.

The port accepts the quote/order before execution, while the economy moves from execution through actual cost to settlement. Quote quality/acceptance criteria exist, but no named outcome binds the delivered artifact to those criteria before successful settlement. A provider-reported `SUCCEEDED` could therefore be interpreted as sufficient to charge the fixed success price even when the mandatory artifact validator rejects the result. Publication validation is mentioned separately and is not explicitly connected to the settlement decision.

Minimal correction: introduce a durable delivered-result validation receipt/state, distinct from `AcceptedOrder`. Bind it to the quote, result/artifact digest, required criteria and evaluator. Full success settlement requires the success disposition; partial, failed, rejected or timed-out validation follows the quote's frozen terms. Define who decides and a bounded decision deadline. This needs only a local deterministic contract fixture at M0; a complete dispute service can remain deferred.

Acceptance: provider `SUCCEEDED` plus a bad artifact hash or failed mandatory criterion cannot settle as successful delivery. A duplicate validation/settlement event cannot charge twice. A partial result cannot inherit the full success disposition silently.

### AR-03 · P1 · Artifact resolution must enforce the context grant, not just content integrity

References: [DELIVER_INTEGRATION.md](../DELIVER_INTEGRATION.md), artifact mapping at line 31 and transport section; [CONTEXT_ARCHITECTURE.md](../CONTEXT_ARCHITECTURE.md), lines 17–19 and 35–41.

Context architecture correctly states that references do not authorize access and policy checks precede fetching. The Deliver artifact mapping lists digest, size, type and license validation but does not state the authorization boundary for resolving external path-style references. A correct hash proves content identity; it does not prove that the requesting task may read that local path, storage tier, source or actor memory.

Minimal correction: require the adapter resolver to bind every read to the effective task/principal grant, permitted storage tier/root and expected artifact identity before exposing bytes. Reject path traversal, absolute/out-of-root paths and symlink escapes outside the grant; apply equivalent checks to remote storage object references. Recheck revoked/expired grants and preserve namespace/NPC knowledge restrictions. A deterministic selector remains a policy proof, not an OS sandbox.

Acceptance: a permitted manifest referencing an unauthorized naval document or another NPC's memory is rejected even if its hash is valid. A storage key escaping its allowed root never returns source bytes or an informative unauthorized-content summary.

### AR-04 · P2 · Cost uncertainty and delivery uncertainty need an explicit policy boundary

References: [ECONOMY_AND_PRICING.md](../ECONOMY_AND_PRICING.md), lines 7 and 13; [DELIVER_INTEGRATION.md](../DELIVER_INTEGRATION.md), line 41.

The documented lifecycle requires actual cost before settlement, and unknown actual usage is described as `null/RECONCILE`. Delivery uncertainty should block duplicate execution and an unjustified settlement; missing provider cost telemetry is a different condition. For a validated fixed-price delivery, P is already known even when provider cost C is delayed. As written, a missing cost receipt can indefinitely hold buyer funds or make a successfully delivered request look as though execution itself is uncertain.

Minimal correction: state whether buyer settlement can finish while provider cost accounting remains pending, or explicitly define a bounded hold/reconciliation policy. Keep the provider's cost unknown rather than zero and keep its exposure conservative. In either choice, missing C cannot change agreed P, trigger a duplicate execution, or erase the provider's liability. Avoid using one status field for both delivery and accounting finality.

Acceptance: a valid delivered result with missing actual cost has a documented buyer disposition, `actual_cost=null`, and a pending provider-accounting status; it never becomes zero-cost or a new payable request.

### AR-05 · P2 · Planned M0/provider behavior is sometimes written as already demonstrated

References: [MASTER_ARCHITECTURE.md](../MASTER_ARCHITECTURE.md), status line; [DELIVER_INTEGRATION.md](../DELIVER_INTEGRATION.md), line 19; [ECONOMY_AND_PRICING.md](../ECONOMY_AND_PRICING.md), line 31; [REPO_MAP.md](../REPO_MAP.md), missing-system section.

At review time, the local schemas/proofs were still being authored. Statements that the local simulator “exercises” the lifecycle and “proves” the fixed-price subset can be read as completed work, while REPO_MAP explicitly says no accepted-price ledger is demonstrated. The live Deliver caveat is accurate, but the local maturity boundary should be equally clear.

Minimal correction: use planned/future wording until the local test results exist; after execution, point to the exact implementation, test command, covered cases and limitations in VALIDATION_REPORT. The proposed proof may justify a narrow subset, never durable accounting, production isolation or full game completion.

Acceptance: every completed-capability claim is backed by a named artifact/check; design-only work and unmeasured human experience remain explicit.

## Boundaries that pass this review

- The game provider port is outside the simulation tick, and the game has a local path independent of Deliver. LLM dialogue is optional and cannot freeze deterministic simulation.
- The observed Deliver fragment actually has listener/state/context methods and explicitly rejects `reinforce_next`. Its missing imports prevent claiming a runnable local production adapter. The docs correctly describe a compatibility target, not verified interoperability.
- Historical truth, reconstruction and gameplay have distinct write authorities. Import review does not trust existing `AtlasFact` or source-count confidence automatically.
- Historical anchors are bounded by source precision; the detailed historical policy includes explicit conflict/end/fork/review responses. Profiles and an experience director do not justify secret resurrection, false enemy locations or rewriting history. This resolves the main tension between local agency and protected events at the design level; executable anchor tests remain future work.
- NPC knowledge uses delivery time and actor-specific memory, separate from historical effective time. Durable relationships and continuity are owned by character state, with optional LLM expression behind the same interface.
- Relevance is separated from access, claims carry their provenance as a bundle, expansions are scoped, and estimated tokens are not presented as provider telemetry. The minimal ContextManifest still needs semantic validation of its grants in the implementation.
- The nine-axis quality vector and independent human experience gate resist trading historical integrity for visuals or confusing higher activity density with better pacing.

## Schema follow-up and closure

The canonical JSON schemas were not yet available at the initial review. Review them next for request/quote/result hash binding; immutable quote identity and fixed price; distinct order/result acceptance; explicit delivery/accounting states; effective scope/knowledge grants; provenance closure; and estimated versus measured metric fields. JSON schema alone cannot prove policy authorization, numerical conservation, truthful sources or human experience.

Each finding closes when the owning document/contract is corrected and its scoped acceptance case is either tested in the intended phase or explicitly retained as an unimplemented gate. Record final dispositions in this review or VALIDATION_REPORT; do not imply that an unexecuted acceptance scenario passed.

## Consolidation resolutions (root, 2026-09-27)

- AR-01: MASTER graph now separates historical/contract preflight, playable candidate, independent ExperienceReview and promotion with a feedback edge. No human playtest is claimed.
- AR-02: DELIVER_INTEGRATION and ECONOMY now require DELIVERED/RESULT_VALIDATED, a distinct criteria-bound independent result disposition, and frozen partial/failure terms before successful settlement.
- AR-03: DELIVER_INTEGRATION explicitly requires task/principal/grant/root authorization before reference resolution, plus traversal/symlink rejection. M0 only selects in-memory refs and does not pretend to resolve artifacts securely.
- AR-04: Initial policy holds buyer settlement pending known provider cost, with separate execution/accounting uncertainty. Production quote terms require bounded review/reconciliation deadlines and an escalation owner. Durable enforcement remains outside M0 and blocks real-money adoption.
- AR-05: Planned behavior is labeled as design; only actual tests and artifacts are claimed in VALIDATION_REPORT.

The original findings remain as review history. Concrete M0 coverage/limits supersede a broad statement that every production adapter behavior is implemented.
