# Architecture and M0 validation report

Date: 2026-09-27. Scope: architecture, initial contracts, offline context routing and simulated provider lifecycle. **No playable episode, headless game simulation, engine build, headset run or human playtest has been completed.**

## Independent work and review

Research ran in bounded tasks: game-stack/official-source research; agent/context architecture; historical reconstruction; simulation/ECS/LOD and Lego. The root inspected the repository and Deliver/Driver boundaries, integrated the contracts, product experience and pricing. Agents received relevant invariants/files and scoped ownership, not the entire master brief. Later user steering added game-first experience and practical future VR portability.

Independent findings and dispositions are retained in [ARCHITECTURE_REVIEW](reviews/ARCHITECTURE_REVIEW.md), [CONTRACT_REVIEW](reviews/CONTRACT_REVIEW.md) and [FINAL_INTEGRATION_REVIEW](reviews/FINAL_INTEGRATION_REVIEW.md). Findings drove preflight/promotion separation, explicit result acceptance, authorized artifact resolution, temporal parsing, immutable quote money, status/gap consistency and bounded NPC grants. Source observations and limitations are in [HISTORICAL_RESEARCH](reviews/HISTORICAL_RESEARCH.md).

## Checks

| Check | Result / scope |
|---|---|
| Existing Driver contracts/context/store | **39 passed** using existing local Python environment. No full-regression or live deployment claim. |
| New M0 suite | **47 passed in 0.17 s** in the integrated pytest run: 10 contract tests, 18 router cases, 19 provider tests. |
| Schema library | Draft 2020-12 shape checked; 17 requested top-level contracts, 36 definitions including helpers; entrypoint required. Python enforces additional semantic checks. |
| Synthetic EpisodeSpec | Passes explicit EpisodeSpec JSON/Python entrypoints. Terrain and initial-state artifact digests/sizes checked against local bytes. No historical certification or runtime capability set. |
| Context isolation | Targeted proof covers tank/naval inverse isolation, no unrelated aviation/episode/time/area, exact interface exception, mandatory closure, estimated budget, stable selection and person knowledge cutoff. |
| Historical/source review | Legacy auto-promotion and coarse maps explicitly barred from automatic game truth/precision. Conditional historical seed only; no battle/terrain content certified. |
| Engine/VR research | Official-source comparison; Godot/OpenXR selected provisionally. No download, benchmark, export or device result. |
| Local links/schema refs | **PASS** across 26 Markdown documents; local JSON Schema references resolve. External citation content was researched separately. |

The first system-Python baseline attempt could not import pytest for one module. The existing Desktop ETL environment provided pytest; the successful 39-test run supersedes that environment error. No package installation was needed. New requirements record the libraries used, and `game/README.md` contains the full pytest command so function-based router tests are not silently skipped by unittest discovery.

## Observed synthetic examples

[Machine-readable M0 results](reviews/M0_RESULTS.json) record actual local calls. Tank selection contained only `ground_vehicles` (886 estimated tokens); naval selection contained only `naval` (982 estimated tokens). Granting the exact transport interface added that interface (1,004 estimated tokens) without ship/hull implementation. Counts include the serialized manifest estimate and supplied payload estimates, not provider usage. The emitted manifests are under `game/examples/`.

The provider quoted 100 TEST_CREDIT, recorded actual cost 130 and settled buyer payment at 100, with provider loss 30. One execution and one separate synthetic review occurred. Duplicate/race/failure cases are covered by the 19 provider tests. These numbers describe test fixtures, not model pricing or a commercial prediction.

## Demonstrated subset and limits

The router selects metadata/references from a trusted in-memory index. It does not verify source bytes, enforce OS access, query a graph, run embeddings or measure actual provider tokens. It fails unsupported temporal/geographic cases rather than pretending to resolve uncertainty. Its scope is smaller than the production context design.

The provider simulator uses synthetic TEST_CREDIT, trusted local fixtures and process-local state. It does not invoke paid work, operate a durable financial ledger, authenticate real counterparties, reconcile remote execution, support production refunds or guarantee crash recovery. The concrete supported lifecycle and test cases are in its tests. Real Deliver compatibility is a target contract; missing runtime/API modules still block interoperability certification.

Historical admission, asset rights, equipment mesh matching, semantic reference resolution, long-horizon LOD, replay, NPC continuity, performance, VR comfort and ExperienceReview remain implementation acceptance gates. Missing results remain unknown. A successful schema/test is not historical verification or proof that the game is fun.

## Architecture completion

Delivered design covers repository scan, current stack evaluation, domains, context/roles, Lego, initial contracts, EpisodeSpec, Deliver/economy boundary, progressive fidelity, simulation LOD, experience/VR design, MVP sequence, uncertainties and requirement traceability. Production-open items have owners and gates in OPEN_PROBLEMS. Large game implementation starts with the measured M1 slice, not a claim that this M0 artifact is already PlayableEpisode.

Final independent integration review reran all 47 M0 tests successfully (0.15 s) and found no architecture/M0 blocker. One nonblocking limit remains: the router hashes the entire trusted index, so an out-of-scope index edit can change the fingerprint. Denied reference metadata/content stays outside the emitted packet, but this is not a strong information-flow noninterference guarantee. Partitioned private-index fingerprints are a later production concern.
