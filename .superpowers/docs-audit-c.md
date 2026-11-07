# Documentation accuracy audit, part c

Audited 2026-11-07 against `469c35c` on the worker branch derived from
`feat/astro-site`. Scope: every Markdown page in `docs/tutorials/`,
`docs/reference/` (including `otb/`) and `docs/images/`. Only those ten
pages and this report were edited. No source, screenshots, research-board
files, generated API pages or other workers' pages were edited.

Counts: **10 pages checked; 10 pages changed; 3 code-looks-wrong items;
9 unverified claim groups; 2 stale/misleading screenshots**.

## Per-page results

| Page | Changes and code evidence |
| --- | --- |
| `docs/tutorials/index.md` | Limited the snippet-include guarantee to the two tutorials that use it, and added the already-existing remote-target walkthrough to the list. Includes resolve to `examples/synthetic/emg_classification.py:69` and `examples/synthetic/emg_regression.py:81`; the remote walkthrough contains its own literal files rather than includes. |
| `docs/tutorials/emg-classification.md` | Added the `examples` extra to runnable training commands, retained optional `grpc`, marked the screenshot as the earlier UI, corrected `FeatureSelector`'s general concatenation contract, and required retraining after a feature-selection change. Evidence: `pyproject.toml:75`, `myogestic/recipes/estimators.py:47`, `myogestic/widgets/training/feature_selector.py:127`, `examples/synthetic/emg_classification.py:125`, `:250`, `:269`, `:352`. Checked the class names, constants, 200 ms/60 s window/buffer, optional-hand binding, movement palette, bus output and step layout. |
| `docs/tutorials/emg-regression-with-vhi.md` | Replaced the old ProcessLauncher-panel instructions with Connect and stream connections; named Record Rest/Fist and Stop correctly; replaced the removed control-outlet variable with `simulator.set`; explained continuous kinematic capture throughout the take; corrected construction versus resolution/bind validation, clipping before and after smoothing, the final `link.stop()` call, and the responsive two-column layout. Evidence: `examples/synthetic/emg_regression.py:125`, `:138`, `:192`, `:259`, `:288`, `:296`, `:311`, `:351`, `:485`; `myogestic/_controls_bus.py:296`; `myogestic/remote/target.py:198`. Kept the sensible training/prediction and class-filter descriptions pending C1/C2 rather than changing code. |
| `docs/tutorials/examples-index.md` | Corrected generator/in-process-source descriptions, optional-launch behavior and ML extras; added the missing electrode overview, high-channel viewer and reference target; removed the obsolete SWA claim; corrected myocontrol's two independent maps, take/model paths and Connect/Record/Train/Drive labels; corrected Pong's Record/Train/Play controls, difficulty location and dummy wrist source; removed wide-pose/channel-index language from the per-address operator-hand description and the false claim that no other example uses signed controls. Evidence: `examples/synthetic/electrode_overview.py:44`, `examples/synthetic/high_channel_viewer.py:25`, `examples/synthetic/reference_target.py:28`, `examples/synthetic/emg_regression_raulnet.py:354`, `examples/synthetic/vhi_control_hand.py:41`, `examples/start_here/myocontrol.py:106`, `:123`, `:130`, `:227`, `:283`, `:682`, `examples/start_here/pong.py:125`, `:142`, `:453`, `:468`, `:931`, `:1045`, `examples/start_here/force_ramps.py:74`, `myogestic/remote/target.py:406`. Checked all 13 synthetic examples and all three start_here protocols. |
| `docs/tutorials/your-first-remote-target.md` | Fixed the stage-1 main block's premature `rest_after_s` argument and moved the flag parser to stage 5 where the constructor gains that argument; added a printed Python PID and a real SIGKILL step so timed rest is tested without executing orderly teardown; qualified the four discrete RPC lines as successful-delivery output; made the one-channel wrong-producer variant use one-element samples; removed an obsolete line count. Evidence: the page's stage-1 `Rig.__init__` and staged constructor extension, `myogestic/remote/_control.py:115`, `:152`, `:289`, `myogestic/_controls_bus.py:352`, `:380`, `:396`, `:582`, `myogestic/remote/interfaces.py:116`, `examples/synthetic/reference_target.py:71`. Ran extracted files and negative probes; see command evidence below. |
| `docs/reference/index.md` | Replaced mkdocstrings with the actual griffe/Astro reference-generation path: `website/scripts/gen_api.py:135`, `website/src/markdown/api/render.ts:1`. No MkDocs/properdocs claims remain in the assigned pages. |
| `docs/reference/api-cheatsheet.md` | Corrected `get_display` to `(ts, data) | None`, raw-snapshot optionality, current/recent session lifetime, keyword-only parameters and defaults; added acquisition notch, relevant App/Pipeline options, the synthetic source's default sine and opt-in EMG waveform, capability/bus/connector arguments, participant-aware SessionManager, and aligned-window options. Removed a promise of API source links. Evidence: `myogestic/core.py:357`, `:571`, `:705`, `myogestic/stream.py:236`, `:753`, `:775`, `:788`, `myogestic/sources/lsl.py:76`, `myogestic/sources/synthetic.py:93`, `myogestic/_controls_map.py:320`, `myogestic/_controls_bus.py:177`, `:648`, `myogestic/ml/pipeline.py:173`, `myogestic/session/_windows.py:461`, and the constructors/ui methods of every listed widget (including `myogestic/widgets/training/session_manager.py:84`, `:125`, `myogestic/widgets/plots/heatmap.py:56`, `:74`). |
| `docs/reference/glossary.md` | Added acquisition conditioning as the previously missing third meaning of filter, made target capabilities optional, included the final labeled segment, documented the participant/kind archive and model layout, and corrected display snapshots to GUI-demand computation and prediction work to the predicting state. Evidence: `myogestic/stream.py:257`, `:507`, `:533`, `:775`, `myogestic/core.py:543`, `:561`, `:571`, `myogestic/session/_core.py:254`, `:390`, `:432`, `:459`, `:964`, `myogestic/session/_windows.py:95`, `myogestic/_controls_bus.py:83`, `myogestic/ml/pipeline.py:370`. |
| `docs/reference/otb/README.md` | Distinguished the MATLAB example's `0x80` stop byte from Python's mode-preserving stop packet. Evidence: `docs/reference/otb/Read_Quattrocento.m:214`, `myogestic/sources/otb/quattrocento.py:125`, `myogestic/sources/otb/_constants.py:223`. Checked the committed MATLAB version headers, endpoints, channel/rate tables, byte order, conversion factors, CRC and channel indices against `_constants.py:15`, `:178`, `:259`, `_decode.py:16`, `_crc.py:11` and the MATLAB files. |
| `docs/images/README.md` | Added the dev/Quartz requirement, the actual 7 s signal capture wait, missing registry entries and the Hello EMG output override; corrected current example launch steps and the tutorial-versus-homepage screenshot roles; removed an osascript command that treated a process ID as a window ID; described the local-image link check accurately. Evidence: `tools/widget_screenshot.py:42`, `:98`, `:230`, `:436`, `:455`, `:477`, `:560`, `:585`, `:606`, `myogestic/core.py:895`, `website/scripts/sync-static.mjs:1`, `website/scripts/check-links.mjs:59`. Kept the intended three mock sessions pending C3. Inspected all 15 listed existing widget PNGs and the classification screenshot without regenerating them. |

