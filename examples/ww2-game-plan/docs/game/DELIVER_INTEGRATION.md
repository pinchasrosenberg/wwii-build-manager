# Deliver integration and compatibility boundary

Status: designed against local evidence; no live Deliver handshake verified. The newer local Deliver registry fragment uses listeners, external artifact references and state events. The older Driver implementation uses CALLS/NEXT and token reservations. These are two different integration surfaces, not one interchangeable API.

## Port owned by the game

`GameCapabilityProvider` is a build/research port, outside the fixed simulation tick:

```text
evaluate(CapabilityRequest) -> PricingEvaluation | CapabilityGap
quote(request_digest, evaluation_id) -> Quote
reserve(quote_id, buyer_account, idempotency_key) -> Reservation
accept(quote_id, reservation_id, authorization_ref) -> AcceptedOrder
execute(accepted_order_id) -> CapabilityResult | Pending | Reconcile
validate_result(accepted_order_id) -> ResultValidation | Reconcile
record_actual_cost(accepted_order_id, cost, receipt_ref) -> CostReceipt | Reconcile
settle(accepted_order_id, idempotency_key) -> Settlement | Reconcile
status(request_id) -> RequestState
cancel(request_id) -> CancellationReceipt | Reconcile
```

`LocalCapabilityProvider` is designed to resolve checked-in deterministic implementations. `LocalDeliverSimulator` is designed to exercise lifecycle/settlement using synthetic test credits and no model, network or real money. `DeliverCapabilityProvider` will use a `DeliverRuntimeAdapter` to translate the same contracts when a real API exists. Alias these intentionally: the former implements the port; the latter owns wire translation and transport. The Episode Builder depends only on the port. No game module imports `etl.driver_runtime` or `aggregation_engine`.

Runtime capabilities (movement, ballistics, navigation) execute local versioned code already in the build. Asking Deliver to build an asset is not a network invocation every physics tick. LLM dialogue, if later enabled online, is asynchronous, bounded, cancellable and has a local fallback; a missing provider cannot freeze simulation.

## Mapping to observed Deliver concepts

| Game contract | Local Deliver evidence | Translation obligation |
|---|---|---|
| TaskContext / work update | `append_state_event`, event `layer`, `event_type`, `state_version` | publish work delta, correlation id, input digest, monotonic aggregate version |
| EvidenceContext / DependencyContext | state/context events and `reinforce_context` | publish references and authorized scopes; never all source bytes |
| AgentRole / Capability | `save_deliver`, capability_signature, version | capability signature and schema version compatibility |
| context subscription | `save_listener`, `list_active_listener_bindings`, `save_subscription` | filter before ranking; charge any paid listening through its own quote |
| artifact | PathArtifactStore refs and content_sha256 | hash verification, size/type/license checks before resolving path |
| used_context | `reinforce_context` | credit only reviewed used references, once per output event |
| new_context / new_work | state events | separate channels; factual validation before historical promotion |

`reinforce_next` explicitly rejects calls in the Deliver fragment. No game scheduler copies the legacy NEXT graph. A deterministic dependency resolver can be simple: ready work is selected by priority/deadline/id from unmet capability requirements, with dependency cycle detection, dedupe and bounded iterations. This is not a fixed sequence of agent identities.

## Transport and failure semantics

Each request binds request_id, episode_id, capability+version, input_sha256, context manifest hashes, schema version, budget/accuracy/quality targets and deadline. Same ID+same digest returns the previous result; same ID+different digest is conflict. Retries preserve identity, not create another payable order. Execution and settlement have their own durable idempotency keys and journal records.

Delivery timeout means `RECONCILE`, not failed-free. Keep reservation until provider status or signed receipt proves completion/non-execution. Cancellation before acceptance releases reservation; after acceptance follows the locked cancellation policy. Crash recovery uses outbox/inbox and compare-and-swap versions. Artifact publication occurs after content validation and receipt persistence. An unavailable provider yields a gap/local fallback; it cannot silently change the historical scenario.

Contract version is semantic, runtime internal version may be integer. Adapter maintains explicit mapping and refuses unknown versions. `CapabilityResult.status` distinguishes SUCCEEDED/PARTIAL/FAILED/RECONCILE; a PARTIAL result lists unresolved gaps and cannot satisfy a mandatory capability.

## Historical import adapter

Read the existing graph/files through a bounded snapshot export. Preserve source IDs, passage locators, original candidate class, original validation metadata, observed time precision and transformation chain. Do not trust `safe_for_factual_answer`, an `AtlasFact` label, number-of-sources confidence or auto-generated quotation as independent verification. Import auto-promoted assertions as review-required candidates until reviewers establish claim support, identity, time and locator. Unknown remains unknown.

No source corpus, ontology, graph or production Deliver state is rewritten by this game work. A later migration is additive, owner-scoped and reviewed from an explicit diff. Source review belongs to the historical workflow; schema conformance does not confer authority.

## Replacement acceptance gate

Run the same provider conformance suite against local and real adapters: equivalent input hashes, quote immutability, insufficient funds, replay/idempotency, timeout/reconcile, cancel states, partial result, artifact digest mismatch, incompatible versions, forbidden evidence promotion and identical Episode Builder output for equivalent fixtures. Add transport capture, authorization, concurrency and restart/fault injection before real money. Until the missing Deliver modules and API are available, compatibility means **contract-level target**, not verified runtime interoperability.

## Result acceptance and artifact authority

After execution, `DELIVERED → RESULT_VALIDATED` binds artifact digests, the accepted quote's criteria hash, reviewer identity and PASS/PARTIAL/REJECTED receipt. Provider-reported SUCCEEDED alone cannot unlock success settlement. PARTIAL/rejection follows frozen failure terms. When delivery and acceptance are certain but provider cost telemetry is missing, buyer price remains fixed; this initial policy holds settlement pending cost reconciliation, tracked separately from execution uncertainty. A later policy can separate the settlements only through explicit quote terms.

Artifact hashes prove integrity, not access rights. Resolution applies principal/task/grant checks before opening a URI, allows only authorized storage roots/schemes, rejects traversal and symlink escapes, then verifies size/type/hash. Context grants travel with references; a source locator does not authorize reading the whole file. Implemented local-provider subsets are listed in VALIDATION_REPORT; design names do not imply live services.
