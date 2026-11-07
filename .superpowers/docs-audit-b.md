# How-to documentation accuracy audit, part b

Audited all 21 Markdown pages in `docs/how-to/` against branch tip
`469c35c9802afaccf20686bcd238eac51ed5336a`. Changed 20 pages; the index needed no
correction. No Python, example, website, generated API, screenshot, or research-board
source was edited. This report is the requested exception outside the owned pages.

Counts: **21 pages checked; 20 pages changed; 3 code-looks-wrong items; 18 unverified
claim groups; 0 stale screenshots.** One stale diagram is listed separately below.
An unverified group can cover several related sentences or measurements. Claims in
those groups remain in the pages, as instructed. Source comments repeating a
measurement were not treated as a reproduction of that measurement.

## Per-page findings

All paths in this table are relative to the repository root. A dash means no open
finding in that category. Screenshots are absent from every page; the one diagram
reference is identified as V1.

| Page in `docs/how-to/` | Change and reason, with implementation evidence | Open findings |
| --- | --- | --- |
| `index.md` | Checked, unchanged. The classification example uses CatBoost with RMS/MAV (`examples/synthetic/emg_classification.py:91`); regression learns five digit outputs (`examples/controls/regression.toml:11`, `examples/synthetic/emg_regression.py:86`). Guide descriptions match the owned pages. | — |
| `add-a-model.md` | Replaced the obsolete whole-pose VHI outlet example with a named `ControlBus` command. Corrected Save to disabled when a model/save callback is missing. `myogestic/remote/target.py:406`, `myogestic/_controls_bus.py:282`, `myogestic/ml/widgets.py:156`. Checked decorators, arbitrary model ownership, prediction dict replacement and training thread against `myogestic/ml/pipeline.py:218`, `:258`, `:370`. | U1, U14 |
| `add-a-source.md` | Added explicit connection and checked its result; connection errors live in `Stream.last_error`, not automatically in the global status message. Corrected SerialSource from line parsing to fixed-width binary floats. Made the CSV example preserve both dimensions for single-row input. `myogestic/stream.py:361`, `:412`, `:465`; `myogestic/sources/serial_source.py:48`; `numpy.loadtxt(..., ndmin=2)` was also exercised locally. Protocol, timestamp shape and default dtype match `myogestic/stream.py:62`, `:116`, `:618`. | — |
| `add-a-target.md` | Corrected the thread contract: bind runs on the constructing caller, and send can also run for UI selections or teardown. Clarified the `None` capability result and added user-owned teardown guidance. `myogestic/_controls_bus.py:213`, `:327`, `:351`, `:376`, `:465`. The two shipped target commands were run and their output matched the page. | — |
| `add-a-widget.md` | Replaced the claim that reconnect mutates the stream registry with the actual add/remove lifecycle. `myogestic/core.py:401`, `:434`; reconnect reallocates the same stream at `myogestic/stream.py:432`. Checked the shared scan cache at `myogestic/widgets/signals/_scan.py:54` and prediction reference replacement at `myogestic/ml/pipeline.py:397`. | — |
| `add-an-output.md` | Added an app cleanup hook for the user-owned telemetry socket. Outlet does not register with App and starts its own send thread. `myogestic/outputs/outlet.py:87`, `:104`, `:167`; `myogestic/core.py:804`. Latest-wins pacing and exception handling match `myogestic/outputs/outlet.py:113`. | — |
| `connect-otb-devices.md` | Added `reconnect()` to each standalone stream example. `start()` starts acquisition but never connects. Imported Stream in the Quattrocento example and distinguished 192 exposed biosignal channels from 216 wire channels. `myogestic/stream.py:361`, `:465`; `myogestic/sources/otb/quattrocento.py:74`, `:83`, `:116`. Checked geometry, conversion constants, width probing and dropout counters against `myogestic/sources/otb/_constants.py`, `muovi.py:34`, `sessantaquattro.py:66`, `:218`. | U2 |
| `drive-a-remote-target.md` | Restricted one-stream-per-DOF wording to continuous controls; discrete changes use gRPC. `myogestic/remote/target.py:406`, `:492`. Checked RPC names and address-keyed payloads against `myogestic/remote/_proto/remote_control.proto:195`; queue/deadline behaviour against `myogestic/remote/_control.py:33`, `:115`, `:312`; reference-target limitations against `examples/synthetic/reference_target.py:83`, `:101`. | U3, U4 |
| `enable-recording.md` | Added explicit connection, class names on Context, synchronous headless finalisation and normal signal exit. Corrected recording/predicting lifecycle order, connected-stream scope, codec-pipeline wording, classification boundary handling and midpoint alignment. `myogestic/core.py:510`, `:571`, `:603`, `:798`; `myogestic/session/_core.py:38`, `:681`, `:863`, `:964`; `myogestic/session/_windows.py:157`, `:597`. Checked participant paths and archive stems against `myogestic/session/_core.py:270`, `:358`, `:432`, `:626`, and RecordButton labels/dialog at `myogestic/widgets/panels/recording.py:355`, `:495`. | C2, U5 |
| `feature-extraction-cookbook.md` | Stopped claiming the bandpass snippet applies a notch, corrected SciPy to a direct dependency, corrected onset output to a one-element float32 array, and explained that training must explicitly reuse the feature code. `pyproject.toml:31`; `myogestic/ml/pipeline.py:293`, `:393`. Ran all six concrete extraction recipes, including MyoVerse. The sliding example gives 22 windows at 400 samples, as stated. | U6 |
| `headless-mode.md` | Added checked connection everywhere, persisted protocol class names, used `stop_recording(wait=True)`, and replaced the hard-exit service with signals that return through cleanup. Removed the ineffective no-stream test (`start_recording` still creates a session with zero streams). Fixed LSLOutlet input to an ndarray and registered output teardown. `myogestic/core.py:510`, `:571`, `:798`, `:1018`; `myogestic/stream.py:465`; `myogestic/outputs/lsl.py:111`. Explained that the unattended script must first be saved by the reader. All four snippets were run against a local LSL fixture. | — |
| `install-vhi.md` | Replaced rejected v1 example pins with v2.1.0, the running-target floor in `myogestic/vhi/interfaces.py:323`. Corrected destination handling (`VHI_PATH` is launcher-only), missing-digest behaviour, unresolved-latest handling, marker use, and Python `godot_bin` argument spelling. `myogestic/tools/install_vhi.py:81`, `:133`, `:173`, `:216`, `:341`, `:383`; `myogestic/vhi/interfaces.py:88`, `:254`. CLI help and temporary-fixture installer runs verified the local mechanics. | C1, C3, U7, U8, U9, U10 |
| `integrate-vhi.md` | Corrected continuous/discrete transport, checkout/user-root search order, Launch button text, Godot override precedence, and the overly broad claim that every example uses VHI. Replaced a manifest-inspection command that can move the hand with the read-only map inspector and supplied the viewer's stream flag. `myogestic/vhi/interfaces.py:170`, `:210`, `:254`; `myogestic/remote/target.py:492`; `myogestic/widgets/panels/process_launcher.py:406`; `tools/inspect_control.py:130`; `tools/inspect_control_map.py:110`. Checked movement palette against `myogestic/widgets/vhi/panel.py:38` and read-back layout against `myogestic/vhi/pose.py:47`. | U3, U11, V1 |
| `inter-stage-state.md` | Qualified callback scheduling to ticks with available input and obtained Context through `pipeline.app`. Removed the claim that all container reads are safe; dict/deque iteration can raise during mutation. `myogestic/ml/pipeline.py:173`, `:370`; shared stream reads use a lock at `myogestic/stream.py:753`. Local dict/deque iterator probes both reproduced RuntimeError after mutation. Checked model replacement and EdgeTrigger against `myogestic/ml/pipeline.py:293`, `myogestic/outputs/edge_trigger.py:77`. | — |
| `pick-a-device.md` | Added the opt-in `waveform="emg"` distinction while preserving sine as the picker/default source. Corrected green status to connection completion rather than first sample. Corrected the fixed float32 sample-memory factor from three to four, plus timestamps and workspaces: the ring has storage and unwrap arrays, alongside Stream's display and window arrays. `myogestic/sources/synthetic.py:111`; `myogestic/widgets/signals/device_picker.py:266`; `myogestic/stream.py:325`, `:432`; installed `dvg_ringbuffer.py:196`. Constructor/live options, labels, scopes and recording locks were checked against `device_picker.py:57`, `:80`, `:212`, `:482`, `:946`, `:1065` and `myogestic/core.py:401`. | U2, U12 |
| `post-process-output.md` | Used a named bus alias for device delivery and matched the visible One Euro label. `myogestic/remote/target.py:406`, `myogestic/_controls_bus.py:282`, `myogestic/widgets/panels/filter_processor.py:197`. Checked defaults, kernel, live reconfiguration, reset, latency UI and display-only viewer transforms against `myogestic/outputs/filters.py:113`, `:183`, `:259`; `myogestic/widgets/panels/filter_processor.py:150`, `:444`; `myogestic/widgets/signals/_controls.py:304`. | — |
| `record-and-replay.md` | Corrected callback call shape/initial label, removed the nonexistent skip-first rule, passed stored class names to `get_trials`, fixed midpoint alignment and averaging semantics, connected ReplaySource, and restricted timestamp comparison to a monotonic replay pass before wrap. `myogestic/widgets/panels/recording.py:696`; `myogestic/session/_core.py:1042`; `myogestic/session/_windows.py:157`, `:461`, `:579`; `myogestic/sources/replay.py:79`. Checked timed-take defaults/state machine at `myogestic/widgets/panels/recording.py:83`, `:589`, `:706`, take browsing at `myogestic/widgets/training/session_manager.py:131`, prediction capture at `myogestic/ml/pipeline.py:409`, `:457` and `examples/start_here/myocontrol.py:1315`, `:1339`. | — |
| `record-for-proportional-control.md` | Corrected “no dependencies” to NumPy-only for the directional decoder (`myogestic/recipes/estimators.py:17`, `:221`). Checked Pursuit defaults, phase routing, signed units, effort span threshold/count, gain-family rejection and session fallback against `myogestic/tracking.py:306`, `myogestic/session/_windows.py:208`, `myogestic/recipes/estimators.py:229`, `:307`, `:337`, `examples/start_here/pong.py:268`, `:275`. The runnable rehearsal is covered by the docs gate. | U13, U14, U15 |
| `record-good-training-data.md` | Removed skip-first and one-window-per-class claims, included the automatically inserted initial label, corrected seven 3-second holds to 21 seconds and 29 windows per full hold, and distinguished activations from windows in the rules-of-thumb table. Removed nonexistent automatic five-tick smoothing and the claim that gesture-to-gesture cues confuse the timestamp slicer. `myogestic/widgets/panels/recording.py:696`; `myogestic/session/_windows.py:157`; `myogestic/ml/pipeline.py:393`. Checked inspector/filter/preview UI at `myogestic/widgets/training/template_inspector.py:132`, `:206`, `:306` and `trial_preview.py:94`. | U16, U17 |
| `track-a-force-target.md` | Corrected the panel example to SyntheticForceSource, supplied mandatory `window_ms` and connection for the synthetic streams, and accounted for the optional stochastic SyntheticSource carrier. `examples/panels/tracking_task.py:37`; `myogestic/sources/force.py:59`; `myogestic/stream.py:236`, `:361`; `myogestic/sources/synthetic.py:111`. Checked trapezoid defaults, calibration, MVC timing, settings, record metadata, phase stream and midpoint alignment at `myogestic/tracking.py:106`, `:398`; `myogestic/widgets/tracking.py:295`, `:441`, `:495`, `:505`; `myogestic/sources/target.py:26`, `:129`; `myogestic/session/_windows.py:579`. | U2, U18 |
| `use-recipe-features.md` | Passed `windows["emg"]` rather than the whole windows dict to FeatureSelector. Replaced nonexistent `pipeline.state` with `pipeline.app.ctx.state`. `myogestic/ml/pipeline.py:173`, `:393`; `myogestic/widgets/training/feature_selector.py:128`. Checked feature count/shapes/dtypes, empty-selection failure and live toggles against `myogestic/recipes/features.py:23` and `feature_selector.py:76`, `:153`. | — |

