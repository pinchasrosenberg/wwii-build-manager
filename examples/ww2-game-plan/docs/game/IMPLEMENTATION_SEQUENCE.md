# Implementation sequence and acceptance gates

This sequence follows architecture consolidation and cross-review. Large implementation is deliberately deferred until these decisions and the first historical/experience scope are reviewable. No task starts by constructing all WWII Lego.

| Phase | Work and owner | Acceptance / stop condition |
|---|---|---|
| A — architecture | root + scoped stack/context/history/simulation researchers; independent reviewers | coherent docs, initial schemas, decisions, open gaps, traceability; review findings resolved |
| M0 — contract proofs | context/economy owners | tank/naval isolation; declared interface exception; required context budget failure; fixed quotes/idempotency/overrun; contract validation. Synthetic fixtures only. |
| M1 — engine + experience spike | simulation/experience/asset owners | named target hardware, headless run + playable embodiment, companions, readable responsibility, meaningful local action, quiet atmosphere, save/replay; OpenXR input/camera seams and export/device smoke gate; choose stack from measurements |
| M2 — Episode #1 preflight | historians, terrain/weather, experience designer | source-backed skeleton and equipment; explicit reconstructed gaps; tactical terrain uncertainty assessed; historical and experience scope feasible |
| M3 — first playable vertical slice | builder asks missing Lego owners | EpisodeIntent→research→skeleton→terrain/weather→resolve/gap→EpisodePlan→EpisodeSpec→validation→headless→PlayableEpisode |
| M4 — Episode #2 | same builder and capabilities | second data package loads with same core; quantify reuse vs additions and context/cost; investigate any episode-specific branch/module |
| M5 — persistence/progressive scale | LOD/characters/economy owners | long clock, schedule/relationships/injuries, conservative split/merge, migration/replay checks and renewed ExperienceReview |
| M6 — real Deliver adapter | integration/economy owners | captured real protocol + conformance/fault tests; same builder works with provider swapped; accepted price and telemetry reconciled |

M1 may use a synthetic environment clearly labeled as a technical/playtest fixture. It must not be advertised as a historical Episode. M2 research can run alongside M1 once schema contracts are stable. No engine installation or source downloads are prerequisites for the architecture deliverable.

VR gate clarification for the Lego build catalog: M1 desktop playability and input/camera/asset separation can proceed using synthetic tracked-pose fixtures. Export/device checks should run early when target hardware is available. An unavailable headset remains an explicit open risk, not a desktop blocker or a passed test; target-specific VR compatibility, stereo rendering, performance and comfort claims require the real device gate. The reusable component inventory and scoped dispatch packets are in [LEGO_BUILD_CATALOG_HE](LEGO_BUILD_CATALOG_HE.md).

## M3 minimum scope

Small period-grounded sector; infantry; one machine gun; one vehicle; basic data-driven ballistics, suppression, injury and AI; one weather state; one EpisodeSpec; at least one explicitly reconstructed field; optional accuracy inspector; one real capability gap and a simulated Deliver build request. Also required by the experience steering: embodied controls, recognizable squad members, a quiet activity, a meaningful local choice/consequence, readable orders, offscreen world progression, basic audio/light/animation, save/resume and a desire-to-continue playtest.

Choose vehicle and weapon after evidence review. If a required historical presence is unsupported, choose another supported sector or keep the spike synthetic; do not fill a historical OOB with convenient assets. No multiplayer, full VR release, full persistent LLM dialogue, detailed aircraft/naval physics or continent-wide tactical terrain in the first slice.

## Proposed quantitative gates (targets, not measured achievements)

Name CPU/GPU/RAM/OS and resolution before the spike. Initial target: stable 60 Hz presentation at 1080p on selected midrange hardware, p95 frame ≤16.7 ms, no repeated >50 ms streaming hitches, memory ≤4 GiB for the small slice. Target headless 20-minute slice at ≥10× real time with a stated entity count and disabled rendering. These targets can be revised with a documented product tradeoff; do not choose an arbitrary demo count to claim scalability.

Same build/platform+seed+inputs produces identical canonical authoritative state hashes across repeated runs. Cross-platform bitwise determinism is not promised until demonstrated. Save/reload preserves IDs, supplies, casualties, orders, companions and historical envelope state. ExperienceReview uses human observations as specified in EXPERIENCE_DESIGN.

## Episode #2 measurement

Report reused capabilities/version IDs; extended/new capabilities; changed executable lines; new asset bytes; research sources/claims/hours; loaded context refs/estimated and actual tokens; paid cost if any; tests. Use denominator definitions: capability reuse = reused required capability versions / all required capability versions, not all registry entries. Do not game metrics by counting unused dependencies. Target no episode-specific code branch and no core loader modification; a justified new general capability is acceptable. Record measurements as null until run.

## Task handoff packet

Each bounded implementation work item contains only invariant refs, task goal, owning domain, interface versions, evidence refs, allowed read/write paths, acceptance checks, budget/deadline and expected structured output. Owners request cross-domain changes. Root serializes shared schema edits and integrates after independent review. New roles are opened only when an actual gap or review requires them.
