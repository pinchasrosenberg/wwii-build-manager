# Historical fidelity and reconstruction contract

Status: proposed architecture, 2026-09-27. This document specifies the game data boundary; it implements no importer, renderer, simulation, or historical claim. Canonical machine contracts belong to the game schema package. The bounded repository evidence behind this design is in [HISTORICAL_RESEARCH.md](reviews/HISTORICAL_RESEARCH.md).

## Three stores with one-way derivation

| Store | Contains | Must never contain |
|---|---|---|
| `HistoricalTruth` | Immutable source observations, separately asserted historical claims, review decisions, competing claims, and versioned accepted views | Gameplay outcomes promoted as history; an inference disguised as a source passage |
| `Reconstruction` | Explicit assumptions, uncertainty envelopes, terrain hypotheses, unresolved strength allocation, reconstructed agents, scenario alternatives, and derivation recipes pinned to a truth revision | Fabricated unit/person identifiers presented as historical entities; edits to original evidence |
| `GameplaySimulation` | Runtime state, player actions, generated detail, performance approximations, random seeds, and a complete manifest of its pinned inputs | Writes to source observations or accepted historical claims |

`HistoricalTruth` is a typed evidence system, not a promise that every stored claim is true. Accepted facts are a reviewed, scoped view over it. The data flows from evidence to accepted claims to reconstruction to a session. A session may emit diagnostic contradictions and research questions for later review; it cannot update history. Deliver is an optional downstream consumer of a game export, never the game's identity provider, persistence owner, runtime dependency, or release gate.

The product is an embodied game experience: the player belongs to a unit, meets persistent people, performs useful activities, and makes consequential local choices. These evidence controls support the living world; they are not a requirement to turn play into a museum tour or expose provenance panels in normal interactions. Inspectable evidence is available through separate review/debrief tools. Historical review and `ExperienceReview` are independent release gates: a well-sourced but inert information scene fails the latter, while a compelling but historically incompatible scene fails the former.

Source bytes, source versions, passages, crops, literal readings, and review receipts are append-only and content-addressed. A correction creates a new assertion linked with `supersedes`; it does not rewrite an original reading. Mutable indexes such as `current` point to an immutable revision. Export manifests carry hashes and complete dependency versions so provenance survives without a running graph database.

## Field-level epistemic state

Each claim-bearing field has a value or explicit absence, units where applicable, scope, time semantics, evidence references, and epistemic metadata. A historical unit can have a documented designation, disputed location, reconstructed headcount distribution, and unknown equipment mix. An entity-wide confidence score cannot represent that state.

The required terms are orthogonal labels, never a scalar ranking:

| Axis | Values and meaning |
|---|---|
| Assertion basis | `DOCUMENTED`: a retrievable source explicitly asserts this field; `RECONSTRUCTED`: inference constrained by evidence; `SYNTHETIC`: generated design content without a historical assertion; `UNKNOWN`: no supported field value |
| Verification | `VERIFIED`: a named/versioned review passed an explicit scope; otherwise unreviewed, rejected, or review-required metadata |
| Confidence | `HIGH_CONFIDENCE`, `PROBABLE`, or unassessed; each assessment names its method, supporting evidence, limitations, and applicable scope |
| Dispute | `DISPUTED` with competing claim references, or an explicit assessed/unassessed dispute state |

`DOCUMENTED + VERIFIED` may mean “the map contains this label,” not “this unit was at this exact coordinate.” `RECONSTRUCTED + HIGH_CONFIDENCE` remains an inference. `DOCUMENTED + DISPUTED` retains both source statements. `VERIFIED` requires a review record specifying whether it checked transcription, identity, location, date, material, or another property. A synthetic artifact may pass technical QA without acquiring historical verification. Model/OCR scores remain algorithm metadata and never map directly to historical confidence. Unknown values are null/absent with a reason; zero is a measured or asserted zero, not a missing-value substitute.

Strong evidence is a policy decision for a particular claim and use, based on source relevance, explicitness, identity resolution, temporal/spatial applicability, independent corroboration where needed, and unresolved contradictions. It is not “all scores above 0.8.” Several copies of one report count as one evidence lineage. An adversary's map can document what its author believed without proving the depicted opposing unit's real state.

## Separate pipeline stages and release gates

