# Reusable capabilities and data composition

Status: proposed architecture, 2026-09-27. This is the minimum composition model for a compelling first episode and later reuse; it is not an instruction to build a universal military engine first. [EXPERIENCE_DESIGN](EXPERIENCE_DESIGN.md) owns the player loop and promotion gate; [SIMULATION_LOD](SIMULATION_LOD.md) owns runtime authority, continuity and conservation.

An episode is a versioned composition of existing capabilities, grounded definitions, licensed assets and authored opportunities. A second episode changes those inputs through the same loader. It must not require `battle_x.rs`, an episode-specific engine plugin or a separate executable. A genuinely new mechanic is implemented once behind a general contract, tested independently, then selected by data.

## Three different kinds of building block

| Kind | Runs when | Contract and example |
|---|---|---|
| Research/build capability | Authoring, review or explicit package revision | A scoped request produces a provenance-bearing artifact, test result or typed gap: research a vehicle variant, reconstruct a locality, prepare a rig, validate uniforms. `GameCapabilityProvider` may resolve locally or through a Deliver adapter. |
| Runtime capability | In the installed game, scheduled locally | Versioned systems interpret data: movement, orders, suppression, injury, inventory, perception, bounded dialogue or daily-life schedules. No purchase/research call in a tick. |
| Engine plugin/adapter | Build/startup of a selected client or headless host | Registers an engine subsystem, loader, renderer, audio/controller integration or physics adapter. One plugin can host many runtime capabilities; a capability can have multiple engine implementations. Plugin APIs are not EpisodeSpec APIs. |

Deliver is a replaceable provider for the first row. The local builder must produce and load a usable episode without Deliver, a live research graph or an online model. [DELIVER_INTEGRATION](DELIVER_INTEGRATION.md) owns quotes, reservation, accepted orders, retries and settlement. A runtime dependency cannot accidentally become a paid subscription by resolving a similarly named build capability.

An engine plugin is executable trusted code in a pinned build. An episode is data and vetted assets. Episode loading cannot execute scripts, fetch arbitrary code or register new system schedules. Newly required code goes through the normal implementation/review/build path; a content package may only select installed capabilities and a bounded declarative interaction grammar.

## Composition flow

```text
EpisodeIntent + experience hypothesis + evidence requirements
           ↓ bounded capability resolver
Reviewed evidence / reconstruction / equipment / locality / characters / assets
           ↓ assemble against installed runtime contracts
EpisodeSpec + asset manifest + capability lock + model assumptions
           ↓ structural + semantic + historical + integration validation
Headless fixture + embodied playable scene
           ↓ independent ExperienceReview and remaining promotion gates
PlayableEpisode revision
```

The resolver starts from actual missing requirements. It chooses ready work by declared priority, dependency and budget; it does not always run every specialist in a fixed chain. Each request fixes owner domain, permitted dependency interface, entity/time/space scope, input digests, quality requirements, evidence constraints, deadline and budget. Completion gives an artifact/result with explicit unresolved gaps. Cycles are detected and resolved through a fixture, an already validated prior artifact, a bounded integration task or a surfaced blocker. Retrying the same request/input cannot purchase it twice.

The builder separately checks historical admissibility and player experience needs. Better lighting, sound, animation or meaningful companion behavior may be the highest-value next work once historical gates pass. An expensive research result cannot compensate for unreadable controls; polished visuals cannot validate an unsupported historical identity.

## Registry and manifest requirements

The following are schema obligations for the proposed implementation. They must be mapped to the canonical contracts rather than duplicated under incompatible names. Absence of a field in a current proof schema means the proof is narrower than this design.

| Record | Required meaning |
|---|---|
| Capability definition | Stable ID, semantic version, contract kind (`BUILD`, `RESEARCH`, `RUNTIME`, `VALIDATE`), owning domain, input/output schema versions, preconditions, effects, dependencies, supported detail levels and required permissions. Engine adapters are separately pinned implementation/host records, not an unrecognized capability kind. |
| Applicability and evidence | Entity/variant/date/geographic scope; provenance field references; uncertainty and disputed/unknown fields; approximation method and validity envelope. Applicability may be explicitly timeless/global only when justified. |
| Runtime implementation | Installed implementation ID/build hash, owned components, system phase/read/write declarations, deterministic-domain/RNG declarations, resource accounting, actor-knowledge limits and required fixture results. |
| Content manifest | Content hashes, formats, license/use restrictions, import settings, units/axes/scale, rig/skeleton/material/audio variants and expected runtime IDs. A URL alone is not a content lock. |
| Capability result | Request/input digest, success/partial/failure/reconcile status as appropriate to the provider contract, produced artifacts, used evidence/context, assumptions, tests, unresolved gaps and accepted quote reference when paid. |
| Episode lock | Episode/schema revisions, evidence/reconstruction snapshot IDs, exact selected capability/implementation/content versions, seeds, profile policy, locality/roster/order/envelope inputs and validation receipts. |

