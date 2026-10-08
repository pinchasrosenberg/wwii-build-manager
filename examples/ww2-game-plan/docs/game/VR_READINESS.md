# VR readiness and presentation-stack decision

Research date: **2026-09-27**. Status: **design decision with untested hardware/build gates**. No engine, SDK or headset software was installed; no device was accessed. Headset model, host PC, runtime and availability are unknown.

## Decision

Select **Godot 4.7.2, core OpenXR, and an isolated typed domain/data module running in Godot** as the provisional M1 stack. Run the same domain module and physics backend with presentation disabled in headless mode. Build a compelling desktop game first, while proving the VR technical boundary in **M1**. VR is a required future delivery path, not a promise that can be satisfied by an interchangeable camera alone.

This changes the earlier Bevy-first recommendation: first-party stereo/session/input integration, a documented Quest/Android export route and integrated animation authoring provide a material advantage for this requirement. Unity is the principal alternative if Godot cannot meet standalone interaction/performance needs; Unreal is a strong alternative when PCVR visual/character production dominates. Bevy has a real, developing OpenXR implementation, but accepting its additional integration burden requires evidence from the exact package and device combination.

This decision preserves the separation of **HistoricalTruth**, **Reconstruction** and **Gameplay**, provenance/uncertainty, reusable data-defined capabilities, deterministic scoped context, explicit command/event contracts and headless execution. The game engine cannot import Deliver internals. Desktop and VR are presentations of the same accepted scenario state; accessibility or lethality profiles do not rewrite historical evidence.

