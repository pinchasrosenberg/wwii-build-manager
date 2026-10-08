# Final integration review — architecture and M0

Reviewed: 2026-09-27. **No blocking inconsistency found in the reviewed architecture/M0 scope.** The current artifacts justify an architecture deliverable and narrow offline contract proofs. They do not establish a playable game, historical episode, engine benchmark, headset compatibility test or production Deliver integration.

This reviewer inspected work owned by the root and other agents. The reviewer previously authored STACK_EVALUATION and VR_READINESS; this review checks their adoption in other documents, not independent verification of its own engine research claims.

## Scope and findings

| Boundary | Review result and evidence | Limit retained |
|---|---|---|
| Stack and future VR | MASTER_ARCHITECTURE, IMPLEMENTATION_SEQUENCE, EPISODE_SCHEMA and game/README consistently adopt provisional Godot/OpenXR. M1 requires presentation/input seams and an export/device smoke gate. The architecture explicitly avoids FFI merely to preserve Rust. | The initial isolated typed Godot module and shared live-headless/backend choice are design decisions. Rust extraction is optional later work. No engine, export, physics replay or headset result is claimed. Hardware-dependent testing remains unperformed. |
| Game experience | EXPERIENCE_DESIGN requires embodiment, companions, quiet activities, consequential local choices, audio/light/animation, readable orders and an independent playtest. The formative gate is at least three unfamiliar testers, all able to name their role and a consequence, at least two wishing to continue, with no blocking control/readability failure. | These are proposed gates, not observed outcomes. Headless tests cannot establish product enjoyment or comfort. |
| Historical truth | The master, episode schema and Python contracts distinguish evidence/review, explicit reconstruction and gameplay state. Unknown historical claim values must be null; documentation/reconstruction/dispute states require their respective supporting fields. Promotion requires additional semantic and independent review gates. | Reference strings and schema validity do not establish source support, reviewer independence, temporal applicability, a correct equipment mesh or a historically admissible episode. The synthetic fixture cannot be promoted by passing tests. |
| Context caller versus grant | Router request fields are checked against separately supplied trusted grant and policy. Changing role/task/entity/time/geography cannot enlarge the grant. Exact references, domain ownership and named interface dependencies precede selection. An omitted mandatory dependency fails rather than silently disappearing. | The caller providing policy/index/grant/clock is trusted. This proves selection under that premise, not authenticated grant issuance, revocation, OS access or authorization of fetched bytes. |
| Manifest metadata | The emitted effective grant contains selected references/domains and requested entities, rather than copying the broader caller grant. An independent sentinel probe confirmed that unrelated grant references, domains and entity IDs are absent from serialized output; denied item metadata was also absent. | The entire trusted index contributes to `index_snapshot_hash`. A denied-entry change changes that opaque digest. Do not claim that the receipt reveals nothing about changes outside the selected scope; principal-partitioned indexes/audit receipts remain a production concern. This does not expose the denied item text or grant broader access. |
| NPC knowledge and bundles | Tests cover delivered observations/orders/memories at the actor cutoff, exclusion of later/other-person/hidden information, a narrow neutral-instruction exception, complete provenance closure and mandatory budget overflow. Selection is stable under index permutation and identical duplicates. | The proof trusts metadata and token estimates, supports restricted time/geography cases, and does not resolve artifact bytes, persist NPC memory or measure provider tokens. Its typed routing errors are the narrow M0 boundary, not a complete production gap/resolver service. |
| Provider integration | The process-local provider imports game contracts, not Deliver/Driver internals. Quote/scope/version binding, detached copies, accepted-order authorization, separate result review, fixed price, cost reconciliation and single-process idempotency have executable tests. Provider SUCCEEDED does not authorize successful settlement. | Trusted synthetic callbacks/reviewer and TEST_CREDIT only. There is no durable ledger, authenticated counterparty, external execution, secure artifact resolver, crash recovery or production cancellation/refund. Unsupported cancellation leaves holds explicitly unresolved. |
| Release sequence | Preflight precedes an unpromoted playable candidate; independent human ExperienceReview precedes promotion. M1 may use an explicitly synthetic environment; M2 supplies historical preflight; full VR release and continent-scale implementation are deferred. | The proposed numeric performance, determinism, save/replay and Episode #2 reuse targets remain unmeasured. |

The whole-index digest observation is a limitation of the advertised trusted in-memory proof, not a request to implement a production security service in M0. Keep the visible-grant reduction when adding a resolver: a valid hash never authorizes a read, and requester-facing errors must not disclose denied content.

## Executed checks

The current documented command was independently run from the repository root:

```sh
PYTHONPATH=.runtime-deps/driver-runtime <atlas-etl>/.venv/bin/python -m pytest game/tests -q
```

Result: **47 passed in 0.15 seconds**: 18 router cases, 10 contract cases and 19 provider cases. Collection was also inspected to verify all three modules ran, including parameterized/function-based router tests. No package installation was required.

An earlier system-Python/unittest attempt could not import pytest. The current README explicitly names the existing environment and full pytest command; the successful run above resolves the environment/test-runner concern. Unittest discovery is not a replacement for the complete mixed-style suite.

The independent in-memory sentinel probe added unused references/domains/entities to the trusted grant and an ungranted index item. Selected item IDs remained unchanged; the unused metadata did not appear in the manifest JSON; the whole-index digest changed as described above. No persistent reviewer-authored tests or production-code changes were made.

## Handoff

- **task/status:** Independent final consistency review complete; no open blocker for the architecture/M0 deliverable.
- **artifact:** This review only.
- **used_context:** MASTER_ARCHITECTURE, IMPLEMENTATION_SEQUENCE, EPISODE_SCHEMA, EXPERIENCE_DESIGN, CONTEXT_ARCHITECTURE, DELIVER_INTEGRATION, game/README, contracts.py, both prototype modules, all three M0 test modules, prior architecture/contract reviews and the validation-report snapshot. No full original master brief or historical corpus was loaded.
- **evidence:** Read boundaries and tests, 47 passing local cases, complete collection and the scoped metadata probe. Earlier review dispositions were checked against current documents rather than treated as still-open findings.
- **assumptions/uncertainties:** Trusted M0 callers and fixtures; runtime quality, historical admission, live interoperability and actual device behavior remain unestablished.
- **gaps/followups:** Execute the bounded Godot/experience/VR M1 spike, semantic/historical preflight and later production adapter gates in the documented sequence. Keep historical, visual, simulation, character, interaction, atmosphere, interest, coherence and performance outcomes separate.
- **tests/cost:** Offline local checks only; no network, paid work, real currency, graph mutation, engine installation, game build or headset run. No independent token/currency usage telemetry was available.