## Code looks wrong: left unchanged for the coordinator

1. **C1: VHI replacement is not atomic.** Doc: `docs/how-to/install-vhi.md:18` promises
   atomic installation. Code: `myogestic/tools/install_vhi.py:434` removes the old
   destination before `shutil.move` at `:439`; that move can be a copy across filesystems.
   A failure loses the previous installation or exposes a partial replacement. A
   temporary-directory fixture observed that the destination no longer existed when
   replacement move began. The sensible atomicity promise was retained; no installer
   code was changed.
2. **C2: Crash-folder recovery cannot work as described.** Doc:
   `docs/how-to/enable-recording.md:282` says the raw folder can be opened or reattached
   and packed after a crash. Code: `myogestic/core.py:622` writes metadata only during
   stop/finalisation; `myogestic/session/_io.py:33` requires `meta.json` to open a folder.
   `myogestic/session/_core.py:626` creates a new folder, with no reattachment argument.
   A live-session fixture confirmed missing metadata, FileNotFoundError on open, and
   a different folder from a second constructor call. The recovery claim was retained
   as a missing-code issue, not replaced with an invented recovery API.
3. **C3: `--no-verify` has no runtime checksum warning.** Doc:
   `docs/how-to/install-vhi.md:91` promises a loud warning. Code:
   `myogestic/tools/install_vhi.py:414`, `:423` skips both digest lookup and `_verify`
   when the flag is supplied. The warning is inside `_verify` at `:224`, so it never
   runs for this flag. A fixture install with download/unpack replaced in memory
   emitted no checksum warning. The sensible warning promise was retained and the
   implementation was not edited.