| Stage | Durable output | Acceptance boundary |
|---|---|---|
| 1. Source discovery | Catalog record, archive/item identifiers, original authority, host, rights notes, retrieval receipt, immutable asset/hash, coverage/gaps | Item identity and accessible provenance; an archive hit is not a historical claim |
| 2. Extraction | Literal text/symbol/line observation, original pixel/page locator, extractor version, alternatives and explicit gaps | Source bytes and geometry agree; headers, legends, stamps, place labels and unit symbols are distinguished |
| 3. Georeferencing | Separate transform/model, control-point lineage, CRS, source/target coordinates, uncertainty and extrapolation flags | Fit diagnostics and independent spatial validation appropriate to the intended scale; accepted model is still a derived location |
| 4. Claim construction | Subject/predicate/value plus time, population, perspective, source references, identity candidates and epistemic fields | Explicit claims separate from interpretation; an entity match does not itself establish participation, position, strength or movement |
| 5. Conflict analysis | Competing claim sets, dependence graph, incompatibility reasons and unresolved research tasks | Preserve alternatives; do not average incompatible dates, denominators or identities |
| 6. Verification | Signed/versioned review receipt with scope, method and admissibility decision | Review the exact source locator and claim; repeated model agreement is not independent corroboration |
| 7. Reconstruction | Feasible assumptions/envelopes, provisional residual pools, physical/visual constraints, derivation graph | Cannot contradict strong accepted evidence; every added historical-looking detail has an explicit basis |
| 8. Episode packaging | Pinned manifest, source coverage, hard anchors, uncertainties, allowed deviations, unresolved blockers | Coverage is adequate for the proposed playable scale; runtime/visual fidelity never substitutes for historical coverage |

The stages have distinct identifiers and receipts. Extraction completion, tile coverage, graph insertion, georeference acceptance, identity confirmation and playable release are different states. A gap is a first-class output; it must not disappear when a later stage succeeds elsewhere. Discovery/search workers have no permission to write accepted historical claims.

The separate `ExperienceReview` checks an embodied first-person/unit role, understandable immediate tasks, meaningful local choices, responsive people and activities, and a rhythm that includes waiting, anticipation, conversation, maintenance and recovery as well as danger. It checks persistent consequences across long episodes and whether evidence presentation interrupts ordinary play. Its reviewer cannot waive historical constraints, and the historical reviewer cannot waive this experience gate.

Existing historical-map evidence and its deterministic candidate georeference can be reused through an adapter. The adapter must retain all original statuses, dimensions, locator conventions and uncertainty. It must not import `AtlasFact`, `EXPLICIT_FACT`, `safe_for_factual_answer=true` or `validation_status=source_verified` as proof of game verification. The legacy supervisor can set these through automatic source-backed acceptance, including a fallback locator. Such records enter a review queue until the exact underlying evidence is retrieved, its source hash/version checked, its locator resolved, and transcription, identity, scope and temporal semantics independently assessed. A missing locator or circular claim-to-claim citation fails import into the accepted view. No existing runtime code is changed by this proposal.

## Place plus time: terrain and geographic uncertainty

`Place` gives stable geographic identity and supported naming histories; `PlaceState` describes a property at a historical time or interval. The same coordinate does not imply the same road, bridge, building, river channel, vegetation, ownership or military significance across dates. Modern geographic data occupy a separate baseline layer with their own acquisition date, resolution and attribution.

Terrain reconstruction records: place/region identity, historical effective time and precision, observation/publication times, source lineage, horizontal and vertical reference systems, geometry, uncertainty, surface/material classification and the basis of every time-sensitive feature. Keep at least these layers distinct:

1. Modern/reference elevation and geographic registration.
2. Historically evidenced terrain/features, including roads, buildings, bridges, land cover, fields and waterways where supported.
3. Evidenced temporal changes, damage and temporary works.
4. Reconstructed microterrain and visual filling, bounded by known features and labeled as reconstruction or synthesis.
5. Simulation collision/navigation approximations with their resolution and relationship to the visual surface.

Source-pixel geometry is immutable and tied to exact image dimensions, origin and `[x,y,width,height]` convention. A crop/resize/rotation needs its own reversible transform. WGS84 estimates do not replace pixel observations. Control-point uncertainty, projection error, source cartographic generalization, symbol meaning and extrapolation are separate error contributors; a fit residual alone is not total historical accuracy. A command-post marker is not a polygon containing every soldier.