Dependency resolution accepts compatible declared ranges during authoring and writes exact versions/hashes at publication. Loaded saves keep the lock they started with. Installation of a new engine plugin or discovery of a better source cannot silently upgrade an active world. Changing component schemas, physics semantics, accepted-effect ordering or RNG algorithms requires explicit compatibility/migration decisions, even if visual assets appear unchanged.

Examples of dependency interfaces are `TerrainSample`, `SurfaceMaterial`, `MobilityEnvelope`, `WeaponMount`, `AmmunitionCompatibility`, `ShotEffect`, `SupplyTransfer`, `OrderDelivery`, `ActorObservation`, `InteractionProposal` and `AnimationActionView`. These names describe bounded contracts; they do not grant access to an entire other domain. A truck requesting ground traction receives the approved terrain sample, not the unrestricted atlas. An NPC receives delivered knowledge, not the truth store. [DOMAIN_REGISTRY](DOMAIN_REGISTRY.md) owns the domain boundaries.

## Equipment is composed from evidence-bearing definitions

Separate four records: historical type/variant definition, reconstruction of missing detail, individual gameplay instance, and visual/audio presentation binding. The first two are reviewed content; the third evolves; the fourth depicts its actual configuration and state.

For a ground vehicle, composition can include chassis dimensions/mass, running gear, engine/drivetrain/fuel model, suspension/mobility approximation, crew stations, visibility, stowage, armor surfaces, weapon mounts, compatible ammunition, carried loads and visual rig/material bindings. A component may be absent, unknown or deliberately simplified. Declaring its absence is preferable to inventing an authoritative value.

The pattern below is illustrative structure, **not researched numerical data for a particular vehicle**:

```text
EquipmentVariant
  variant_id / revision / valid_time_and_place / claim_refs
  dimensions_and_mass: value + units + provenance + uncertainty
  mobility: model_id + parameter_refs + validity_envelope
  protection: geometry/material_refs + approximation_notes
  mounts: mount_id + weapon_variant + orientation_limits
  stores: permitted_ammunition_and_fuel + capacity_refs
  presentation: visual_variant_id + rig_bindings + reviewed_identity_features

EquipmentInstance
  instance_id / variant_revision / owner / location_support
  load_and_resource_ledger / crew_assignments
  component_condition / damage_events / repair_state
```

`Tiger.damage = 100` or a single vehicle health pool is not the foundation of historical effects. A shot combines weapon/ammunition definition, muzzle/trajectory approximation, range, incidence, impacted geometry/material and a bounded effect model. Accepted effects can damage mobility, weapon operation, observation, fuel/fire state or crew. Numeric accuracy is limited by source evidence and model calibration; the interface must report unknown/unsupported cases. A first-slice model may use coarse collision volumes and categorical component states if labeled and reviewed. It must not claim penetration precision that its geometry/sources cannot support.

Small arms and the machine gun likewise combine weapon variant, ammunition, load/feed, aiming/dispersion model, heat/jam model where implemented, reload actions and sound/animation bindings. MVP need not implement every malfunction or thermodynamic effect. Each selected simplification has a declared purpose, valid range and observed consequence, and cannot turn incompatible ammunition into a valid load. Suppression, health and morale are separate: nearby fire can interrupt intent or reduce willingness without subtracting an abstract health number.

Visual/simulation matching is a validation gate. Mesh silhouette, scale, running gear, mount, barrel, armor layout where modeled, uniforms and carried equipment must match the selected identity and time/place. A skin for a different variant cannot stand in silently because the simulation data is correct. Missing representative assets produce a typed gap or a conspicuously declared placeholder in a non-promoted prototype. Appearance also reflects gameplay state: a disabled mount cannot keep aiming as functional, and a dead companion cannot retain a living idle animation.

Source attribution is field-level where it matters. A general manual may support dimensions while an exact local presence remains uncertain. Do not inherit one provenance/confidence label over the whole entity. [HISTORICAL_FIDELITY](HISTORICAL_FIDELITY.md) owns certainty semantics; a cheaper approximation may lower visual/simulation detail without changing evidence confidence.

## Minimum Lego for Episode #1

Only build what the first sourced locality and experience need. The exact battle, weather and equipment variants are selected through preflight; this document does not certify their presence. The required slice includes infantry, one machine gun and one vehicle when the chosen evidence supports them. If it does not, select another supported slice or explicitly revise scope; do not insert an anachronistic asset to satisfy a checklist.