## Unverified claims retained

These are 18 grouped findings, not 18 individual sentences. The implementation
supports the local API mechanics, but cannot establish these external, historical,
physiological or numerical claims. No campaign or external release audit was added.

| ID | Page and location | Claim that remains unverified |
| --- | --- | --- |
| U1 | `add-a-model.md:61`, `:65` | Unqualified CatBoost/sklearn/XGBoost pickle round trips and PyTorch/CUDA portability for the reader's own model. The local helper delegates to joblib; no XGBoost or CUDA test was performed. |
| U2 | `connect-otb-devices.md:11`; `pick-a-device.md:29`; `track-a-force-target.md:69` | Physical button/network setup, actual firmware accessory geometry and which device models have analogue inputs. Code implements the documented constants/probing; no amplifier or transducer was connected. |
| U3 | `drive-a-remote-target.md:34`, `:117`; `integrate-vhi.md:136`, `:164`, `:232` | A running external VHI's complete vocabulary, read-back width/type/rig anatomy, trajectory ownership/refusal, keyboard gating and archived-corpus observations. Client/proto/layout code agrees with the intended contract, but the VHI application and corpus are outside this checkout. |
| U4 | `drive-a-remote-target.md:122` | Historical claim that this repository shipped a backwards sign while its contract suite passed. No historical checkout or run evidence was supplied. |
| U5 | `enable-recording.md:147` | “Large sessions write and read meaningfully faster” with zarrs. Registration and extra installation were checked; no benchmark was run. |
| U6 | `feature-extraction-cookbook.md:72`, `:102`, `:179` | Universal 20–450 Hz/6 Hz recommendations, spectral recruitment/fatigue interpretations and task-specific feature recommendations. The numerical recipe implementations run, but do not establish the physiological advice. |
| U7 | `install-vhi.md:4`, `:39` | External VHI's exact Godot 4.5 requirement and .NET build requirement. No Godot project or VHI build was inspected. |
| U8 | `install-vhi.md:35`, `:84`, `:141` | “Until a 2.x release is published” and availability of the example v2.1.0 asset. The local minimum gates are verified; publication state and tag assets were not fetched. |
| U9 | `install-vhi.md:67` | Actual release asset matrix and Rosetta translation explanation. The installer maps those asset names but does not prove what the releases contain or how another machine executes them. |
| U10 | `install-vhi.md:96` | Ad-hoc signing/notarisation status, Gatekeeper/Popen guarantees and OS-version-specific Finder behaviour. Local code strips quarantine and prints advice, which does not establish those system-level guarantees. |
| U11 | `integrate-vhi.md:263` | Generic grpcurl interoperability with the running external server. No VHI server was present to check reflection or a proto-supplied call. |
| U12 | `pick-a-device.md:66`, `:75` | The agonist/antagonist physiological analogy and the claim that real recordings never offer the described signal-to-noise cue. Code verifies amplitude/direction/noise scaling, not that physiological generalisation. |
| U13 | `record-for-proportional-control.md:21`, `:32`, `:47`, `:223`, `:242`, `:249`, `:260`, `:269`, `:309` | Measured 30% dead zone, -0.34 output, 14x MAE gain, gain sweeps, staircase-versus-pursuit seed results, 165 qualifying windows, exact old/new fit equality, threshold table, direction-estimate MAE and mixed-force span collapse. Some numbers repeat in source docstrings, but no underlying recordings or measurement runner was available in the allowed sources. |
| U14 | `record-for-proportional-control.md:7`, `:25`, `:50`, `:64`; `add-a-model.md:189` | Universal estimator claims: three target values make every fit a three-class problem, a tree ensemble cannot emit an unseen level, linear models gain nothing, and raw-feature regression necessarily conflates direction/effort. These require model-specific evidence or a narrower statement, not just the recipe constructor. |
| U15 | `record-for-proportional-control.md:57`, `:66`, `:105` | Human inability to aim at a numeric level, universal sufficiency of eleven staircase holds and the fewer-than-about-sixteen-hops coverage heuristic. No participant or coverage comparison was reproduced. |
| U16 | `record-good-training-data.md:4`, `:39`, `:44`, `:52` | Most failures being training-data failures; minimum/comfortable recording counts and “within a few percent” performance. Fixed window arithmetic was corrected, but these empirical sufficiency claims have no supporting run here. |
| U17 | `record-good-training-data.md:57`, `:59`, `:60`, `:69`, `:70` | Two-second hold advice, cross-day variance ranking, electrode-placement diagnosis from appearance, 1–2 second amplifier settling and absolute synthetic-to-real non-transfer. No hardware/physiological study was part of this audit. |
| U18 | `track-a-force-target.md:6`, `:104`, `:209`, `:240`, `:365` | Force ramps as the standard motor-unit protocol, OTB acquisition-software behaviour, physiological recruitment/recovery rationale, guaranteed interpretation of calibrated force, look-ahead/memorisation claims and the general recommendation to train on holds. The trajectory/calibration calculations and UI behaviour are verified; those experimental claims are not. |

