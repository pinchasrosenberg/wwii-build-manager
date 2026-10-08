# Episode and shared wire contracts

Version `0.1.0` is an initial draft, not a production compatibility promise. Canonical schema source is [game/contracts.py](../../game/contracts.py); generated JSON Schema Draft 2020-12 is [contracts.schema.json](../../schemas/game/contracts.schema.json). Export deterministically with `PYTHONPATH=.runtime-deps/driver-runtime python3 -m game.contracts > schemas/game/contracts.schema.json`.

The JSON file is a `$defs` library. Select an entrypoint explicitly (`#/$defs/EpisodeSpec`, for example); validating against the bare bundle does not validate an episode. Python validators enforce semantic constraints not encoded in the generated JSON Schema. Untrusted input must use `model_validate_json` with strict/extra-forbid validation. Parsed JSON must reject nonfinite numbers and duplicate keys at the transport boundary. Shape validity does not establish historical truth, source access, or entitlement to spend.

## Contract inventory

| Contract | Boundary and required semantics |
|---|---|
| ContextManifest | Five layer references, grant, policy/index digest, write/read bounds, budget, metrics, expansion requests |
| Capability | Owner, version, kind BUILD/RESEARCH/RUNTIME/VALIDATE, schemas, dependencies, artifact and tests |
| CapabilityRequest | Request/input binding, episode/capability/version, scoped work/historical refs, quality/accuracy, budget/deadline |
| CapabilityResult | Same binding, status, artifacts/evidence/provenance, quality/accuracy/cost, new context/work, gaps |
| CapabilityGap | Needed vs available, owner, blocking status, permitted resolution and supporting refs |
| HistoricalClaim | Subject+field+value, unit, time/space, certainty axes, sources, contradictions and assumptions |
| Provenance | Source content digest/license/locator, method, derivation, perspective, source time and review refs |
| EquipmentVariant | Family/model/variant/block/modification/period, unit/theater/date evidence, sim/visual identity match |
| HistoricalTerrainSnapshot | Place+time, versioned layers, historical/modern/reconstructed origin, georef error and admission reviews |
| HistoricalWeatherSnapshot | Local time/area, weather fields/units, claim refs and field accuracy |
| HistoricalBattleSkeleton | Formations/strength/command/axes/places, ordered anchor data, outcome and unresolved claims |
| HistoricalEnvelope | Source precision, earliest/latest and optional preferred, constraints, evidence, hard/soft status, infeasibility policy |
| AccuracyManifest | Field paths, certainty axes, claim/reconstruction references, unresolved conflicts and reviews |
| EpisodeSpec | Identity/revision, place/time, terrain/weather/skeleton, formations/strength/equipment, experience, objectives/events/initial state, capability/content locks, quality/budget/accuracy, seed/tick/reviews |
| Quote | Immutable request/provider/scope/criteria/terms binding, fixed Money, expiry and evaluation |
| PricingEvaluation | Cost estimates/ordered percentiles/risk, demand/reuse/revenue, historical/player/quality/strategic gains and calibration |
| DeliverInvestment | Candidate investment, quote/cost, expected gains/dependencies/success criteria and reasoned decision |

`EpisodeIntent` is an authoring request, not executable content: requested time/place/role, duration, profile, experience goals, budget and scope. `EpisodePlan` is a reviewed work graph with prerequisites, source/gap decisions and resulting locks. Their production wire schemas, result-acceptance receipt, replay header and LOD transaction follow M1 owner review; their behavioral contracts are already defined in the corresponding documents. Do not feed free-form intent directly into the game runtime.

## Shared conventions

Stable IDs identify entities across revisions; artifact hashes identify immutable bytes. Semver applies to contracts/capabilities, Episode revision identifies a content snapshot, and save/replay pins both. Physical quantities use SI in named units; geographical storage uses EPSG:4326 `[west,south,east,north]`. The initial bbox contract excludes antimeridian crossing; split areas rather than silently wrap. Runtime local coordinates use meters and a separately locked origin/transform; do not treat longitude as meters.

Historical source time preserves stated precision and unknown timezone. A source-reported local time is not UTC. `OBSERVATION` never automatically becomes `VALIDITY`; validity requires evidence. Operational deadlines/expiry use explicit offset instants. Comparisons require compatible granularity and timezone knowledge. The draft supports Gregorian dates with whole-second resolution; calendars/uncertain intervals more complex than this are an explicit later extension.

Certainty is orthogonal: basis DOCUMENTED/RECONSTRUCTED/SYNTHETIC/UNKNOWN, verification VERIFIED/UNREVIEWED, confidence HIGH_CONFIDENCE/PROBABLE/UNASSESSED, dispute DISPUTED/CLEAR/UNASSESSED. All requested display terms remain available. VERIFIED review references must resolve to independent reviews; schema presence alone is insufficient. UNKNOWN values remain null. Conflicts retain alternative claims.

Money uses nonnegative integer minor units plus currency. Signed profit is a separate accounting calculation; never encode losses as negative price. The local simulator uses `TEST_CREDIT` only. Nested quote money is immutable. A provider result is not a result-acceptance receipt; settlement follows independent validation against locked criteria.

## Semantic gate beyond shape validation

Resolve every referenced ID/hash against the locked bundle and caller grants. Reject cycles/missing dependencies, wrong episode/capability/input binding, unauthorized artifact paths, revoked/expired grants and unresolved required capabilities. Check artifact licenses, source locators, source independence, review authorship, unit dimensions, equipment availability and visual mesh identity; an ID match alone does not inspect a mesh.

Historical admission checks terrain date (especially modern baseline), source error vs required interaction scale, weather contradictions, force strength cohort bounds, command validity and spatial/time envelope feasibility. Partial result must explain gaps; success cannot contain blocking gaps. No guessed troop assignment or unsupported exact coordinate is upgraded to a fact.

Episode preflight validates required capabilities and historical constraints before a playable candidate. Promotion happens after playtests and all independent reviews. ExperienceSpec includes player role, meaningful choices, quiet activities, persistent characters, autonomous systems and invariant-preserving profiles. VR presentation/profile settings never alter historical equipment identity or world truth. All nine quality axes carry rubric-based targets and remain null when unmeasured.

## Revisions and migration

Adding optional data is a minor draft revision only after consumers accept it explicitly; extra fields currently fail closed. Breaking semantics require a new schema version and conversion artifact. Never relabel old UNKNOWN values as measured, or reuse a revision/hash after edits. Save migration validates identities, resources, companions, anchor state and profile; failed migration leaves the old save intact. Historical updates are not automatically applied to running sessions.