| Reusable block | Minimum behavior for the first slice | Explicitly deferred extension |
|---|---|---|
| Locality / basic terrain | Small traversable area, elevation/collision, basic surfaces/cover, navigation constraints and spatial uncertainty; validated world/local transform. | Continental seamless terrain, comprehensive destruction or arbitrary procedural geography. |
| Weather / light / sound | One supported or clearly reconstructed weather/time regime; visibility, sound ambience, surface response and atmosphere agree with it. | Full atmospheric simulation and climate campaigns. |
| Infantry / embodied interaction | Walk, turn, crouch, use cover and interact; clear role/orders; 3–5 recognizable companions; basic squad movement/regroup. | Every formation/doctrine, giant crowds or full-body biomechanical simulation. |
| Machine gun / small arms | Compatible stocks, reload/fire state, bounded ballistic model, cover interaction and audiovisual acknowledgment; suppression distinct from injury. | Every weapon class, exact internal ballistics or unsupported penetration tables. |
| Vehicle | One grounded variant with crew/occupancy, route/mobility, fuel/load and simple component failure state; correct visual identity. | Full drivetrain/track simulation, all armored vehicles or naval/air systems. |
| Injury / casualty / care | Persistent injury, death, a bounded aid action and its resource/time costs; same outcome survives saves and LOD. | Complete medicine or a claim that a simplified model is a medical simulation. |
| AI / command / perception | Local state machine or utility decisions for follow, wait, task, threat/cover and aid; delayed observations/orders; no omniscient path to world truth. | Unbounded autonomous agents, mandatory online LLMs or strategic staff simulation for every theater. |
| Identity / quiet life | Persistent IDs, brief backgrounds with provenance labels, directed relationships, event-linked memory; at least two meaningful quiet activities and a later recognizable consequence. | A generated biography for everyone or rich open conversation before basic attachment is tested. |
| Presentation / presence | Responsive controls, coherent locomotion/gestures/gaze, readable actions, layered environmental sound, lighting and subtitles; source inspection optional; desktop/VR action and body/view boundaries. | Photorealism as a prerequisite, full VR release or a giant asset library. |
| Profiles / accessibility | Data policies for Easy/Experience, Standard, Simulation and High Fidelity, separately configurable assistance and accessibility; profile changes logged. | Four separate simulations/content forks or evidence confidence tied to difficulty. |
| Core / loader / save | Fixed-step local runtime, event/snapshot contract, typed package loader, scoped LOD proof and provider independence. | Full-world multiplayer lockstep or an operational Deliver marketplace. |

The first playable loop must include a preparation task, movement with companions, a quiet interval, a clear order, a consequential local choice and a visible/audible response. Possible quiet interactions are an equipment check, sharing/moving supplies, listening to a companion's uncertain report or helping a tired person. The selected activity changes actual time, stock, preparedness, knowledge or relationship state. Decorative dialogue alone does not establish meaningful interaction.

Profiles are data selecting assistance, hints, player-facing lethality/recovery and supported simulation detail. They do not modify the underlying evidence record, an NPC's factual knowledge or the historical identity of a weapon. An Easy protection policy records the accepted gameplay effect and still preserves honest inventory/casualty accounting; it never secretly removes deaths from the log. High Fidelity uses available model detail and can still have accessibility assistance. [EXPERIENCE_DESIGN](EXPERIENCE_DESIGN.md) defines the policy and envelope-conflict expectations.

Future VR portability is required from the first composition, even though a full VR release is later. Input bindings select a shared action set; body state is independent of desktop or tracked head/hand presentation; interaction targets expose meter-based reach/contact and device-independent prompts. Assets carry real scale, meaningful hand/grip anchors and collision metadata. UI supports readable world-space/diegetic presentation, and cinematic content cannot require forced camera movement. [SIMULATION_LOD](SIMULATION_LOD.md) defines authority and safety boundaries; [VR_READINESS](VR_READINESS.md) defines the M1 target-device OpenXR smoke gate. Engine selection stays conditional until the actual XR integration is researched and tested; an advertised/community plugin alone is not proof.

## Bounded interaction and character contracts

An interaction definition declares eligible actor/target roles, knowledge prerequisites, location/time/resource requirements, interruption/resumption policy, choices, validated effects and presentation cues. Runtime systems evaluate it against actual state. Effects go through normal inventory/health/order/relationship interfaces; content cannot write arbitrary components. An authored aid scene requires a present living companion who needs aid. If those facts are false, it is ineligible; the director selects another permitted possibility or leaves quiet time.

