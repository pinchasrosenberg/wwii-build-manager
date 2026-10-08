# Workspace guidance

- Existing Atlas/ETL work and game architecture are distinct. Start game tasks at `docs/game/MASTER_ARCHITECTURE.md`, then load only the owning domain and interfaces. `docs/game/REPO_MAP.md` records inspected boundaries.
- Preserve HistoricalTruth / Reconstruction / GameplaySimulation. Never upgrade a candidate or simulation output merely because it has a source ID or passes a schema.
- Game code may depend on shared contracts, not Driver/Deliver internals. External research/build calls stay outside simulation ticks. No NEXT chain for game agents.
- Keep provenance, units, time precision, stable identity and variant matching. Historical evidence, visuals, experience and performance are separate quality dimensions.
- Before assigning work, bind role/task/read-write scope, relevant evidence and contract versions. Additional context is an explicit expansion; dependencies grant interfaces, not entire domains.
- Each capability has one owner. Serialize shared schema edits; request owner changes across domains. Do not overwrite unrelated dirty work.
- Run targeted local tests without network/paid actions for game contract proofs as described in `game/README.md`. Live graph writes or external execution follow their existing authorization, never inferred from a local test.
- Playable promotion requires independent historical, provenance, simulation/integration and ExperienceReview gates. Future VR compatibility must be checked at presentation/input/asset boundaries.
