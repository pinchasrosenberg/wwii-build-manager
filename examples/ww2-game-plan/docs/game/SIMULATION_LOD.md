# Simulation, ECS and world LOD

Status: architecture contract, 2026-09-27. No engine, conservation test, replay benchmark or playable result is claimed here. [EXPERIENCE_DESIGN](EXPERIENCE_DESIGN.md) owns the experience gate; [STACK_EVALUATION](STACK_EVALUATION.md) owns the engine comparison and measured spike. The provisional M1 choice is Godot/OpenXR with an isolated typed domain module and the same headless physics backend; device and performance gates remain untested. This design must support desktop play and future VR portability; [VR_READINESS](VR_READINESS.md) owns the XR spike details.

The simulation exists to make a place and its people worth inhabiting. An encounter has preparation, uncertain information, fatigue, relationships and aftermath. Rendering fewer entities must never erase those consequences. A correct headless run is necessary evidence about mechanics; it cannot establish atmosphere, animation, readable action or interest.

## Authority and execution boundaries

`HistoricalTruth` is an immutable, versioned evidence snapshot. `Reconstruction` selects bounded interpretations, starting conditions and approximations with provenance. `GameplaySimulation` owns the evolving counterfactual playthrough. They share stable reference IDs; they do not share write authority. A runtime casualty is a gameplay event even when its victim represents a documented person. It never becomes a historical claim.

```text
Evidence snapshot + reviewed reconstruction + EpisodeSpec + content lock
                              ↓ load / validate once
Commands → fixed-step SimulationCore → canonical events + snapshots
                     ↓ authorized view         ↑ input commands
                 renderer / audio / animation / UI
```

The core owns time, identity, inventory, health, orders, knowledge, world scheduling and accepted domain effects. It can run without a GPU, window, audio device, network, research database or Deliver. Python research/build tools produce content-addressed packages. Runtime systems consume validated local packages, never invoke a paid builder in a tick. The renderer consumes an actor-authorized view and sends intentions; changing camera, frame rate, streaming completion or sound settings cannot change a canonical outcome.

Detailed collision/physics may initially live behind an engine-specific local adapter. Its authority-changing results enter through a versioned `AcceptedEffect` boundary; decorative particles, cloth and ragdolls have no domain authority. If the adapter cannot run headlessly or reproduce its effects in the declared determinism domain, command-only replay for that feature remains unproven. Recorded accepted-effect replay is a distinct, weaker guarantee and must be labeled accordingly.

## Desktop and VR embodiment boundary

Keep the authoritative player body, eye/view presentation and tracked head/hands separate. `PlayerBody` owns locomotion, stance, collision, carried equipment and injuries. A presentation rig maps a desktop camera or an XR tracking space onto it. Tracked poses are inputs with sample time and tracking-validity state; they are not permission to overwrite the body's world transform. Device adapters translate keyboard/mouse/controller/VR actions into the same domain intentions: move, turn, interact, aim, use, reload and issue order. Record accepted actions/pose-derived interaction outcomes at simulation ticks so replay never requires a live headset.

World coordinates, collision volumes, reach and assets use declared meter units and consistent axes. Rendering a pair of stereo views, late pose updates or increasing display frequency must not advance physics/domain time. The body, head safety volume and hands have explicit collision/reach policies: a tracked hand cannot pick up an object through a wall; an invalid/tracking-lost pose cannot cause a shot or teleport; physical head movement near a wall receives a comfortable visual response without forcing the camera back by physics. Hand/weapon contact effects remain in the fixed-step accepted-effect boundary. Body proxy/hand colliders must not impart unlimited impulses from noisy tracking.

Comfort/accessibility are presentation and input policies: configurable snap/smooth turning and locomotion, optional seated height/reach assistance, no forced camera shake/head bob, and no cinematic that forcibly rotates a tracked head. Scripted events direct attention through sound, gaze or an optional transition instead. UI/interaction affordances have a device-independent model with readable world-space/diegetic depth where appropriate; source inspection and menus cannot depend on an unreadable flat overlay. Desktop interaction remains usable without imitating tracked hands.