Character identity, role, health, commitments, knowledge, memory and relationship state are separate components with a persistent `CharacterId`. A name/face plus past experience must remain recognizable through outfit changes, streaming and save/resume. Real people receive bounded sourced identity and clearly interpreted dialogue; synthetic companions are labeled synthetic in optional inspection. A rumor is an actor belief with origin and delivery time, not a historical fact.

Animation/audio are driven by accepted action states and authorized observations. Presentation may select compatible gesture/voice variants, but cannot invent a completed reload, aid event or spoken fact outside the actor's knowledge. Cues can improve readability without granting future or hidden enemy information. Later generative dialogue fits the same `InteractionProposal` interface, with scoped knowledge, a deadline, validation and a local fallback; no memory exists only in a model conversation.

## Substitution, approximation and missing pieces

Every capability exposes supported fidelity levels and their limitations. A reduced model returns its model ID, assumptions, validity region, error/calibration evidence where available and unresolved unknowns. An absent required capability returns `CapabilityGap`, never plausible-looking success. Partial artifacts cannot satisfy a mandatory requirement until the gap is resolved or the episode's approved scope changes.

Safe substitutions retain identity and declared interfaces: fewer mesh triangles for the same variant; coarse but reviewed terrain outside the visible play area; scripted dialogue using the same knowledge and memory rules; a categorical local effect model within a reviewed scope. Substitutions that alter actual variant, dated unit presence, actor knowledge, casualty state or hard historical envelopes require reconstruction/scenario review. The runtime may lower purely visual settings independently; a change of simulation model is a recorded policy/LOD decision and must obey continuity tests.

Content quality is a vector with separate history, visuals, simulation, character, interaction, atmosphere, interest, coherence and performance evidence. It is not a single score automatically increased by spending more money. The budget planner can choose a small well-animated, well-lit locality over another square kilometer once minimum historical and mechanical requirements are met. Numerical fields remain unmeasured/null until reviewed; never fabricate a benchmark or playtest score.

## Acceptance and reuse proofs

1. **Typed composition:** reject an unknown capability, incompatible schema, cyclic unresolved dependency, unsupported LOD, wrong unit or missing required field before play. Errors name the dependency and remedy.
2. **Grounding and asset binding:** field provenance resolves to the pinned snapshot; wrong-date variants, mismatched mesh/weapon binding, incompatible ammunition and absent licenses fail the relevant gate. A correct JSON shape alone proves none of these.
3. **Provider independence:** package the fixture with `LocalCapabilityProvider`, disconnect network/research/Deliver and load/play it. The runtime dependency scan contains no Deliver internals. Same accepted fixture outputs yield the same locked package regardless of adapter.
4. **Conservation and replay:** execute the [SIMULATION_LOD](SIMULATION_LOD.md) fixtures for owned runtime effects, persistent people and save/LOD handoffs. Claim command-only physics replay only in a proven domain.
5. **Second-episode reuse:** author a second small fixture with different locality/order/roster/variant data and the same installed capabilities. Load it with the same binary and loader; review the diff to show no episode-specific code or schedule was added. This test proves composition, not that an entire second historical campaign exists.
6. **Actual play:** create the embodied first slice with meaningful quiet activity, companions, weather/sound/animation and consequential choice. Complete HistoricalValidation, ProvenanceValidation, SimulationValidation, IntegrationValidation and independent ExperienceReview. A headless demo, asset catalog or proof that plugins load cannot be promoted as PlayableEpisode.
7. **VR portability:** use the same locality, role and interaction definitions with desktop and tracked input adapters in the M1 smoke test. Check stereo scale/depth, head/body separation, hand contact/reach, comfortable attention cues, readable UI and measured target-device cadence. Record missing hardware/runtime as an unverified gate; do not claim a full VR build from the architecture alone.

## Risks and unresolved decisions

The principal architectural risk is building an elaborate registry while postponing the game. Keep the initial registry finite, select a small episode, and add a contract only for observed reuse or a required boundary. Other risks are engine plugin churn leaking into content; overspecified schemas making authoring expensive; broad evidence labels concealing weak local presence; visual and physical variants drifting; coarse models producing convincing but unsupported effects; and animation/audio content effort dominating the schedule.

Dependencies on the historical reviewer, locality/equipment data, representative licensed assets, engine spike and canonical contract/schema owner are real. Unknowns include first locality, supported variant, reference hardware, asset/rig supply, coarse effect calibration and the best engine authoring workflow. Resolve them with narrow fixtures and an early human playtest. Research/build automation, detailed physics, long campaigns, richer AI, naval/aviation and marketplace integration expand only after the first experience and reusable loader have passed their gates.
