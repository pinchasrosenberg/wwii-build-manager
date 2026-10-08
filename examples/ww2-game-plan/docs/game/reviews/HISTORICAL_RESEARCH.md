# Historical reconstruction: bounded evidence review

Review date: 2026-09-27. Scope: local historical-map pipeline, source provenance, selected audit/runbook sections, one existing pilot's metadata, and one official archive-page access attempt. This is architecture research, not a new historical fact dataset or a live database audit. No whole corpus, master specification, graph database, or extraction run was loaded.

## Existing capabilities and their limits

| Evidence inspected | What exists | What cannot be concluded |
|---|---|---|
| [Historical maps README](../../../etl/historical_maps/README.md), selected `pipeline.py` contracts | Immutable annotation input, source hash/dimension validation, additive versioned evidence, independent discovery/routing/OCR/research/manpower stages; candidates remain non-factual | These do not supply a complete or verified playable battlefield |
| [Discovery visual QA, 2026-09-06](../../HISTORICAL_MAPS_DISCOVERY_VISUAL_QA_2026-09-06.md) | Six deliberately selected crops checked for readable labels, with source hashes and pixel coordinates | This is not random sampling, recall, unit identity, troop strength, or terrain verification |
| [Inventory, 2026-09-06](../../HISTORICAL_MAPS_INVENTORY_2026-09-06.md) | Dated inventory of map assets, 39 West annotation files, pilot metadata and known error patterns | Its local/remote counts are dated, not a fresh inventory; copied fortification lines are not independent confirmations; roads were an extraction gap |
| [Georeference checkpoint](../../MAP_GEOREFERENCE_DRIVER.md), `map_georeference.py` | Separate deterministic candidate georeference, control-point lineage, leave-one-out diagnostics, extrapolation and uncertainty | HIGH/MEDIUM are algorithm quality labels, not historical verification or tactical spatial accuracy |
| [Extraction audit, 2026-09-13](../../HISTORICAL_MAP_EXTRACTION_AUDIT_2026-09-13.md) | Run receipts document 15,693 source-pixel candidate observations and 3,401 gaps; zero historical promotions; new run final georeference did not execute | No map was end-to-end complete in that audit. The reported graph quarantine/disk pressure is a dated operational condition, not a current health check |
| [`map_graph_projection.py`](../../../etl/driver_runtime/map_graph_projection.py) | Additive, idempotent projection of archived candidates and gaps, with non-factual markers | A successful graph write does not resolve truth or identity |
| [`supervisor.py`, `promote_source_backed`](../../../etl/driver_runtime/supervisor.py) | Generic runtime automatic acceptance can set `EXPLICIT_FACT`, `safe_for_factual_answer=true` and `source_verified` for sourced candidates, with a fallback `automated-source-extraction` locator | These flags are insufficient for the game's historical acceptance policy; evidence and locators need revalidation |
| [`manpower.py`](../../../etl/historical_maps/manpower.py), [`manpower_cmh.json`](../../../data/historical_maps/curated/manpower_cmh.json), [checkpoint strength section](../../HISTORICAL_MAPS_CHECKPOINT.md) | Typed population/time semantics and 12 previously reviewed original-scan end-of-month U.S. Army ETO assigned-strength rows, preserving exclusions | These do not establish battle-local strength, unit composition, daily interpolation, or the illustrative 10,000-person fixture |

The September 8 georeference checkpoint reported 35 accepted candidate models and 7,854 candidate coordinates. The later September 13 audit says that **that later extraction run's** final georeference pass did not happen. These statements describe different runs and are not evidence that no georeferencing code or prior candidate geometry exists.

## Specific provenance findings

