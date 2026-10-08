# Experience design — presence before presentation

Product contract: **I live inside a moment of WWII, with people, responsibilities and uncertainty.** The game must remain worthwhile for someone who already knows the history. Knowledge inspection is optional and contextual; historical information is primarily encountered through terrain, visibility, orders, equipment, fatigue, delayed reports and other people.

## First playable loop

Episode #1 selects a sourced small sector and 20-minute experience after historical preflight. The precise battle, weather and vehicle are not invented now. First-person embodiment is the provisional camera choice, with accessible third-person/camera comfort options evaluated in the engine spike. A full VR release is later; VR portability seams and an early device smoke test are required from M1, as specified in [VR_READINESS](VR_READINESS.md).

The player is a junior member of a small unit with one clear responsibility: accompany a movement, help keep the group together, and deliver or act on a bounded order. A movement problem gives at least two legible, consequential local responses. A companion needs assistance; helping may cost time or supplies and changes a later interaction. A vehicle, infantry and one machine gun establish the requested MVP interactions when evidence supports their identity and presence.

The loop is: perceive → understand an immediate responsibility → choose/act → see/hear a response → update relationships/resources/plan. The world clock and offscreen orders continue. A missed objective creates a recoverable local consequence or explicit episode endpoint, not an invisible reset. A player may die or be injured; an optional checkpoint reload is clearly a gameplay affordance, not a historical event.

## Pacing is a state of the world

Use authored possibilities with simulation prerequisites, not a forced timer spawning combat every 30 seconds. An example test session includes preparation, travel, waiting, a brief complication and recovery. These are test beats rather than claims about a named battle. Quiet time offers observation, navigation, equipment checks, companion interaction, listening to rumors or making a plan; it need not always require input. Sound, gestures, distant activity, changing light and consequences sustain anticipation.

An experience director can choose eligible optional interactions, hints and presentation emphasis. It cannot create false enemy positions, override historical anchors, silently change equipment, resurrect dead people, teleport a formation or give NPCs future knowledge. If no safe interesting event is available, allow quiet life, a consensual time skip or a shorter Episode.

## People and continuity

CharacterId is persistent across rendering and simulation LOD. Biography, visible appearance, current role, health, relationships, memories, knowledge and orders are separate components. Synthetic companions are explicitly synthetic when inspected; do not attach invented biographies/dialogue to real people as evidence. Real historical people have claim-backed identity and bounded interpretation.

Memory records event_id, witnesses, perceived content, local time and provenance layer. A relationship change is gameplay state. Heard rumors are beliefs and can be wrong; speech never directly accesses WorldTruth. Death, injury, replacement, separation and reunions persist across saves and aggregation. LLM dialogue is a later implementation behind the same bounded interaction interface; scripted/state-machine dialogue is sufficient to establish care and continuity in slice one.

## Long episodes

Days/weeks/months require activity schedules, sleep, meals, maintenance, travel, training, guard duty, briefings, leave, relationships, letters, promotion, injury and recovery. Scheduling assigns intent/resources, while interruption policy handles alarms, weather and orders. Do not expand every meal into a mini-game. Track fatigue, supplies, social continuity and deadlines consistently.

Time acceleration is requested by the player and pauses or slows before a material local event. Offscreen simulation advances at its own LOD; clocks cannot skip across a historical anchor without processing it. Resume restores companions, outstanding orders and supplies. Save at safe boundaries, support interruption and display expected skip length. Multiplayer time acceleration is deferred pending shared-clock design.

## Experience profiles

| Profile | Assistance / gameplay tuning | Historical invariants |
|---|---|---|
| Easy / Experience | clearer wayfinding/orders, lower player lethality, gentler recovery, optional pause/checkpoints | same historical setting, terrain, equipment identity, major events |
| Standard | readable cues and moderate local consequences | same |
| Simulation | fewer cues, harder navigation, higher personal vulnerability | same |
| High Fidelity | most available physical/behavioral detail with assistance separately configurable | same; visual setting is not an evidence confidence label |

Difficulty, physical model fidelity and historical certainty are separate settings. High Fidelity does not mean that other profiles have false history. Accessibility (subtitles, remapping, contrast, camera motion, sound cues, readable text, input holds/toggles) is available across all profiles. Profile changes are recorded gameplay modifiers, applied to the player-facing damage/recovery/hint layer; they cannot silently alter the historically grounded weapon data or global casualty ledger. Tensions with an anchor use the conflict procedure, not forced deaths.

## Episode quality and investments

The vector is `historical_fidelity`, `visual_fidelity`, `simulation_fidelity`, `character_quality`, `interaction_density`, `atmosphere`, `gameplay_interest`, `world_coherence`, `performance`. Values are rubric-based, with evaluator, scope and evidence, and remain null when unmeasured. No uncalibrated average is an objective quality score. Higher interaction density is not always better; quiet pacing has its own target range.

FidelityPlanner considers cost, uncertainty reduction, historical importance, visibility, reuse, sensory impact and measured experience deficits. A lighting, sound, animation or character investment can outrank another research pass once historical hard gates pass. Paid beauty cannot compensate for wrong units or unsupported certainty. Performance is measured on a named machine and workload.

## ExperienceReview promotion gate

An independent reviewer observes a fresh playtest, separate from the builder's scripted demo. At least three people unfamiliar with the controls should try the first 15–20 minutes; this is a proposed formative gate, not a statistically validated product metric. Record consented observations and questionnaire answers without inventing scores.

Check: compelling role; clear available actions; meaningful local choice and observable response; pacing that supports quiet; recognizable companions; curiosity; coherent autonomous world activity; acceptable comfort/performance; desire to continue. Initial target: all testers can describe their role and one consequence, at least two want to continue, and no tester encounters a blocking control/readability failure. A failure returns concrete design work, not a confidence downgrade on historical claims. Review quiet sections explicitly. Death-heavy excitement is not a substitute for attachment or atmosphere.

Promotion requires HistoricalValidation, ProvenanceValidation, SimulationValidation, IntegrationValidation and ExperienceReview. Automated tests establish mechanics and invariants; only human play establishes the experience gate. This delivery contains the gate design, not completed playtest evidence.
