# Public interface context

Interface names in the Lego registry are proposed stable boundaries. Before a builder depends on one, the contract owner must provide its exact version, units, preconditions, outputs, errors and contract fixtures. A name alone is not an implemented API.

The first contract freeze must cover:

- EntityId / VariantId / SI quantities / SimTick / events / provenance and accuracy references.
- `TerrainSample` and `SurfaceState`: slope/contact/material/wetness/traction inputs.
- `WeatherSample`: wind/precipitation/visibility/temperature at time and place.
- `PowertrainOutput`, `MobilityCommand`, `MountTransform`, `CrewStation`.
- `WeaponAction`, `AmmunitionDefinition`, `ShotQuery`, `HitEvent`, `DamageEffect`.
- `PerceptionQuery`, `DeliveredObservation`, `OrderDelivery`, `InteractionProposal`.
- `VariantVisualBinding`, `AnimationActionView`, `AudioCue`, `PlayerAction`, `TrackedPose`.
- `ObjectiveCondition`, `BattlePhase`, `AnchorConstraint`, `EpisodeComposition`.

Consumers get the named interface and a synthetic test double, not the entire owner folder. Root/runtime_core serializes shared contract changes; downstream owners review migrations. Existing Python wire schemas remain in `game/contracts.py`, while Godot runtime interface contracts are future work.
