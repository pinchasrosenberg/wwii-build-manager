# Domain registry

Status: finite initial registry for routing and ownership. This is a design inventory, not an assertion that all domains are implemented or should have active workers. Extend it through an explicit registry change with owner, interfaces and isolation tests.

## Registry rules

Every context item and capability has one primary owning domain. Cross-domain applicability is represented by named interfaces or grants, not a list that silently grants all domains. Subdomains narrow ownership; for example a tank task uses `ground_vehicles/tanks`, while a naval task uses `naval/ships`. Shared historical entities have stable IDs across domains without making every domain's records visible.

The `domain_specialist` role instantiates only a selected domain/subdomain for the duration of a bounded task. The root uses the registry's summaries and dependency edges to allocate work. There is no always-running specialist per registry row, and no requirement to construct every domain before the first playable prototype.

## Initial domains

| Domain ID | Owns | Public interface examples | Default exclusions |
|---|---|---|---|
| `historical_evidence` | Source metadata, locators, explicit claims, verification records, contradictions | Evidence bundle lookup; claim state and provenance; dated source snapshot | Global unrestricted corpus dumps; source text outside the request |
| `geospatial_temporal` | Terrain geometry, coordinate transforms, map extent, dates and precision, geographic applicability | Terrain sample; coordinate transform; evidenced temporal overlap | Vehicle/naval implementations; fabricated positions or interpolated history |
| `ground_vehicles` | Tanks, armored cars, trucks and mobility subsystems; configurations and vehicle damage state | Mobility envelope; mass/dimensions; mount and armor geometry; vehicle state | Naval hull/fire-control, aircraft performance, unrelated weapon source libraries |
| `weapons_effects` | Weapon/ammunition characteristics, firing and damage-effect contracts, ballistic assumptions | Mount compatibility; shot/effect query; ammunition type and units | Whole tank, ship or aircraft implementation; unsupported penetration certainty |
| `infantry` | Individual/squad capabilities, equipment use, movement and formation behavior | Squad action; carried load; formation footprint; casualty state | Global command truth, hidden enemy state, vehicle engineering details |
| `aviation` | Aircraft state, flight and air mission capabilities | Payload/range envelope; sortie interface; observation delivery | Naval and tank design internals; future or undelivered reconnaissance |
| `naval` | Ships, sea movement, naval operations and ship-specific systems | Vessel transport limits; sea-route availability; naval platform state | Tank/aircraft internals; unrelated terrestrial sources or command intelligence |
| `logistics` | Stocks, demand, supply routes, throughput, maintenance and transport allocation | Demand/stock/throughput; delivery event; load-capacity request | Full vehicle/ship design; assumed supplies inferred solely from route proximity |
| `command_organization` | Unit hierarchy, orders, organizational assignments, communications and delivery semantics | Versioned order; actor authority; delivery/acknowledgment event; dated organization | Omniscient NPC intelligence; tactical presence inferred solely from OOB membership |
| `characters` | Stable identity, commitments, actor memory, relationships and their continuity across scenes/saves | Actor knowledge projection; relationship event; remembered interaction; validated dialogue/action proposal | Another actor's private memory, future knowledge, authoritative state kept only in an LLM conversation |
| `simulation_runtime` | Deterministic state evolution, event ordering, save/replay, visibility enforcement, scenario configuration | Tick/event interface; state snapshot; actor observation projection; seeded replay | Promoting simulated outcomes into historical truth; unrestricted NPC state views |
| `experience_design` | Player role/presence, meaningful activities, pacing and quiet, controls/readability, responsiveness, atmosphere, curiosity, accessibility and profile design | Experience hypothesis; interaction sequence; authorized view model; playtest criteria; independent promotion review | Treating a historical exhibit or graph view as the whole game; bypasses around historical invariants, visibility or game-state APIs |

Additional cross-cutting owners complete the registry without creating always-running workers:

| Domain ID | Owns | Interface / exclusion |
|---|---|---|
| `weather` | Historical weather snapshots and declared simulation effects | Dated local weather sample; cannot replace unknown weather with a documented claim |
| `asset_pipeline` | Models, rigs, animation, materials, sound, LOD and platform/VR import variants | Variant-matched licensed asset manifest; cannot alter historical equipment data |
| `ai_navigation` | Local paths, perception-driven decisions and activity planning | Scoped observations, traversability and intent; no hidden WorldTruth |
| `economy_deliver` | Capability provider, quotes, reservations, investments and settlement | Request/result/cost contracts; no engine simulation internals |
| `context_orchestration` | Policy/index, grants, context selection, handoff and bounded task routing | ContextManifest and expansion decisions; no implicit access or historical truth promotion |