M1 includes an actual target-device/runtime stereo/input/interaction/performance smoke gate per VR_READINESS. It establishes portability risk early, not a full VR release. No XR performance or compatibility claim is accepted from a desktop frame-time result alone. If hardware/runtime is unavailable, mark that gate blocked/unverified and keep the engine decision conditional.

## Time and ECS scheduling

Use an integer `SimTick` and rational tick duration; **20 Hz is the provisional domain rate**, not a measured requirement or a mandate for the physics/render rate. Local physics may use a finer fixed rate with explicit synchronization boundaries. Strategy and daily-life systems schedule due work on the same timeline at coarser intervals. Every scheduled event is processed before time advances beyond its deadline. Paused simulation does not accumulate wall-clock time to catch up later.

An entity is a stable domain ID plus components. An engine ECS handle is disposable and cannot be a save-file identity. Components represent identity, position support, equipment/inventory, health, fatigue, morale, orders, knowledge, commitments and representation ownership. A system declares component/resource reads, writes, emitted events and phase dependencies. The scheduler can parallelize disjoint work; overlapping mutations go through a deterministic ordered reduction. No meaning depends on hash iteration order, worker finish order or which cell loaded first.

| Tick phase | Authority and dependency rule |
|---|---|
| 1. Accept inputs | Validate actor rights, intended tick, sequence and preconditions. Apply commands, profile changes and already accepted external decisions in stable order. Reject late/conflicting inputs explicitly. |
| 2. Advance due world events | Deliver messages, supplies and weather transitions; update schedules and existing orders. Historical anchors are assessed before their deadline. |
| 3. Build observations and decisions | Derive visibility/hearing from state; update actor knowledge; run AI against that knowledge. Current-tick decisions cannot consume effects from a later phase. |
| 4. Resolve activities and local motion | Produce movement, work, firing, contact and interaction proposals. Physics results are accepted at their specified synchronization point. |
| 5. Commit domain effects | Validate and resolve proposals once: ammunition expenditure, fuel use, injury, death, suppression, morale change, relationship/memory and order status. |
| 6. Change representation | Commit eligible LOD transactions and spatial residency handoffs only after pending effects are resolved. |
| 7. Audit and publish | Check balances/ownership; append events, compute canonical hashes, emit authorized views and optional snapshots. |

This phase order is an initial contract, not engine API syntax. A changed order is a simulation-version change. Same-phase conflicts use documented domain rules followed by stable event keys such as `(tick, phase, priority, actor_id, command_sequence, effect_index)`. A total order must not accidentally grant the smallest ID a permanent combat advantage: simultaneous exchanges use a frozen phase input and batch resolution when the model requires simultaneity. Parallelism changes compute order, not commit order.

## Four simulation levels

Simulation LOD and graphics LOD are independent. Looking away may hide a mesh; it does not instantly convert a soldier into an unrelated probability. Activation considers causal relevance, threat, task, communication and player interest as well as distance. Hysteresis and minimum residency reduce repeated promotion/demotion. Pending shots, contact, rescue, conversations and observed transitions pin sufficient detail until their consequences settle.

| Level | Active representation | Typical due work and retained detail |
|---|---|---|
| Strategic | Formations, supply networks and region-scale commitments | Hours/day schedules, route capacity, reinforcement and anchor feasibility. Preserve roster references, resource ledgers, scheduled commitments and a bounded location region. No invented precise front-line coordinates. |
| Operational | Unit routes, transit, supply and staff activity | Minutes/hour events, delayed reports, travel progress, rest/maintenance and interruptions. Preserve named people, vehicles, loads and order chains. |
| Tactical | Squads, vehicles, cover areas, contacts and tasks | Seconds-scale movement/combat/activity batches with terrain and visibility envelopes. Contacts carry uncertainty and last observation, not omniscient target transforms. |
| Local | Individuals, equipment instances, visible surroundings and interactions | Fixed-rate movement, detailed fire/cover, animation-facing action state, sound stimuli and direct social activity. Identity and supplies are the same records used at coarser levels. |

