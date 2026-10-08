# Context selection roots for Lego builders

This directory contains **planning packets and context entrypoints**, not installed agents or a production context sandbox. The concrete user-facing assignment file is `docs/game/LEGO_BUILD_CATALOG_HE.md`.

Every future run selects five layers:

1. GlobalInvariantContext: `global/INVARIANTS.md`.
2. DomainContext: the relevant domain entrypoint and assigned role card only.
3. TaskContext: one `build_packets/<id>/BRIEF.md`, plus the exact task/revision/acceptance scope.
4. DependencyContext: selected public interface contracts from `interfaces/`; no producer implementation by default.
5. EvidenceContext: actual source snippets/crops/data for the selected entity, date and place with provenance. This repository scaffold does not supply missing historical evidence.

`domains/`, `evidence/`, `episodes/`, `runs/` and `npc/` are separate namespaces. Only prepared files listed in a run manifest enter model context. Do not load all of this directory or all of `docs/game/`. Unavailable evidence triggers a research gap. A task may use a clearly labeled synthetic fixture until historical data is approved.

The existing `game/prototype/context_router.py` only selects trusted in-memory references. Materialization, tokenization, actor authorization, filesystem isolation and live model execution require later implementation. Agent/model selections in the catalog are recommendations; no Claude or Codex worker is automatically launched from these files.