Current driver quality labels permit kilometre-scale cross-validation error, and the inspected August 26 pilot tag declares 22 km approximate horizontal error. These inputs can support source exploration and an operational envelope. They cannot locate a tactical street, trench, vehicle or soldier. A visually detailed surface must retain its coarser evidential uncertainty; adding polygons does not reduce it. Tactical release requires separately justified local registration and evidence at the chosen playable scale.

Roads from modern basemaps, plausibly drawn roads from map overviews, and copied traces must not become wartime facts. A transferred line preserves its parent trace and transfer model; copies are not independent observations. Uncertain geometry can be represented as an envelope or alternatives. If two geometries are genuinely incompatible, retain the conflict rather than making a falsely precise mean line.

## Weather is a dated physical state

Weather fields use observation time/window, location/coverage, measurement height or level when relevant, units, source/instrument or model, and uncertainty. Station readings, regional reports, interpolation and scenario assumptions are different evidence types. Season, a photograph's appearance, or a narrative phrase alone does not justify an exact hourly weather series. Coarse daily observations do not produce invented minute-by-minute measurements.

One versioned `WeatherState` drives rendering and physical effects through named models:

| State/input | Model relationships to evaluate | Consistency rule |
|---|---|---|
| Precipitation and recent history | Soil wetness, drainage, mud formation, traction, mobility and track persistence | A wet visual surface and terrain resistance derive from the same material/water state |
| Temperature and thermal history | Freeze/thaw, snow/ice persistence, equipment and human exposure models where implemented | Do not infer frozen ground from instantaneous air temperature alone |
| Wind | Smoke/dust advection and dispersion; ballistic effects where simulated | Visible smoke and visibility calculations use compatible wind inputs |
| Fog/cloud/illumination | Sight and identification ranges, contrast and shadows | AI visibility and player visibility share the same physical bounds |

These are proposed model dependencies, not claims about any selected historical day. Models need bounded validation, explicit simplifications, and separate evidence for their numerical coefficients. Unknown weather can become a declared reconstruction scenario with a sensitivity range. If weather materially determines an anchor's feasibility, insufficient evidence blocks that fidelity level instead of being silently filled by a pleasing preset.

## Equipment variants: visual and simulation identity

An `EquipmentVariant` is identified by variant and relevant configuration, not merely family name or mesh filename. Its availability is separately evidenced for date/window, unit or supply population, theater, and role. Earliest manufacture, delivery, assignment, and observed combat use are different claims. “Available somewhere by this date” does not establish that this particular unit possessed it.

Versioned variant fields may include chassis/model, weapon/ammunition configuration, armor/material and geometry, propulsion/mobility, crew requirements, optics/communications, markings and appearance. Each field retains its own evidence or reconstruction status. Availability can be unknown or disputed; an unknown count is not unlimited stock. An episode inventory pins the variant, configuration, quantity interval, date/unit/theater applicability and provenance.

Both the renderer and simulation consume a shared `variant_revision` and configuration digest. A mesh with one gun/armor layout must not use another variant's penetration, protection or mobility profile without an explicit, reviewed approximation. Cosmetic substitutions and LOD simplifications are declared separately and must preserve features material to gameplay and recognition. No missing variant is silently replaced with a later model. A generic placeholder remains visibly labeled in development and blocks historical release where variant distinction matters.

## Battle skeleton, uncertainty envelopes and player agency

An episode separates the macro historical trajectory from uncertain local detail. Its skeleton contains source-backed participants/roles where known, start/end conditions, meaningful phase/event constraints, place/time envelopes, command/availability constraints, and external events. Every anchor references accepted claims and expresses only the precision they support.

An anchor can be a partial order (`A before B`), a date, a broad interval, a location envelope, a presence/absence constraint or a supported outcome. Do not fabricate an exact clock time merely because the scheduler wants one. A runtime may select a deterministic illustrative schedule inside an admissible window; that selected instant belongs to `Reconstruction` or `GameplaySimulation`, not `HistoricalTruth`. Unknown time zones remain unknown, and source-reported noon must not be serialized as noon UTC without evidence.

The scenario author declares a player influence domain and a protected anchor set before release. The local domain can include routes, timing within allowed windows, cover use, ammunition expenditure, local survival, tactical objectives and limited equipment loss. Its causal reach must be checked against the protected anchors. Finite resources, travel times, reinforcement schedules and counterpart behavior constrain feasible solutions; a scenario cannot claim open agency while permitting only an undisclosed scripted answer.