## Code looks wrong: unchanged

1. **C1: regression training and live feature layouts differ.**
   Doc: `docs/tutorials/emg-regression-with-vhi.md:109` and `:148` describe
   training one regressor and using it for live prediction. Code:
   `examples/synthetic/emg_regression.py:125` uses a 1000 ms live EMG
   window, while `:162` and `:192` train on 200 ms windows. The MyoVerse
   transforms are flattened at `:148`; live prediction consumes that
   vector at `:249`. A headless invocation of the real extractor produced
   **288 features for 409 samples and 1536 for 2048 samples** at eight
   channels. This changes both width and the positions of feature blocks.
   Source code was not changed.
2. **C2: excluding every class re-enables every labeled class.**
   Doc: `docs/tutorials/emg-regression-with-vhi.md:138` promises that the
   labeled fallback honors unticked class chips. Code:
   `examples/synthetic/emg_regression.py:213` converts an empty
   `data.classes` to `None`; `examples/synthetic/emg_regression_raulnet.py:300`
   has the same pattern. `SessionManager.ui` can return an empty active set
   after every class is excluded (`myogestic/widgets/training/session_manager.py:176`),
   while `iter_labeled_windows(..., classes=None)` includes all labels
   (`myogestic/session/_windows.py:160`). Keep an empty selection empty or
   refuse training, rather than silently restoring it. Source code was not changed.
