# Repository evidence map

Inspected 2026-09-27. Base commit observed: `8bde17d` (2026-09-07). Working tree contains extensive pre-existing modified/untracked work; this architecture adds isolated files and does not normalize or revert that state. Paths below refer to inspected source, not assertions that deployed services currently behave the same way.

| Surface | Evidence | Reuse decision / limit |
|---|---|---|
| Atlas | `web/package.json`, `web/src/core/*`, `web/src/layers/*`, `web/src/ui/*` | JS static map, timeline, entities, terrain and scene views; research navigation/launch UI. Not an embodied game engine. |
| Historical maps | `etl/historical_maps/README.md`, discovery/routing/pipeline and dated audit documents | Immutable crops, candidates, maps, provenance, research context; tactical terrain requires new review and reconstruction. |
| Driver contracts | `etl/driver_runtime/contracts.py` | Strict Pydantic objects, request binding, provenance, temporal scope, metrics; useful patterns. Wire vocab differs from game contracts. |
| Context packing | `etl/driver_runtime/context.py` | Closed claim+provenance bundles, required anchors, estimated token budgets; lacks game's domain/NPC/time/geo policy registry. |
| Execution/store | `etl/driver_runtime/runtime.py`, `store.py` | Versioned orchestration, reservations, uncertain-delivery reconciliation, checkpoints/outbox; token accounting is not an accepted fixed-price economy. |
| Driver design | `docs/WWII_Driver_Runtime_Codex_Spec_v0_3_HE.md` | Explicitly says design/acceptance target, not all features deployed; legacy CALLS/NEXT semantics remain in this family. |
| Deliver v6 fragment | `bridge-fix/deliver-runtime/aggregation_engine/deliver_registry.py` | Listener bindings, work/context event fields, content-addressed payload references, telemetry; `reinforce_next` explicitly raises. |
| Missing Deliver modules | imports of `.deliver_models`, `.listeners`, `.costs`, `.artifact_store`, `.core_registry` in that fragment | Not present alongside it in this checkout. Cannot instantiate or claim live compatibility. Adapter contract tests must use a captured, reviewed external fixture later. |
| Legacy factual promotion | `etl/driver_runtime/supervisor.py:62` | Sourced candidates can become EXPLICIT_FACT/source_verified, with generated locator and count-derived confidence. Game import must revalidate original evidence; do not adopt flags automatically. |

No root `AGENTS.md` was present at inspection. `bridge-fix/units/AGENTS.md` governs that separate subtree; no edits there are required. The new root guidance points to game docs without changing existing atlas runtime policy.

## What is not present

No `Cargo.toml`/Rust game workspace was found in the project scan; `cargo` and `rustc` were not available on PATH. No complete EpisodeSpec loader, combat simulation, persistent character system, gameplay profiles, engine integration, accepted-price ledger or playable historical episode is demonstrated by the inspected files. Absence in this scoped repository scan is not a claim about all other workspaces or remote deployments.

The local documents and Deliver fragment are enough to define a compatibility boundary, not enough to reverse-engineer a full production Deliver API. This gap is tracked in OPEN_PROBLEMS. Do not copy partial runtime code into the game.

## Baseline verification

Existing tests for Driver contracts, context packing and store passed: **39 tests** using the existing Desktop ETL Python environment plus this repository's `.runtime-deps/driver-runtime`. An initial system-Python unittest invocation could not import pytest-dependent tests; the existing environment resolved that without installing packages. No live Neo4j writes, external model calls, corpus ingestion or paid actions were performed.

Navigation rule: start with this map and the owning document; use `rg` for relevant symbols. Do not preload corpora, technical manuals, all image files or the entire master brief into every agent.