Intervals are chosen and tested per model, not treated as universal values. An aggregate owns a set of entities; it does not become another set of soldiers. Keep a compact roster with stable `CharacterId` for every represented person, even when detailed biography and meshes are lazily loaded. Synthetic identities are allocated deterministically at scenario/roster creation and labeled Reconstruction. If a theater-scale roster exceeds measured budgets, design a declared cohort identity model before claiming that scale; do not silently generate replacement people whenever the camera approaches.

Only one simulation authority owns an entity for an interval. An aggregate's personnel total is a derived index over its owned roster, never an additional population balance. Nearby squads can use different levels, but an interaction has exactly one owner and one resolution model. A long-range shot into a coarse cell either promotes the affected scope before resolution or uses a declared coarse effect model with an accepted, traceable result. Two models must never resolve it twice.

## Conservation and persistent state

For each extensive quantity and item type, every interval must satisfy:

`closing = opening + declared arrivals + declared production − declared departures − declared consumption − declared destruction`

Transfers have one transaction ID and a debit/credit pair, including in-transit ownership. Local inventories and parent summaries cannot both count the same stock. Integer counts and fixed base units are preferred for audited resources. Rate integration retains fractional residuals across LOD/save boundaries so repeated rounding cannot create supplies. SI units, caliber/ammunition compatibility and resource types are explicit. Do not combine rounds, magazines, kilograms and liters without a declared conversion.

| State | Preservation / transition rule |
|---|---|
| Personnel | Alive and dead IDs persist. Membership/location/status may change only via events. Use orthogonal life, custody, presence and duty states; wounded, missing and captured can overlap and must not be summed as disjoint totals. Check headcount from unique IDs. Reinforcements are arrivals, not a reset to establishment strength. |
| Casualties / injury | Death is terminal in a playthrough; evacuation, treatment, infection/progression and recovery have dated events and prerequisites. Cumulative deaths never decrease. Injury anatomy/severity, bleeding progression, disability, treatment and carried supplies survive every LOD transition. A checkpoint load explicitly starts a replay branch. |
| Equipment | Preserve instance ID, variant, owner, mounts, load, component failures and wreck/capture/repair state. A lost item is not replaced by a new visual prefab. Parent summaries derive from instances or a counted homogeneous stock with explicit withdrawals. |
| Ammunition | Debit an actual compatible stock before accepting a shot/burst. Separate projectile expenditure, reload/magazine contents, reserves and transfer. Coarse effects consume the same stock; no free offscreen fire. |
| Fuel / consumables | Preserve quantity, type, tank/container owner and integration remainder. Travel, idle, leakage and disposal are explicit sinks. A vehicle that exhausts fuel changes its plan or stops. |
| Orders / commitments | Preserve issuing authority, version, recipient, delivery/acknowledgment times, prerequisites, deadline, status and cancellation/supersession chain. LOD change cannot mark an undelivered order received or silently erase a failed task. |
| Morale / fatigue | These are evolving intensive states, **not conserved scalar totals**. Keep per-person values or a declared distribution with identity-linked exceptions and causal updates. An average cannot reconstruct frightened/injured individuals or squad cohesion. Fatigue/rest and morale changes require elapsed activity/events. An instantaneous no-time LOD round trip preserves each value exactly. |
| Relationships / memories | Preserve directed relationship state, event-linked memories, witnesses, actor interpretation and time. Aggregation may index/cold-store these records; it cannot merge two people's beliefs into unit truth. Death and separation leave surviving people's memories intact. |
| Position / uncertainty | Preserve the admissible location support, route progress, last resolved location/time, velocity/travel bounds and uncertainty model. Finer detail cannot imply better historical evidence or better actor knowledge. |

