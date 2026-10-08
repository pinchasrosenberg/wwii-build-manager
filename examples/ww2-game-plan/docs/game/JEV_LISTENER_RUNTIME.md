# Jev context gate and Deliver listeners

## Invariant

Every context bundle sent to any LLM must have an explicit Jev Choice decision. Deterministic graph/file search may discover and rank a bounded candidate set, but it cannot admit a context item into an LLM prompt. `no_match`, disabled Jev, authentication/network/schema errors and timeouts admit nothing. There is no context fallback.

This does not put Jev inside simulation ticks. Deterministic runtime systems continue locally. Jev is used at asynchronous build/research boundaries, where an LLM would otherwise receive context or a Deliver proposes follow-up listeners.

## State loop

```text
Deliver result
  -> versioned EpisodeState + BuildState
  -> event emitted by that Deliver
  -> only that Deliver's proposedListeners
  -> deterministic selector filter
  -> bounded candidate listener set
  -> Jev Choice(listener | no_match)
  -> selected activation(s), never automatic fan-out
  -> next Deliver result updates state
```

`EpisodeState` holds what is known, reconstructed or unknown about the episode: place, time, formations, weather, battle activities and evidence references. `BuildState` holds construction progress: Deliver statuses, missing capabilities, selected listeners, artifacts and review state. Both are versioned in `episode_build_states`. Every output is recorded in `deliver_state_events`; every selected edge is recorded in `listener_activations` and points to the exact Jev decision.

Each Deliver owns its outgoing proposals in `docs/game/DELIVER_LISTENER_CATALOG.json`. A proposal defines a stable listener ID, emitted event, target Deliver, deterministic `when` selector and reason. Registration is not activation. Prerequisite edges remain separate (`edge_type=prerequisite`, `jev_gate=0`) and cannot be confused with listeners.

This is a universal Lego build contract, not a weather special case. Every normal build worker must return a `listener_manifest` decision for every assigned `lego_id`. A decision either contains typed listener proposals or a concrete `no_listener_reason`. Missing/duplicate/unassigned Lego decisions make the handoff malformed and prevent acceptance. Valid proposals are registered under the source Deliver and source Lego. A proposed target that does not exist becomes a disabled `proposed` placeholder, so it is visible for planning but cannot execute. Rebuilding a Deliver disables its previous model-generated proposals before registering the new manifest.

## All LLM context

The manager first creates a local inventory. It groups it into a minimal task envelope and optional dependency, evidence, graph, retry and reference bundles. Jev sees bounded metadata for the shortlist and selects bundles sequentially. The required task envelope also needs an explicit selection; if it is rejected the worker does not run. Only selected paths are rendered into the final prompt. Excluded candidate names remain in the local manifest and dashboard and are not shown to the LLM.

Planner and repair prompts currently enter the same gate as a single prepared bundle. This is safe and auditable, while later work can split their internal contexts into smaller bundles without changing the invariant.

## Snow example

1. `episode.context_scan` is deterministic. It detects a possible winter/snow signal without claiming historical snow.
2. On `CONTEXT_SCANNED`, it proposes `snow.signal_to_research`.
3. The selector must first find a snow/winter signal. Jev then chooses the listener or `no_match`.
4. Only a selected listener activates `weather.snow_research`, an LLM research Deliver receiving Jev-selected evidence.
5. Its result preserves sources, uncertainty, type, timing, depth/range and surface condition. `weather.snow_state_compile` normalizes these fields without inventing unknown values.
6. `SNOW_STATE_READY` proposes surface, mobility, visibility and presentation listeners. Deterministic selectors remove irrelevant proposals based on snow and battle state; Jev selects at most the configured bounded number, never all by default.
7. Presentation consumes the simulation state and remains non-authoritative. The same state supports desktop and future VR rendering.

## Operations

```bash
tools/build_manager/bin/wwii-build import-plan
tools/build_manager/bin/wwii-build jev status
tools/build_manager/bin/wwii-build listener status
tools/build_manager/bin/wwii-build listener emit \
  --episode episode-001 \
  --source-deliver episode.context_scan \
  --event-type CONTEXT_SCANNED \
  --state /path/to/state-patch.json
```

Production routing uses the official Python SDK (`typesafe-sdk==0.7.2`), `TypeSafeClient.system_one` and the `Choice` primitive against `https://api.typesafe.ai/v1/systemone`. The official environment variable is `TYPESAFE_API_KEY`; the dashboard can store the same credential in macOS Keychain without putting it in the repository or SQLite. `jev status` performs a live model-list probe and a small Choice evaluation over existing Deliver IDs. TypeSafe's documented response provides per-call `input_tokens` and `output_tokens`; no balance endpoint is assumed.

The state patch is a JSON object with optional `objective`, `phase`, `episode`, `build`, `result` and `context_refs`. Live documentation refresh is `wwii-build jev docs-refresh`; it is a deliberate network action. TypeSafe's inspected live documentation exposes per-call token usage but no balance endpoint, so the dashboard labels configured usage as a local estimate and otherwise shows unknown.

The `/delivers` dashboard shows the Deliver graph, owned proposals, current episode/build state, selected activations, context provenance, exact Jev request previews, probabilities, tokens and latency. A green dashed edge is selected/running; a blue dashed edge is only proposed. Each Deliver has a control/detail page for its definition, model, hard dependencies, proposed listeners, context candidates, economics, attempt history and artifacts.

The prompt bar searches registered graph context deterministically, sends only compact candidates to Jev, and inserts only selected evidence into planner/advisor prompts. The Task Manager MCP server applies the same rule through `jev_selected_graph_query`; it also exposes bounded mutation tools for Delivers, listener proposals, dependencies, context candidates, economics and planner requests.

The existing local Graph RAG is available through the Hebrew **גרף RAG** control page and the Task Manager MCP tools. Planner requests have bounded full retrieval access. Each Deliver has an explicit `none`, `limited`, or `full` policy; limited mode disables generated Cypher and applies scope, chunk-count, and character caps. Retrieval output is split into candidates and remains fail-closed until Jev explicitly selects it.