The first playable scope can activate only a subset. A ground scenario might need ground vehicles, geospatial/temporal, weapons effects and simulation runtime, plus scoped evidence, character continuity and experience design. Aviation and naval rows remain registered but inactive unless the scenario requires them. Experience design starts with the player's role and activity loop; independent experience review remains required for promotion.

## Dependency registry

Dependencies are directional named contracts, versioned independently from implementation. A consumer names the interface, purpose, input entity IDs and scope. The producer returns bounded fields with units, coordinate/time conventions, evidence/reconstruction/gameplay labels, assumptions and validity limits. A dependency does not authorize transitive expansion.

| Consumer → owner | Permitted interface | Example of excluded material |
|---|---|---|
| Ground vehicles → geospatial/temporal | Local terrain/slope/contact sample and map transform | Entire theater atlas or unrelated future map layers |
| Ground vehicles → weapons effects | Named gun mount, ammunition compatibility and shot/effect result | Every naval gun document or fire-control implementation |
| Ground vehicles → logistics → naval | Explicit task-scoped load envelope for a named vessel/landing scenario | Naval tactical doctrine, ship weapons and unrelated voyage history |
| Naval → geospatial/temporal | Declared sea area, depth/coast geometry if supported | Unrelated inland vehicle locations |
| Logistics → ground vehicles/naval/aviation | Capacity and consumption interfaces for assigned transport entities | Full platform subsystem design |
| Command/organization → simulation runtime | Timestamped orders and delivery events | Hidden state injected as received intelligence |
| Characters → command/organization/runtime | Delivered order/observation events and authorized actor projection | Future events, another actor's memories or the unrestricted research ledger |
| Characters → experience design | Bounded continuity/relationship cues and interaction affordances | Private NPC thoughts disclosed as player knowledge without a scenario rule |
| Simulation runtime → all active simulation domains | Validated state transition interfaces for that scenario | Unselected domains or production research corpus |
| Experience design → simulation runtime/characters | Authorized player view, command interface and permitted interaction state | Hidden enemy state rendered through debug convenience |

For the tank-to-vessel example, the root can request the naval capacity result directly or let a logistics capability compose it under separately approved grants. This is an implementation choice based on the task, not a compulsory agent chain.

## Scope record

Each registry entry declares a domain version, owner role, owned symbols/entity types and optional subdomains; exported interface versions; permitted dependency interface names; context namespaces; default deny rules; temporal/geographic requirements; and acceptance criteria. Keep the machine-readable seed aligned with these definitions when the router prototype is introduced.

A task narrows that record using explicit entity IDs, time and precision, geometry/region and coordinate system, fidelity ceiling, and budget. A development task may intentionally be timeless or globally applicable; the task must say so. Missing time or geometry cannot silently grant all history or all locations. An NPC task additionally fixes an actor, scenario, simulation cutoff and delivered knowledge set.

An entity's global identifier enables a join; it does not grant access to its complete record. A single tank may have an evidenced historical specification, a reconstruction of an unknown subsystem and a gameplay balance parameter. These remain separate items under the same entity ID with distinct namespaces and provenance.

Profiles (`Easy/Experience`, `Standard`, `Simulation`, `High Fidelity`) belong to gameplay/experience policy. Assistance, subjective lethality and detail settings are transparent and cannot rewrite history. NPC continuity belongs to durable character state regardless of profile; LLM behavior is optional. Experience review considers historical, visual, simulation, character, interaction density, atmosphere, interest, world coherence and performance as separate quality axes with explicit evidence.

## Registry and isolation checks

1. Every registered capability and indexed context item resolves to a known owner and policy; unknown owners fail closed.
2. A tank task cannot retrieve naval bodies through shared words such as armor, gun, engine, speed, or displacement. Denied documents never enter ranking or summaries.
3. A named naval transport dependency returns only the approved capacity interface/result. Its dependencies do not propagate implicit grants.
4. A valid dependency with the wrong version, wrong entity, out-of-scope date or area is rejected as a typed gap.
5. A geography-independent doctrine item needs explicit applicability metadata. Unknown applicability is not global applicability.
6. A dated snapshot is not a validity interval. Unknown or conflicting scope remains visible as uncertainty when the task explicitly permits investigation.
7. Every NPC-facing domain interface passes through the actor knowledge projection. Research access and root role cannot bypass it.
8. Registry expansion does not activate an agent, schedule a listener job, or authorize a paid call.
9. Cyclic interface dependencies are detected and bounded; the root resolves them by a stated fixture, prior-version interface, joint integration task or explicit gap. They do not cause infinite agent spawning.
10. The experience domain cannot be bypassed at promotion because a slice is historically accurate or technically complete. Independent experience review checks meaningful play and presence.

The router's test report identifies which checks are executable now. The full registry is a roadmap for progressive fidelity, not a prerequisite for delivering a bounded working game slice.