The inspected existing pilot is `12ag_1944_08_26`, identified locally with the Library of Congress item [HQ Twelfth Army Group situation map, August 26, 1944](https://www.loc.gov/item/2004629120/). A direct official-page request during this review returned HTTP 403, so no fresh archive metadata or rights verification is claimed. The date/title and pilot association here come from the existing repository metadata and dated audits.

The local tag file at `<atlas-etl>/data/raw/map_tags/12ag_1944_08_26.json` was read in a bounded inspection. It records:

- Image dimensions 6,360 × 5,886, source hash `e6cf1927c89105b50e6f7bfe4f63968de050f2dc3198b9e22207f24b766e9d25`.
- Registration to an August 25 reference, with transformation metadata.
- Approximate georeference metadata declaring 22 km estimated horizontal error and an explicit non-survey-grade warning.
- Symbol annotations with source-pixel boxes, model/review scores and estimated geographic centers. These scores and labels are retained metadata, not newly verified identity or position.

This review did not rehash the full source image, re-open its crops, inspect every annotation, resolve unit identities, or assess the accuracy of that declared error. Historical spatial uncertainty must not be confused with exact representation of a source pixel.

The separate current georeference source code uses an affine fit with RANSAC and inlier leave-one-out tests. Its HIGH acceptance threshold permits p95 cross-validation error up to 5 km, and MEDIUM up to 10 km. It preserves an extrapolation flag and candidate status. Its source controls can come from existing source-backed observations on the same map; fit quality and evidence independence are different questions. These thresholds cannot justify metre-scale gameplay placement.

Generic supervisor auto-acceptance is a concrete interoperability issue, not merely an old documentation inconsistency. It can supply the candidate text as a quotation when a source lacks a more specific evidence reference, and confidence is selected by validation status/source count. The new game importer must verify a retrievable locator in actual source content and inspect original candidate metadata. It must not inherit historical acceptance from graph labels or booleans. Records that fail remain available as unreviewed inputs with their original provenance.

## Conditional Episode #1 candidate

**Candidate: a bounded Western Front operational context on 26 August 1944, seeded by the existing `12ag_1944_08_26` package.** This is a provisional source-backed research starting point, not an asserted named engagement, assigned player unit, or approved playable battle. It is preferable for initial evidence work because this repository already references its image, annotations, literal crop checks, source identifier and reusable West processing path. No new historical event, participant, road, weather, equipment or casualty claim is introduced by selecting the source package.

The product target is an embodied role inside a source-confirmed unit: persistent companions, useful tasks, waiting and maintenance, local decisions and a bounded action. The exact role, unit, action and location remain conditional on evidence; this review does not invent them. A source-and-uncertainty scene is an internal authoring/review aid, not the player experience or the product's first episode. Promotion to a playable episode is conditional on a narrowly defined engagement/window passing all of these gates:

| Gate | Required evidence or decision | Current review result |
|---|---|---|
| Source integrity/access | Verify original image hash/dimensions, archive item/date, permitted distribution, and any derived asset transformations | Metadata exists; fresh hash and archive access/rights checks still required |
| Tactical choice | Identify one bounded action or mission with primary dated accounts and explicit scope, then select the playable causal domain | Not established from the inspected map evidence |
| Participants and strength | Resolve relevant unit identities, dated hierarchy, actual strength definitions and allocation bounds | Some symbol/identity candidate material exists; episode-level accepted roster absent in this review |
| Local terrain | Obtain and register period-appropriate detailed evidence for the chosen area; separate modern baselines | Operational georeference is insufficient for tactical placement |
| Equipment and weather | Establish date/unit/theater variant applicability and material local weather constraints | Not established in the inspected package |
| Skeleton and agency | Source-supported macro anchors/windows plus a feasible local influence domain and conflict policy | Must be authored after primary evidence review; do not invent a minute schedule |
| Evidence/physics QA | Check source lineage, uncertainty, constraint compatibility, visual/physical variant identity and sensitivity | Architecture acceptance cases proposed; implementation and results absent |
| Independent experience review | Embodied unit role, persistent people and consequences, useful quiet activities, meaningful local agency and intelligible assistance profiles | Not established by source audits; requires a playable prototype and independent review |

Until these gates pass, use explicit development/reconstruction labels and avoid marketing or menu text claiming a historically verified battle. A dense simulation of a documented map extent is not automatically a documented engagement. If evidence supports only operational context, retain it as authoring context and choose a better-supported local action after research; do not substitute a map-information tour for the requested living game.

## Episode #2 as a reuse test

**Conditional second candidate: a distinct bounded action/window seeded by one of the existing West sheets dated 28–30 August 1944.** The inventory reports an older LOC pipeline covering those three dates, while its georeference output directory was empty at that audit. Exact assets, provenance, local validity and historical action selection must be freshly checked. These dates are evidence-package candidates, not claims of a particular battle or continuous movement from Episode #1.

Use Episode #2 to test whether the architecture is reusable: a new evidence manifest and scene definition should be sufficient to reuse the source-region pipeline, uncertainty model, terrain/equipment/weather interfaces, skeleton validator and player conflict policy. No hard-coded unit IDs, outcomes, tactical coordinates or August 26 dates may leak into the second package. Source-family parser reuse does not permit reusing truth judgments or copying a first episode's roster/weather/terrain without fresh evidence.

Episode #2 passes the architecture reuse test only if it also exercises a meaningful new uncertainty or contradiction case, produces its own accepted/reconstructed split, and independently meets the same release gates. A new East-front source family is a later stress test; the bounded inventory found no reviewed East geometry, so choosing it as the immediate second release would conflate basic reuse validation with a larger new evidence/legend/georeference effort.

## Targeted research plan and stop conditions

Research is episode-scoped and uses official archive/catalog/government collections for new factual evidence. Begin with the exact existing archive item and source hash; then seek the chosen action's dated reports, operational records, orders/war diaries, detailed period maps or imagery, material equipment records and weather observations as needed. Archive catalog metadata can document a holding; it does not substitute for reading the page or image that supports a claim.

Record every search, query window, source/passage/crop, rejected match and explicit gap. Bound acquisition by the episode's proposed causal domain and highest-risk anchors. Prioritize evidence that could falsify an attractive scenario assumption. Stop expanding source acquisition once each release-critical field has adequate support or a documented reconstruction allowance and the conflict set is resolved; do not crawl the entire corpus to justify one small episode.

Before any future corpus rerun, inspect fresh health/storage state and current checkpoints. The dated extraction audit documents why replay, live database consistency and resource checks matter; this architecture task authorizes no new extraction, graph recovery, deletion, migration, or background process.

## Structured review summary

- **task:** Define historical reconstruction and progressive-fidelity architecture, grounded in the existing evidence pipeline.
- **status:** Architecture and bounded source review complete; no episode is certified or implemented.
- **artifacts:** [HISTORICAL_FIDELITY.md](../HISTORICAL_FIDELITY.md) and this review; canonical schema implementation is owned by the main architecture task.
- **used_context:** Small selected README/audit/checkpoint/code sections, pilot configuration and metadata, reviewed manpower transcription metadata; no master-spec or corpus-wide read.
- **evidence:** Source records and limitations listed above; one official LOC page attempted and blocked with HTTP 403; no new externally verified historical claims.
- **assumptions:** Append-only evidence is the invariant; the game can import a versioned local package independently of Deliver and live Neo4j; release scale is chosen only after evidence sufficiency.
- **uncertainties:** Current database/storage health, complete source availability/rights, local tactical registration, episode identities/strengths/weather/equipment and anchor timing have not been established here.
- **gaps:** Game trust adapter, independent field-level review, local terrain/variant/weather contracts in implementation, constrained reconstruction, explicit anchor conflict runtime, and migration tooling are proposed capabilities.
- **tests:** Documentation/link checks only for this contribution. Existing audit test counts describe their dated runs and are not rerun or current correctness evidence. Acceptance cases are specified in the fidelity document.
- **cost_estimate:** No paid model/extraction/bulk-download job was launched. This review used bounded local reads, two document writes and one official-page request. Episode production cost cannot be measured from these artifacts; estimate it after a small sampled evidence/terrain slice and record measured hours, assets, review effort and unresolved fields before scaling.
- **followups:** Main task to encode field constraints in canonical schemas, integrate the legacy trust gate, and budget a narrowly scoped primary-evidence pilot before approving playable Episode #1; Episode #2 then tests reuse independently.