3. **C3: the session screenshot helper never loads its mock sessions.**
   Doc: `docs/images/README.md:37` says the capture shows three mock sessions.
   Code: `tools/widget_screenshot.py:267` creates three folders but calls
   only `manager.ui()` at `:281`. With no participant, scanning is manual
   (`myogestic/widgets/training/session_manager.py:132` and `:152`); the
   helper does not click Rescan or populate the state. The committed PNG
   indeed shows zero sessions. Source code was not changed.

## Unverified claims: retained

Counts here are claim groups; repeated instances of the same claim share one ID.

1. **U1: live VHI behavior.** Classification/regression tutorials and the
   examples index describe actual hand poses, settled end positions,
   keyboard gating, control-versus-prediction skeleton selection and
   physical readback. The local clients encode the requests, but the
   external VHI renderer was not launched and its implementation is not
   in `myogestic/`, `examples/` or `docs/playground/`.
2. **U2: completed historical archive migration.**
   `docs/tutorials/emg-regression-with-vhi.md:90` says archives were
   converted once. The migration tool exists at
   `myogestic/tools/migrate_vhi_sessions.py:60`; that cannot establish the
   state of an external recording corpus.
3. **U3: RaulNet precision failure and accelerator behavior.**
   `docs/tutorials/emg-regression-with-vhi.md:189` and
   `docs/tutorials/examples-index.md:258` / `:267` describe hard-coded
   TorchScript fp32 failures and MPS/CUDA training. The example sets
   `precision="32-true"` and automatic acceleration at
   `examples/synthetic/emg_regression_raulnet.py:357`; this audit did not
   run a training campaign across precisions or accelerators.
4. **U4: Pong measurements and subject effects.**
   `docs/tutorials/examples-index.md:355`–`:376` retain the 30% dead region,
   14x improvement, eleven-level staircase comparison, lack of a linear
   model gain, historical louder-means-Down fit and human-feedback
   explanation. The implementation supports the protocols/decoder but
   does not by itself prove those numerical or human-subject findings.
5. **U5: VHI skeleton geometry and rotation bound.**
   `docs/reference/glossary.md:53` retains bone-parent relationships,
   the ±179° versus ±180° Euler behavior and renderer-side clipping. The
   channel naming table exists in `myogestic/vhi/pose.py:63`, but
   `split_pose` only checks width and relabels (`:111`); it does not prove
   the external renderer's geometry or clipping.
6. **U6: uncommitted manufacturer-PDF verification.**
   `docs/reference/otb/README.md:19` names six uncommitted protocol/manual
   documents and says verification was performed against them. The
   committed MATLAB files and Python implementation agree with the
   listed numerical facts, but the PDFs and that historical verification
   were not available in the assigned source material.
7. **U7: LSL restart guarantees.**
   `docs/tutorials/your-first-remote-target.md:748`–`:766` describes native
   recovery under stable source IDs and silent non-recovery after
   renaming. The stable source-ID construction is verified at
   `myogestic/remote/interfaces.py:154`; this audit did not exercise
   source-ID-changing restart/recovery on the network.
8. **U8: historical green-suite sign bug.**
   `docs/tutorials/your-first-remote-target.md:855` says the repository
   shipped that exact sign bug with its suite green. Current code cannot
   establish that historical assertion. The hardware sign check itself
   remains explicitly a manual checkpoint.
9. **U9: shutdown timing under normal LSL conditions.**
   `docs/tutorials/your-first-remote-target.md:595` describes two seconds
   as comfortably longer than a reader pass. The bounded joins and caveat
   are present, but native inlet/open/resolve timing is not bounded by
   that Python code; no timing guarantee was established here.

## Stale or misleading screenshots: not regenerated

1. **S1: `docs/images/gui-overview.png`.** Referenced by
   `docs/tutorials/emg-classification.md:25`. It shows the stacked logo,
   persistent left-column panels and older viewer controls. The current
   layout uses AppHeader/StepBar, an active step card, persistent
   simulator, participant takes and StatusBar
   (`examples/synthetic/emg_classification.py:220`, `:250`, `:619`).
   The caption now explicitly identifies the earlier layout.
2. **S2: `docs/images/widgets/session_manager.png`.** Listed by
   `docs/images/README.md:37` as three mock sessions; the image is empty
   and reads zero selected/zero total. This is a misleading capture of
   the helper's current idle state, rather than a different old widget
   design. Fix C3 before recapturing it.