If a player action or new evidence makes the anchor set infeasible, the session emits an `AnchorConflict` with conflicting anchors, observed/simulated causes, relevant source precision, constraint checks and the selected response. Allowed responses are explicit episode policy:

| Mode | Conflict response |
|---|---|
| Historical bounded play | End or pause the playable segment with a clear divergence explanation; optionally offer a restart/checkpoint. Continue an independently labeled historical account outside the player's causal domain only when that account remains coherent. |
| Explicit counterfactual branch | Fork the simulation, preserve the moment and cause of divergence, and mark subsequent output as counterfactual. The original historical account remains available. |
| Reconstruction review | If the contradiction exposes an inconsistent assumption rather than a player divergence, stop certification of that reconstruction and request a new revision. |

Do not secretly revive a killed historical actor, spawn unlimited reserves, teleport a unit, erase player actions, fabricate an off-screen cause, or retroactively rewrite evidence to force convergence. External events may be fixed only if their independence from the playable causal domain is defensible. Local losses cannot quietly exceed supported force/availability bounds. The exact scope of the episode must be narrowed when strong anchors and broad player powers are incompatible.

Persistent NPCs have stable scenario identities, relationships, roles, memories of session events, physical state and lifecycle records. Historical-person links are optional and require evidence; a persistent synthetic character does not need a fabricated historical biography or service number. Quiet routines and conversations can be reconstructed or synthetic while obeying documented unit, setting, equipment and schedule constraints. Synthetic dialogue is never archived or presented as a historical quotation. Optional LLM dialogue may vary expression within these constraints; it cannot create a new order, event, casualty, equipment allocation or historical fact without the authoritative game systems.

A death, absence, transfer or replacement has lasting consequences in the session. Replacement receives a new identity and an evidenced or declared reconstructed source/timing; neither relationships nor memories silently reset to make the scene convenient. Long episodes preserve routine, maintenance, rest and social continuity across time compression. If a historically necessary actor can be killed through permitted player actions, the author must resolve that design conflict before release by narrowing the defensible causal domain or declaring the conflict/fork policy; hidden invulnerability and resurrection are not historical solutions.

## Experience profiles do not rewrite history

`Easy/Experience`, `Standard`, `Simulation` and `High Fidelity` are gameplay profiles. All consume the same pinned historical identities, events, setting, equipment applicability and evidence revision. These labels do not change a field's historical status or bypass either release gate.

A profile may reduce local player lethality, clarify navigation, simplify controls, provide perception/accessibility cues, reduce procedural workload or adjust permitted recovery/checkpoint behavior. Store each assistance as a versioned `GameplaySimulation` overlay, with its mechanical effect, not as revised armor, altered historical weather, a newly issued weapon, a different unit or a changed historical event. The simulation records where assistance alters physical responses; it must not export those outcomes as historical capability evidence. Local consequences still obey the episode's published anchor/conflict policy.

For example, clearer navigation can reveal a route already available to the player's role without inventing a wartime road. A reduced incoming-damage mechanic can help a player survive a local exchange without claiming that the historical uniform stopped those rounds. An easier profile cannot erase a documented historical event. If permitted player actions create an impossible historical state under any profile, the same explicit conflict response applies. `High Fidelity` can demand more player procedures and tighter physical models, but cannot convert unknown troop positions or weather into facts.

## Strength reconciliation without invented units

The following is a contract fixture, **not a historical count or episode claim**. A source-supported parent total is 10,000 persons. Evidence assigns 8,400 persons to known children. If date, reporting window, strength definition, population inclusions/exclusions and parent-child membership are compatible and children do not overlap, the arithmetic residual is 1,600.

Maintain separate records:

| Item | Layer and meaning |
|---|---|
| Total: 10,000 | `HistoricalTruth` claim with its original source, date and population scope |
| Assigned to evidenced children: 8,400 | Accepted compatible child claims plus an auditable aggregation, with duplicate/overlap checks |
| Unallocated residual: 1,600 | Derived reconciliation quantity; historically unassigned, not an identified formation |
| Runtime allocation of residual | `Reconstruction` pool with a scenario-local ID, allocation recipe and uncertainty; any instantiated agents are synthetic/reconstructed actors |

An exact arithmetic residual does not verify the soldiers' identities, organization, locations, roles, equipment or presence in the playable sector. Keep `historical_unit_id=null` for the residual. Do not invent a real-looking battalion number or count the residual as another documented unit. Simulation-only handles are namespaced and cannot resolve through the historical entity registry. Any plausible role/equipment mix must obey supported totals and availability but remains labeled reconstruction. Unknown roles may stay unallocated if detail is unnecessary.