## Outdated screenshots and other visuals

- **Screenshots: none.** No Markdown image on these pages embeds a UI screenshot.
- **V1, one stale diagram:** `integrate-vhi.md:17` embeds
  `docs/images/vhi-integration.svg`. Its description at `:16` attributes current
  movement state to GetControlManifest; the implementation requests that state through
  GetRecordingSessionState (`myogestic/remote/_recording.py:111`). The visible gRPC
  arrow at SVG `:74` includes SetRecordingSession under RemoteClient, but that call
  belongs to RecordingClient (`myogestic/remote/_recording.py:59`). The diagram was
  left untouched because images are outside this worker's owned pages. It is a
  diagram issue, not included in the stale-screenshot count.

## Commands and verification

- `uv run --extra dev pytest tests/test_docs.py -q`: **342 passed**.
- `cd website && npm run ci`, with Node 22 supplied by `npx -y -p node@22 -c
  'npm run ci'`: **passed**. Build, 61 legacy URLs, 5,646 internal links, 808 API
  symbols, 19 Vitest files / 80 tests and Playwright **41 passed / 3 skipped**.
  The skips are the existing context-loss browser case and the two playground
  wheel-dependent cases, not new audit exclusions. Log: `/tmp/docs-audit-b-ci.log`.
- The fresh worktree initially lacked npm dependencies (`astro: command not found`).
  Ran `npm ci` and `node scripts/sync-static.mjs`, then used Node 22 for CI. Existing
  Astro deprecation/pycon highlighting warnings remain outside this worker's scope.