**Engine-neutral schemas and module boundaries are mandatory; an engine-free executable is not.** Godot already supports GPU-free headless execution and typed GDScript. No evidence reviewed requires Rust for the initial locality/squad slice. Keep one runtime/backend initially, avoiding mandatory FFI, native Android packaging and duplicate physics integration. Rust is a later option if profiling, scale or an external-consumer requirement justifies extraction. [Headless export](https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_dedicated_servers.html), [typed GDScript](https://docs.godotengine.org/en/stable/tutorials/scripting/gdscript/static_typing.html)

## Current evidence and its limits

Official release pages identify Godot **4.7.2-stable**, Bevy **0.19.1**, and Fyrox **1.0.0**. The [stack evaluation](STACK_EVALUATION.md) records that broader evidence. The table below adds the sources that matter specifically for VR. “Documented” does not mean tested in this project.

| Candidate | Current implementation / exact version evidence | Practical coverage | Decision |
|---|---|---|---|
| **Godot** | OpenXR is a core engine interface. Godot OpenXR Vendors **5.1.0-stable** explicitly requires Godot **4.6+**. [Core setup](https://docs.godotengine.org/en/stable/tutorials/xr/setting_up_xr.html), [vendor release](https://github.com/GodotVR/godot_openxr_vendors/releases) | Official features list desktop OpenXR/SteamVR, Quest over Link and standalone Quest 1/2/3/Pro. Stereo camera and tracked controllers are core nodes; hand tracking is documented separately. [Devices](https://docs.godotengine.org/en/4.7/about/list_of_features.html#xr-support-ar-and-vr), [hands](https://docs.godotengine.org/en/stable/tutorials/xr/openxr_hand_tracking.html) | **Baseline.** Strongest verified open-source integration route here; still requires renderer/export/device proof. |
| **Bevy** | Community `bevy_mod_openxr`, not an engine-core XR feature. docs.rs shows **0.6.0**. Development workspace says **0.6.0**, Bevy **0.19**, wgpu **29**, OpenXR Rust crate **0.21.1**; internal path dependency version declarations still say **0.5.0**. GitHub's latest release entry is **0.4.0 for Bevy 0.17**. [API](https://docs.rs/bevy_mod_openxr/latest/bevy_mod_openxr/), [workspace](https://raw.githubusercontent.com/awtterpip/bevy_oxr/main/Cargo.toml), [releases](https://github.com/awtterpip/bevy_oxr/releases) | Vulkan is the plugin default; a D3D12 feature and Android support are present. Android example targets ARM64 and declares Quest VR/hand-tracking features. These demonstrate implementation work, not a supported-device guarantee or app-store readiness. [Plugin manifest](https://raw.githubusercontent.com/awtterpip/bevy_oxr/main/crates/bevy_openxr/Cargo.toml), [Android example](https://raw.githubusercontent.com/awtterpip/bevy_oxr/main/crates/bevy_openxr/examples/android/Cargo.toml) | **Challenger, not default.** Package publication, repository release and development metadata disagree; published 0.6 dependency closure was not retrievable in this review. Resolve and compile exact versions before claiming 0.19 compatibility. |
| **Fyrox** | 1.0.0, native editor and headless operation verified. No maintained current OpenXR module, version matrix or Quest/PCVR deployment guide was verified from official engine sources. [Release](https://fyrox.rs/blog/post/fyrox-game-engine-1-0-0/), [book](https://fyrox-book.github.io/) | **Unknown**, not evidence of impossibility. | Does not meet the current VR-readiness evidence gate. |
| **Unity** | Vendor-maintained OpenXR package; sampled documentation is **1.16.1** and declares Editor **2022.3 LTS+** compatibility. XR Interaction Toolkit and XR Hands are separate official packages. These are inspected versions, not a claim of the latest compatible package set. [OpenXR](https://docs.unity3d.com/Packages/com.unity.xr.openxr@1.16/manual/index.html), [interaction toolkit](https://docs.unity3d.com/Packages/com.unity.xr.interaction.toolkit@3.3/manual/index.html), [XR Hands](https://docs.unity3d.com/Packages/com.unity.xr.hands@1.9/manual/index.html) | OpenXR docs explicitly list Windows PC/Link/SteamVR and Android ARM64 Quest. Meta-specific extensions and hand input require the relevant packages/features. [Meta packages](https://docs.unity.com/en-us/engine/6000.3/manual/xr/configuring-project-for/meta-quest-develop/packages) | **Strong fallback**, particularly for standalone interactions and provider tooling. Preserve domain schemas and parity fixtures; a GDScript implementation would need porting or later extraction. Licensing/package closure needs separate selection. |
| **Unreal** | Engine OpenXR plugin, VR Template, and `OpenXRHandTracking` for `XR_EXT_hand_tracking`. Inspected rolling documentation identifies UE 5.8; a production engine/SDK version set has not been pinned. [Template](https://dev.epicgames.com/documentation/unreal-engine/vr-template-in-unreal-engine), [hands plugin](https://dev.epicgames.com/documentation/unreal-engine/API/PluginIndex/OpenXRHandTracking) | Official device table covers Quest, Link and desktop headsets; template provides grab, teleport and snap-turn. Device/vendor-specific capabilities require checking. [Devices](https://dev.epicgames.com/documentation/unreal-engine/supported-xr-devices-in-unreal-engine), [runtime setup](https://dev.epicgames.com/documentation/unreal-engine/openxr-prerequisites-in-unreal-engine) | **Strong PCVR/content alternative.** Standalone remains a separate optimization target; high-end desktop rendering features do not prove Quest performance. |

Bevy's work should not be described as abandoned or merely theoretical. Equally, a current manifest and a stereo example do not establish controller-profile coverage, thermal stability, comfortable locomotion, mature hand interaction, portable materials or production support. Those are the reasons to prefer Godot under the current requirement.

The current macOS development environment establishes no working PCVR runtime. Do not equate macOS desktop export with headset support. Godot's 4.7 feature list explicitly limits visionOS to a flat application plane and excludes immersive experiences; **Apple Vision Pro immersive delivery is not included in this recommendation**. If that becomes the target, reopen the engine decision. [Godot platform scope](https://docs.godotengine.org/en/4.7/about/list_of_features.html#xr-support-ar-and-vr)

## Godot route: what is established and what must be tested

| Area | Verified route | Project requirement |
|---|---|---|
| Stereo / tracking | `XROrigin3D`, `XRCamera3D` and `XRController3D`; XR runtime owns tracked camera updates and frame synchronization. [Setup](https://docs.godotengine.org/en/stable/tutorials/xr/setting_up_xr.html) | One tracked rig; desktop camera is a separate adapter. Test stereo geometry, controller poses and runtime failure fallback. |
| Controller actions | OpenXR action maps associate semantic actions and interaction profiles. [Action maps](https://docs.godotengine.org/en/stable/tutorials/xr/xr_action_map.html) | Map actions such as inspect, select, grip, order, locomote and turn to domain commands. Controller model/button names must not enter simulation rules. |
| Optical hands | Hand tracking is distinct from controller actions; Godot supplies hand trackers and skeleton modifiers. Runtime capability gaps are explicitly documented. [Hand tracking](https://docs.godotengine.org/en/stable/tutorials/xr/openxr_hand_tracking.html) | Controllers are the first complete input path. Hands are optional with an explicit unsupported/tracking-lost fallback. No assumption that Quest standalone hand features work over PC Link. |
| Android / Quest | Godot documents Gradle/OpenXR export; since 4.6 vendor plugin is optional but recommended and may be needed for store/vendor features. [Android deployment](https://docs.godotengine.org/en/stable/tutorials/xr/deploying_to_android.html) | Pin engine, export templates, vendor plugin and required Android tools. Produce a separate ARM64 standalone preset; PCVR success does not validate it. Custom native-library packaging is required only if such code is later introduced. |
| Renderer | Core XR setup recommends Mobile for desktop VR/Quest 3; the Android deployment page still advises Compatibility while discussing Vulkan limitations. [Setup](https://docs.godotengine.org/en/stable/tutorials/xr/setting_up_xr.html), [Android](https://docs.godotengine.org/en/stable/tutorials/xr/deploying_to_android.html) | **Documentation inconsistency:** measure Mobile/Vulkan and Compatibility on the target runtime using the same small scene. Prefer Mobile/Vulkan as the initial candidate, keep Compatibility as a tested fallback; no unsupported promise of parity. |
| Runtime/backend | March 2026 engine update documents Android Khronos-loader integration and recommends Vulkan on Windows for Mobile/Forward+ XR. [XR update](https://godotengine.org/article/godot-xr-update-mar-2026/) | Select the active runtime and graphics backend explicitly. Store runtime version and enabled extension list in every result. |
| Performance features | Godot documents fixed/dynamic foveation and VRS paths with hardware/renderer restrictions. Some post-processing conflicts with them; depth submission/frame synthesis also has limits. [Settings](https://docs.godotengine.org/en/stable/tutorials/xr/openxr_settings.html) | Measure native stereo before enabling these optimizations. Do not count reprojection or frame synthesis as passing the native frame budget. |

OpenXR standardizes an interface; it does not standardize every vendor feature, remove SDK packaging, or guarantee identical visuals and input across devices. A future port still needs interaction design, asset reduction and device validation.

## Boundaries to implement in M1

```text
Desktop mouse/gamepad ──> semantic intent ──┐
OpenXR actions/poses ───> VR intent adapter ├─> accepted commands ─> typed domain module
Recorded input ────────> replay adapter ───┘                              │
                                                             snapshots/events
                                                                         │
                                            Godot scene/audio/avatar adapters

Live-headless runner ──> same domain module + same Godot/Jolt physics port
Event-replay runner ───> same domain module + recorded outcome port
```

The following are application design requirements, not claims supplied by an engine:

1. **Rendering:** use engine-owned stereo projections and eye poses. No manual inter-pupillary-distance hack, one-eye shader assumptions or screen-space gameplay dependencies. Every material/effect used in the shared scene must render correctly in both eyes. Desktop-only effects are feature-gated.
2. **Input:** separate pose sampling from accepted actions. Poses carry reference-space ID, timestamp, validity and tracking status; commands carry actor ID, target ID and simulation tick. Desktop ray, controller ray and direct-hand interaction invoke the same capability validator. Never send every raw tracking update through the history or character-reasoning pipeline.
3. **Avatar:** distinguish tracked head/hands from inferred body/feet and authoritative collision capsule. IK is presentation; inferred poses are not measured truth. Support left/right hand roles, seated/standing use, different heights and controller fallback. Character head motion must not override the user's tracked view.
4. **Scale / physics:** one local engine unit represents one metre. High-precision domain/world coordinates convert to a cell-local frame. Recenter or world-origin shifts preserve object identity, grip anchors and relative positions. Tracked hands should not inject unbounded forces; apply validated reach and contact behavior. Headset physical movement is not forcibly pulled by a spring or a ragdoll.
5. **Locomotion / comfort:** preserve room-scale movement; expose snap turn and optional smooth movement. Teleport, if present, respects navigation and scenario permissions and is labelled as an experience affordance. No compulsory camera shake, bob, roll, FOV kicks or cutscene takeover in VR. A player can pause/exit and recalibrate without changing historical facts.
6. **UI:** journal, orders and subtitles have a spatial presentation with appropriate depth and user-adjustable size. Interaction feedback cannot rely on a tiny flat HUD or hover alone. Test Hebrew/RTL, contrast, selection feedback, controller ray and seated reach. Keep evidence detail available on demand without filling the scene with panels.
7. **Audio / haptics:** world sounds are anchored to world objects and listener orientation follows the head. Test distance, left/right localization, indoor/outdoor transitions and subtitle direction cues. Select/verify a spatial-audio path; the presence of 3D panning alone does not establish HRTF quality. Haptics are optional feedback and never the sole acknowledgement.
8. **Lifecycle:** runtime unavailable, focus loss, controller loss, headset removal, recenter, suspend/resume and reconnection have explicit transitions. Input stops cleanly when tracking/session validity fails; no stuck grip, stale trigger or runaway movement.
9. **Domain isolation:** typed data classes and explicit step/command/result APIs contain no scene lookup, camera, UI, audio, raw input or Deliver dependency. Godot data types can be internal implementation details; exported schemas use portable scalar/record definitions, units and stable IDs. Physics/navigation are internal ports so a headless runner can load the same backend without the visual scene. No FFI or second runtime is required in M1.

For deterministic replay, domain decisions and accepted physical outcomes are logged. Rendering/tracking/IK may vary without rewriting them. **Live-headless integration** reruns Godot/Jolt with the pinned build/backend, input order and fixed-step settings; identical hashes remain a test obligation, not an automatic property of headless mode. **Recorded-outcome replay** feeds accepted physics/navigation/external events into the domain module and checks the resulting state; it does not validate a fresh physical simulation. Keep these two proofs separate.

If later profiling justifies a Rust/native module, extract one measured hotspot behind the existing port. Preserve schema and replay fixtures; validate desktop and Android ARM64 builds, ABI/binding versions, packaging and error handling before adoption. A later engine-free replay executable is a separate deliverable and must declare whether it reruns physics or consumes recorded outcomes.

## Asset portability and rendering budgets

Keep source assets and engine-independent exports: glTF meshes/rigs/clips where supported, original textures/audio, collision descriptions, attachment/grip points, material intent, LODs and provenance/license sidecars. Preserve metric scale and coordinate conversion. Scene graphs, animation state machines, shader code, import settings and light bakes are engine adapters; they will require work in another engine.

Build three explicit profiles from the same scenario: `desktop`, `pcvr`, `standalone_vr`. Profiles can vary resolution, shadows, particles, material complexity, visible crowd detail and animation update rates. They cannot silently change the facts, scenario identity, accepted player choices or capability semantics. Any intentional simulation-LOD approximation is recorded and tested separately.

Start the standalone fixture with one locality, 3–5 companions, a limited number of visible skinned bodies, baked/cheap lighting, restrained transparency and no required screen-space post-effects. This is an initial content scope, not a verified maximum. Use object/texture/animation budgets tied to measured CPU/GPU time and resident memory; do not invent a universal triangle or draw-call limit.

The following are **proposed application budgets**, not measured performance or vendor certification:

| Selected headset mode | Frame interval | Initial p95 application CPU and GPU budgets, each | p99 requirement |
|---|---:|---:|---:|
| 72 Hz, if supported | 13.89 ms | ≤11.1 ms | Each below 13.89 ms |
| 90 Hz, if supported | 11.11 ms | ≤8.9 ms | Each below 11.11 ms |
| 120 Hz, only if targeted | 8.33 ms | ≤6.7 ms | Each below 8.33 ms |

CPU and GPU measurements are separate because work can overlap; summing them is not the frame metric. Record runtime/compositor missed frames, resolution **per eye**, refresh rate, reprojection state and thermal conditions. Budget headroom does not prove motion-to-photon latency. No recurrent hitch above one display interval in steady traversal; capture shader compilation and cold-load stalls separately. Before VR release, repeat after at least 20 minutes on the standalone device and verify memory settles after repeated cell traversal. Desktop 60 FPS is not a VR pass.

## M1 acceptance and later device validation

| Gate | Required evidence | Present status |
|---|---|---|
| VR architecture seam | Desktop and replay providers drive the same semantic actions as a simulated XR provider; rig/session/pose logic is outside domain rules. Domain cannot depend on presentation or Deliver internals; portable contracts may have a Godot-hosted implementation. | **Design only — not implemented.** |
| Build/export | Pinned desktop build, Godot headless runner with the same backend, and Android ARM64 export with vendor configuration. Record hashes and versions. No custom native library is required for M1. | **Not built.** |
| Stereo/content audit | Representative ground, foliage, hands, transparent surfaces, sky, light, journal and text have stereo-compatible implementations and profile fallbacks. | **Not tested.** |
| Hardware smoke, required when a device is available | Launch native stereo; inspect reference-scale objects; move/turn; use both controllers; grab/inspect/place an object; read an order; recenter; lose/recover focus; suspend/resume. Record at least five minutes of frame timing and lifecycle results. | **Not tested — hardware availability unknown.** |
| PCVR route | Record host GPU/OS, headset, runtime/version, graphics backend and connection type; pass smoke test without a device-specific gameplay fork. | **Not tested.** |
| Standalone route | Install signed development APK on the declared Quest/Android device; exercise the same interaction. Compare Mobile/Vulkan and Compatibility on equivalent content; record chosen preset and differences. | **Not tested.** |
| Domain parity | Given the same accepted commands/outcomes, desktop, XR-driven integration and headless replay produce the same canonical event/state hashes. Physics determinism domain is explicit. | **Not tested.** |
| Human experience | First desktop gate: at least three unfamiliar testers; all can state role and one consequence; at least two wish to continue; no blocking controls/readability failure. [Experience gate](EXPERIENCE_DESIGN.md) | **Not tested.** |
| Later VR experience | Repeat formative assessment in headset, including quiet interaction, readable orders, companion attachment and comfort. Any blocking tracking, readability or discomfort issue requires design work. This does not replace desktop playtesting. | **Not tested.** |

Without hardware, M1 may be reported as **desktop slice + VR seams complete; headset validation pending** only after its non-device work actually passes. It may not be reported as “VR ready” or “VR compatible.” The missing hardware result does not stop useful desktop development; it does block a claim of successful VR transfer.

Headset acquisition/selection is an open input, not an action performed by this task. Once selected, lock its refresh/resolution/interaction target before tuning. Optical hand tracking, body/eye tracking, passthrough and multiplayer VR remain optional capabilities with detection/fallback, unless the user makes one a requirement.

## Decision revisit and migration

Promote Godot from provisional only after the embodied desktop slice, domain/headless isolation and actual target-device smoke test pass. Reopen selection if Android export cannot be maintained, the required input/extension path is missing, or the measured target scene repeatedly fails performance/comfort despite a bounded optimization attempt. Compare Unity or Unreal using the same scenario, assets and acceptance script; a replacement must preserve headless automation and historical boundaries.

Moving between engines should preserve scenario manifests, provenance, capability definitions, stable IDs, commands/events, parity fixtures, save schemas and source assets. The initial GDScript domain implementation, rendering, rig setup, controller bindings, animation graphs, UI layouts, materials and importer settings may require porting. Engine-neutral contracts preserve meaning and test expectations; they do not make implementation code automatically portable. A later native core may reduce that work only after its own integration costs are justified.

Follow-up work: lock Godot/export/vendor versions, create the isolated typed domain module and shared desktop/VR rig, prove live-headless and recorded-outcome replay separately, establish Android packaging, then run the first available headset. Current task output is the decision and test contract, with no benchmark or compatibility pass implied.