If the inputs are intervals, subtraction produces a bounded possible residual subject to compatibility and overlap constraints; uncertainty cannot be discarded by using midpoint counts. A negative residual, incompatible stock/flow definitions, different dates, or partial membership produces `DISPUTED`/reconciliation-required status, not a forced zero or invented balancing unit. Assigned, present, effective, ration, authorized and combat strengths are different populations. Never add a parent and its children, sum consecutive stock snapshots, equate a symbol with a full establishment, or distribute theater totals into local formations by area.

The existing reviewed CMH table provides end-of-month U.S. Army ETO assigned-strength snapshots with specific inclusions/exclusions. It is not evidence for the fixture, local battle manpower, or daily strengths between month ends.

## Progressive fidelity and contradiction checks

Fidelity describes representational detail and physical resolution. It does not rank historical truth. Progression is per region and per field, so a high-quality model can legitimately retain unknown unit composition.

| Gate | Intended artifact | Required evidence relationship |
|---|---|---|
| Source scaffold | Inspectable source sheet, literal observations, coverage and gaps | No implication that the extraction is complete or claims resolved |
| Operational reconstruction | Place/time envelopes, accepted participants and macro constraints | Source precision respected; disputed alternatives remain separate |
| Tactical reconstruction | Local terrain, date/unit/theater equipment, local force bounds | Registration and provenance support the chosen scale; unresolved material assumptions disclosed |
| Simulation refinement | Physics, perception, behavior and visual detail | Shared state/variant contracts; sensitivity checks against historical envelopes |

Every refinement computes a semantic diff against its pinned parent. Protected accepted claims are invariant unless replaced through a reviewed truth revision. Unsupported detail can be refined within its envelope, but cannot cross a strong constraint. A newly documented road can replace a reconstructed road through a versioned dependency update; it cannot coexist as an unexplained second road just to preserve navigation. Higher frame rate, denser terrain or more agents does not improve source certainty.

## Revision, saves and migration

An episode manifest pins source hashes, accepted-truth revision, reconstruction revision, equipment/terrain/weather model revisions, policy version, simulation build, and seeds. A save additionally pins actor state and player event history. Published evidence remains append-only even when a source URL changes; new bytes receive a new version. Rights/availability metadata may restrict new distribution without erasing the audit trail.

New evidence triggers dependency analysis: list affected claims, terrain cells, anchors, equipment/strength allocations and episode builds; recompute only dependent interpretations; then run historical compatibility checks. If it changes a protected anchor or materially changes the world, publish a new episode revision. Existing saves remain reproducible under their pinned package when available and display their evidence revision. Do not silently reinterpret a past playthrough as occurring on a newly corrected historical map.

Migration is an explicit versioned operation with before/after manifests, transformations, preserved provenance, resource/conservation checks and a rollback path. Compatible cosmetic or numerical refinements may migrate under policy; a broken anchor, disappeared bridge, renamed/reidentified unit, or changed strength population requires scenario review and may require restart. A save fork may use the new reconstruction, but the original remains identifiable. Player outcomes never become training evidence for what historically happened.

## Architecture acceptance cases (not implemented tests)

1. A legacy auto-promoted claim with a generic locator is rejected from the accepted game view; its original candidate and provenance survive review.
2. A high OCR score on a legend becomes a verified transcription only, not a formation presence claim.
3. A rejected georeference emits a gap; a kilometre-scale accepted candidate cannot enter a metre-scale tactical manifest without additional evidence.
4. A day-only source creates a day envelope and no invented clock/time zone; two snapshots do not imply continuous occupancy or a straight-line march.
5. A modern road remains modern/reference data until wartime existence is evidenced or explicitly reconstructed.
6. Competing source claims remain distinct and correlated copies do not count as independent confirmation.
7. The 10,000 / 8,400 fixture yields a 1,600 unassigned reconstruction pool, no invented historical unit, and no double counting.
8. A renderer/simulation variant mismatch or unit/date/theater availability contradiction blocks packaging.
9. A player's action that makes protected anchors impossible triggers the declared conflict response with a preserved event trace.
10. A truth revision cannot mutate a pinned save or overwrite source evidence; an incompatible migration is rejected with affected dependencies.

These cases require implementation and measured outcomes before release. No new test suite or pipeline execution is claimed by this document.