The other listed widget PNGs were visually inspected against their
widget implementations and capture configurations; no additional
specific UI mismatch was established.

## Commands and validation

- Ran the documented environment commands `uv sync --extra grpc`,
  `uv sync --extra examples`, and
  `uv sync --extra examples --extra grpc`; restored dev/grpc/docs extras
  for validation afterward.
- Ran `uv run python examples/synthetic/my_device.py`,
  `uv run python examples/synthetic/servo_hand.py`, and
  `uv run --extra grpc python tools/inspect_control.py`: all exited 0;
  the inspector reported no target running.
- Ran these 15 long-running commands under a five-second timeout and
  interrupted them after startup: the exact documented commands for
  `control_map_studio.py` (grpc/keyboard),
  `examples/panels/control_map_editor.py`, `electrode_grids.py`,
  `electrode_overview.py`, `high_channel_viewer.py`, `my_session_app.py`,
  `emg_classification.py` (examples), `emg_regression.py` (examples/grpc),
  `emg_regression_raulnet.py` (examples/grpc),
  `emg_32ch_multi_model.py` (examples/grpc), `vhi_control_hand.py` (grpc),
  `start_here/myocontrol.py` (examples/grpc), `start_here/pong.py`
  (examples/grpc), `start_here/force_ramps.py`, and `reference_target.py`
  (grpc). GUI commands reached `App.run`/the GUI loop; these are startup
  checks, not end-to-end hardware or training validation. Evidence:
  `/tmp/docs-audit-c-example-commands.log`.
- Extracted the literal remote-target files to a temporary directory.
  Ran the stage-1 target/probe (exit 0), Antique/probe (expected exit 1
  with the documented vocabulary error), the complete target, valid-map
  inspector (exit 0), typo-map inspector (expected exit 1 with the
  documented near-miss), and finished `drive.py` (exit 0 with
  True/True/False). Used `uv run --project <checkout> --extra grpc python`
  so relative tutorial filenames resolve inside that temporary
  directory. Evidence: `/tmp/docs-audit-c-rig-commands.log`.
- Ran `wide.py` against the full target: the target printed the
  nine-channel-width refusal. Ran `my_target.py --rest-after 1.0` with
  a producer killed by SIGKILL: after receiving +1/-1, both axes returned
  to rest. The first 2.5 s startup probe was inconclusive because it
  observed no nonzero samples before killing the producer; the successful
  probe extended only the copied producer loop to 20 s, allowed 7 s for
  LSL discovery, killed it, and observed rest two seconds later. Evidence:
  `/tmp/docs-audit-c-rig-timeout.log` and
  `/tmp/docs-audit-c-rig-deadman.log`.
- Did not clone a second checkout, install/update VHI, execute screenshot
  or image-compression commands, or run the physical sign checkpoint.
  The audit already has a checkout, excludes external-install changes,
  explicitly forbids screenshot regeneration and has no physical rig.
- Required foreground gates: final results recorded below after the
  last edits. Website checks use Node 22, the version declared by the
  site, through `npx --package=node@22`; the host's default Node is 26.
  Static assets are prepared with the same
  `node scripts/sync-static.mjs` step as CI. An initial clean-worktree
  website attempt before that prerequisite failed on missing copied
  assets; the prepared run passed. No site code was changed to bypass it.

## Final gates

- `uv run --extra dev pytest tests/test_docs.py -q`: **344 passed**.
- `cd website && npm run ci`, under Node **22.23.4** with
  `CI=1 PLAYWRIGHT_PORT=4393`: **passed**, exit 0. The dedicated port and
  CI mode prevent reuse of another worker's preview server.
- Website details: **61 legacy URLs**, **5647 internal links across 63
  HTML pages**, **808/808 legacy API symbols** and **1325/1325 generated
  API references** all passed; **19 Vitest files / 80 tests passed**;
  **41 Playwright tests passed, 3 skipped**. Skips: native WebGL context
  loss in this browser environment, plus two playground workflow tests
  because no local playground wheel/manifest was built. No skip was
  introduced by this audit.
- `git diff --check`: passed. Final website log:
  `/tmp/docs-audit-c-ci-final.log`.

Research board was not edited, as explicitly required by this dispatch;
the coordinator owns any consolidated project reporting.