Historical positional uncertainty, simulation location support and an actor's belief about an enemy position are three different records. An exact gameplay placement sampled inside a plausible region remains a reconstruction; it does not turn an archive's approximate location into a precise fact. A coarse route must carry feasible reachability support, not just a centroid and radius that crosses impassable terrain. Never renormalize an impossible distribution into a legal one without reporting the discarded evidence/assumption.

## Atomic LOD handoff

1. **Plan:** select source ownership epoch, target level, entity roster, tick and reason; bound the destination by terrain, occupancy, route and outstanding interactions. Record the model/version and uncertainty policy.
2. **Resolve through the handoff tick:** settle or explicitly transfer in-flight effects, resource reservations, communication delivery, injuries and due schedules. Never run the source and destination for the same interval.
3. **Prepare:** produce destination representation from canonical records. Stable placement sampling uses the dedicated entity/transition stream, inside the carried support and travel bounds. Use prior detailed positions when still valid. Do not resample a different location merely because the player looks away and back.
4. **Validate:** compare represented IDs, ledger balances/residuals, health/casualties, orders, actor knowledge, morale/relationships, temporal coverage and feasible placements. Destination failure leaves source ownership unchanged.
5. **Commit:** atomically advance ownership epoch and publish a `LODTransition` event. Presentation instantiates/unloads assets from that receipt. Destroying a render entity never deletes the canonical entity.

If a vehicle cannot be placed without violating the route, geometry or observed continuity, retain the more detailed model, delay activation within a declared streaming boundary, or return a typed scenario/placement failure. Do not teleport it to a road. If performance cannot maintain a required pinned local interaction, expose a performance failure or permitted simulation slow-down; do not skip casualties or clocks.

A same-tick promote/demote cycle must be lossless for canonical records. Runs with different LOD schedules need not have identical future tactical outcomes when they intentionally use different approximations. The supported claim is conservation, persistence and calibrated bounds. Store LOD decisions/model revisions in replay input; test equivalence separately for models explicitly designed to agree. Do not promise bitwise combat equality across arbitrary LOD choices.

## Autonomous world, daily life and accelerated time

World activity is event-driven, not spawned by the player's gaze. Orders, logistics, guard shifts, sleep, meals, travel, training, maintenance, letters, briefings, treatment and social commitments advance offscreen. Schedule templates specify role, location, duration range, resource needs, interruption/resumption policy and authority. Actors negotiate conflicting commitments through a small priority/constraint resolver; a soldier cannot drive, sleep and stand guard simultaneously. Intent is separate from completion: blocked routes, alarms, illness and absent supplies can make tasks fail.

The first episode implements a small representative subset: preparation/equipment check, movement, waiting/guard or supply work, companion assistance and rest/recovery. Longer episodes progressively add the other activities with the same scheduling and event contracts. Long time horizons do not require a mini-game for each meal. They require accountable time, supplies, health and human continuity.

Player-requested acceleration changes wall-clock presentation and scheduler batch sizes, never historical/world elapsed-time rules. An event horizon stops a batch at the next material interrupt: local threat, an order needing a choice, a health threshold, a social commitment the player chose to attend, supply failure or historical anchor. Integrate depletion/progression up to the earliest threshold and process it before continuing. Before skipping, display expected destination time/activity and interruption policy; resume exposes changed orders, companions and inventory through in-world feedback. Save/resume is valid at committed tick boundaries. Shared-clock multiplayer acceleration is deferred.

Quiet interactions have effects on time, preparedness, information, trust or later choices. The experience director selects only eligible interactions from actual world state. It can emphasize a sound, gesture or valid opportunity; it cannot conjure enemies, supplies or a surviving friend to cure a pacing problem. If no suitable activity exists, quiet observation or an offered time skip is valid. Presentation quality for this state—wind, footsteps, distant activity, posture, gaze and small acknowledgment—is part of the playable gate.

