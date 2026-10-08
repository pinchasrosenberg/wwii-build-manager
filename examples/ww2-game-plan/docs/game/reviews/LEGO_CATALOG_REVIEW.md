# Lego build catalog review — 2026-09-27

Scope: the user's concrete request for reusable tank/weapon/variant/battle/weather/presentation Lego, single ownership, model routing and exact context packets. This review covers the build specification, not a completed game.

Three scoped subagents contributed the physical inventory, context/ownership design and current official Claude model research. Separate review passes examined the integrated catalog, state ownership, future VR gates and dispatch dependencies. The root consolidated their findings.

Resolved findings:

- Made the gun an assembly with explicit barrel, breech, feed, stock and action dependencies; retained historical variants as data rather than separate engine implementations.
- Added access ports, stowage, persistent surface state, fatigue/exposure, wearable equipment, environmental light, VFX and visual binding.
- Separated weather modifiers from terrain/actor state writers; wired SurfaceState to mobility/material consumers and obscurant/daylight/visibility interfaces to perception.
- Assigned player body presentation to experience_interface, authoritative human movement to infantry_actions and crew occupancy to ground_platform. Weapon-local mount configuration consumes platform transforms.
- Separated M1 desktop/seam proofs from real headset, stereo, comfort and target-performance gates. No mocked tracking is treated as a device test.
- Separated order content/authority from communications/delivery. Clarified that three concurrent workers is a limit across all packages, including subtasks.
- Added explicit runtime actor-projection and battle-evaluator TaskSlices, plus missing knowledge/dialogue/care/supply/order assignments.
- Removed the save/integration dependency cycle: an early continuity seam provides snapshot fixtures; final integration validates real save/replay after components are available.

The final registry has 158 types, 31 owner roles, 17 domains, 10 dispatch packages and 28 single-owner TaskSlices. The graph is a planning DAG, not an active scheduler. All package items are assigned to a task; future catalog items outside these initial packages remain intentionally unbuilt.

Validation: `python3 tools/game/render_lego_catalog.py` checked uniqueness, owner/domain/profile consistency, context files, packet references, single-owner task scopes, complete assignment of packet items and an acyclic dispatch graph. Results: [LEGO_CATALOG_CHECK.json](LEGO_CATALOG_CHECK.json). Relative links in the primary catalog were also checked locally.

Remaining implementation gates are explicit: runtime interface versions must be frozen by B00; historical dossiers, final variant definitions, assets/licenses, target hardware and device checks must be supplied by their build tasks. The existing Python M0 proofs remain separate prior work. No game runtime code, historical truth store, paid provider execution, Claude agent, 3D asset or headset test was created or run by this catalog task.