- Ran `uv run python examples/synthetic/my_device.py` and
  `uv run python examples/synthetic/servo_hand.py`: both exited 0 and demonstrated
  the documented clamp/rest/serial frames.
- Ran `uv run --extra grpc python tools/inspect_control_map.py
  examples/controls/hand.toml` (the shipped fixture substituted for the reader's
  `my-map.toml`) and `uv run --extra grpc python tools/inspect_control.py`: both
  exited 0 and reported no live target. No hand was driven.
- Ran both installer entry points with `--help`, and ran `uv sync --extra zarrs`
  and `uv sync --extra examples`: exited 0. Actual release install/force/uninstall
  commands were not run because this audit does not install or remove the user's
  separate VHI application. Destination/version/checksum logic was checked with
  temporary fixtures and patched in-memory download/unpack functions instead.
- Ran `uv run python examples/synthetic/emg_classification.py` with a 6-second
  timeout. It reached the native GUI loop; the deliberate SIGINT ended it with 130.
  This establishes startup only, not the interactive train/predict workflow.
- Ran `uv run mne-lsl viewer --help` to verify `-s`. The full viewer command with
  `-s vhi.prediction.index` failed with `RuntimeError: No LSL stream found`, as no
  live target/outlet was present. No viewer session was claimed to work.
- Ran all four headless-page snippets and the enable-recording headless snippet
  unchanged from their Python fences in temporary scripts, with an 8-channel local
  `EMG` LSL outlet and a saved DummyClassifier for the prediction example. Interrupted
  each after 5 seconds, using SIGTERM for the service and SIGINT for the others.
  All five exited 0; each of the four recorders left one `.mg.zip`, and the predictor
  left none as intended. This checks connection and cleanup with a short capture,
  not completion of the documented 60-second/protocol durations.
- Ran all six cookbook extraction bodies on synthetic EMG/IMU windows. Shapes were
  `(192,)`, `(8,)`, `(32,)`, `(176,)`, `(1,)`, `(14,)`; MyoVerse's RMS/MAV sub-windows
  and SciPy operations executed successfully. Ran the CSV source with one-row and
  one-column temporary CSVs; both retained the expected two-dimensional shape.
- `git diff --check`: passed. No amplifier, VHI, CUDA model, scientific campaign,
  screenshot regeneration or research-board update was attempted.