## Historical envelopes and local agency

An envelope names its evidence claims, time interval/precision, geographic scope, involved formations, constraint type, slack/tolerance, visibility to the player and conflict policy. Historical evidence strength remains independent of simulation feasibility. Hard anchors describe the declared bounded scenario; softer reconstructions provide explicit alternative possibilities. Designers choose a player role/area with meaningful local alternatives that do not require directing the entire war.

Evaluate reachability and available people/resources at load, before accepting relevant commitments and at a horizon before an anchor. Local outcomes may change who is injured, what supplies arrive, whether an optional objective succeeds, and what companions remember. Such changes remain real within the gameplay branch.

`SATISFIED`, `PENDING`, `THREATENED` and `INFEASIBLE` are explicit runtime assessment states. An infeasible envelope records the conflicting actions/events, missing resources and earliest detection tick. Permitted responses are:

- Adapt a remaining plan only through feasible routes, communication, timing and resources within declared envelope slack.
- End or narrow the episode at an explicit consequence/boundary when the historical mode cannot continue coherently.
- Offer an explicitly labeled counterfactual continuation, if the EpisodeSpec permits it; preserve the original historical record and prior events.
- During authoring, revise an unsupported reconstruction or select another episode and repeat review. This produces a new package revision, never a mid-save silent rewrite.

No response may resurrect a casualty, teleport a formation, generate fuel, force the player's death or report false success. An impossible hard anchor is a design/runtime conflict to surface, not an invitation to invisibly correct the world. Saving/loading or profile changes cannot conceal it.

## Randomness, event log, saves and replay

Use a versioned deterministic random algorithm with independent streams keyed by `scenario_seed`, `entity_id`, `system_id` and `purpose`. Derive draws by semantic event/tick index or store the stream counter; choose and test one scheme per model. An unrelated character's update or a decorative particle must not consume another character's combat stream. Define integer-to-distribution conversion and rejection sampling as part of the version. Counter-based keys alone do not guarantee equivalence between different coarse/fine models.

The append-only log records accepted/rejected commands, authoritative domain events, externally accepted effects/decisions, schedule interrupts, LOD decisions, profile changes and branch markers. Every event has a stable ID, tick/phase/order, owning entity/authority, schema version, causal parent IDs and relevant content/provenance references. An event describes the applicable HistoricalTruth/Reconstruction/Gameplay layer; recorded gameplay is never evidence promotion.

Snapshots contain canonical component state, compact rosters, all balance remainders, pending commands/effects, schedules, message queues, RNG state/counters, ownership epochs, envelope assessments and log position/hash. Cold-stored memory and evidence references need durable content hashes, not temporary asset paths. A replay header pins episode/reconstruction/evidence revisions, dependency and asset hashes, profile policy, simulation/schema/build versions, RNG specification, platform/physics determinism domain and command/effect-log mode.

Guarantees are scoped:

- **Domain replay:** same pinned build/content, seed, accepted inputs and LOD decisions reproduce canonical state/event hashes. Run this headless and with different render rates.
- **Recorded-effect replay:** reapply recorded external physics/AI results and domain commands. This proves restoration/presentation, not that re-running the external provider or physics recreates those results.
- **Command-only detailed physics replay:** enable only after measured proof for the declared backend/toolchain/platform/features and initialization order. Fixed timestep alone is insufficient; cross-platform floating-point physics is not promised.
- **Cross-platform canonical logic:** claim only for a declared tested target matrix and numeric model. Until then it is a goal, not a property of Rust or ECS.

Mismatched locks fail with a diagnostic. An explicit migration creates a new save branch, maps identities, preserves inventory/casualties and records unsupported fields and rollback path; it does not pretend the old replay hash remains valid. An offline build's AI uses local state machines/utility rules. Any later model-driven proposal is knowledge-scoped, validated, timed and logged before acceptance, with a local timeout fallback.

## Validation fixtures and promotion

All numbers below are **proposed tests**, not completed measurements. Store fixtures, seeds, model/lock versions, logs and exact divergence ticks. Use the stack document's hardware/performance suite alongside these domain checks.

| Test | Required result |
|---|---|
| Lossless handoff | 1,000 seeded no-time round trips through all legal LOD pairs, including an injured person, depleted magazine, damaged vehicle and pending order: canonical records and ledger residuals unchanged; one owner per entity. |
| Conservation under activity | 30 simulated days with travel, transfer, firing, leakage, capture, treatment, casualties and 10,000 transitions: zero unexplained personnel/equipment/ammunition/fuel balance difference; quantities nonnegative and IDs unique. Declared sources/sinks reconcile exactly in canonical units. |
| Interrupted transaction | Inject failures before prepare/validate/commit/publish and retry: either old or new ownership wins once; no double effect, duplicate stock or orphaned person. |
| Continuity | A named companion is injured, remembers aid, is evacuated and later encountered after save/LOD changes: same ID, health, relationships and known-event history; a dead companion cannot reappear alive. |
| Uncertainty / placement | 1,000 activations in a constrained route fixture: every position remains in carried feasible support; no forbidden crossing or travel-bound violation. Impossible support returns a typed failure with no placement. Actor knowledge gains only through delivered observations. |
| Replay / resume | Adopt the stack fixture: 100,000 ticks, five seeds, ten repeats, headless/rendered at 30/60/144 FPS plus render jitter; canonical hashes match in each declared replay domain. Restore at tick 50,000 and match uninterrupted state. Separate recorded-effect and command-only results. |
| RNG isolation | Add an unrelated actor and change visual particle count without a causal interaction: existing actors' declared random event streams are unchanged. Save/resume and worker-count changes preserve stream state. |
| Acceleration | In noninteractive schedule fixtures, normal speed and accelerated execution reach identical state/events at the same ticks. A bleeding/resource threshold, command deadline and anchor each interrupt before being crossed unprocessed. |
| Envelope infeasibility | Consume the only feasible transport/fuel or lose an essential actor: return THREATENED/INFEASIBLE and an allowed response; no resurrection, new stock, forced death, teleport or hidden event rewrite. |
| Approximation calibration | Compare fine/coarse models on shared fixtures for travel, suppression, losses and stock use using declared error tolerances and sample counts chosen before running. Passing conservation alone does not establish realistic combat. |
| Experience | Play the embodied slice and meaningful quiet interactions with independent reviewers under [EXPERIENCE_DESIGN](EXPERIENCE_DESIGN.md). Visible/audible consequence, companion recognition and desire to continue are mandatory evidence beyond a passing headless test. |

## Dependencies, unresolved choices and risks

Required contracts: typed units/coordinates, stable identity/provenance, EpisodeSpec locks, evidence/reconstruction references, equipment and interaction definitions, actor-knowledge projection, domain events, snapshots and local physics adapter. [LEGO_ARCHITECTURE](LEGO_ARCHITECTURE.md) defines how versioned reusable capabilities supply them. Contract schemas must distinguish required core fields from future extensions; architecture descriptions do not imply executable validators already exist.

Main risks are aggregate/fine combat bias; illegal rematerialization near observers; saving all individual continuity at scale; scheduler bias; slow streaming forcing invalid handoffs; long-duration injury/resource integration; overly rigid envelopes removing agency; and an engine workflow that passes replay but produces lifeless companions. Bound the first slice to a small area and roster. Prove identity/conservation and one embodied interaction before adding theater scale. Physics backend, numerical representation, update intervals, placement solver, coarse-combat calibration and target hardware remain spike decisions. No promise of multiplayer lockstep or arbitrary-length campaign performance follows from this design.
