# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The control manifest carries a `target_version` — the serving build's own release
  version — and `InterfaceSpec` grew `min_target_version`, enforced at every
  capabilities fetch. This is the runtime half of the version gate: the install-time
  marker check never sees a build launched by double-click, unpacked by hand, or run
  from source, but the manifest is the one channel every launch path answers on. A
  build reporting an older version is refused on the same path as a vocabulary
  mismatch; one reporting nothing (every build before VHI v2.1.0) is warned about
  once and driven anyway. Motivated by a hand that froze mid-session: VHI v1.0.0
  speaks the current vocabulary, so every existing gate passed, but its `SetMovement`
  falls behind under bursty gesture edges and drops them — a frozen hand with a
  perfectly healthy protocol.
- `tools/muovi_probe_sim.py`, a fake Muovi / Muovi+ probe that dials into
  `MuoviSource` at the real device cadence, so any unmodified example runs without
  hardware. `--self-check` verifies its own pacing; `--rate-scale` simulates crystal
  drift; a `BACKPRESSURE` line prints when the app stops draining the socket.

## [2.6.2] - 2026-08-10

### Added

- `SessantaquattroSource` streams a Sessantaquattro or Sessantaquattro+ over TCP, and the
  `DevicePicker` offers it alongside the Muovi and the Quattrocento. The device dials in, so
  MyoGestic listens on 45454 and the amplifier connects to us — the opposite of the
  Quattrocento, where we are the client.

  Two behaviours are measured against a Sessantaquattro+ at 72 channels rather than read off
  the protocol table. Start is a single config word with `GO=1`: sending `GO=0` first, as a
  preamble to stop anything in flight, makes the device hang up and deliver nothing (`GO=1`
  alone gives 233.8 kB/s, `GO=0` then `GO=1` gives 0 bytes, with or without a gap). And the
  accessory block width is probed from the live stream before `StreamInfo` is returned, not
  derived from the detection mode — declaring the widest candidate up front fails as
  `shape=(208, 68); expected (_, 72)` on a device whose block is narrower.

### Fixed

- `StreamPanel`'s reconnect runs off the UI thread. Accepting a connection from a device that
  dials in blocks for the source's whole accept timeout, which on the UI thread is a dead
  window for that long with nothing to say the click registered.

## [2.6.1] - 2026-08-10

### Added

- `Stream(notch_hz=)` notches mains out of the acquired signal, so the model's windows and
  the recording carry the same conditioning. The signal viewer's Notch changed only what
  was drawn; mains sat in every feature vector with a control on screen that looked like it
  had removed it. Conditioning happens at the one point in the acquire loop where the ring
  buffer and the session take the same array, so there is no second code path to drift.
  Measured on a synthetic 50 Hz hum, a live window goes from 24.6% of its power at 50 Hz to
  0.0037%, while `notch_hz=60` leaves it alone.

  It has to be a streaming filter over chunks. Predict windows are the trailing
  `window_ms` taken many times a second and overlap almost entirely; filtering each on its
  own leaves 24x more mains (13.1% of window power against 0.54%) and moves window RMS by
  16%.
- `myogestic.conditioning` holds `apply_mains_notch` and `NotchFilter`, moved out of
  `widgets/signals/transforms.py` because core cannot import from `widgets`. The old import
  path still works — `transforms` re-exports both. Their documented equality, that any
  chunking of `NotchFilter.step` matches `apply_mains_notch` over the concatenation, is
  what lets an offline reader and the live path produce identical samples.
- Recordings say how they were conditioned, in `extras["conditioning"]`. A filtered take
  holds filtered samples and the raw is not recoverable, so nothing in the arrays reveals
  it; `examples/start_here/myocontrol.py` gains a SIGNAL panel and refuses to train on a
  session whose notch disagrees with the switch. Fitting on unfiltered takes and predicting
  through a notch changes the model's input distribution with every read-out still healthy.

### Fixed

- A fault in stream conditioning surfaces in `status`/`last_error` and leaves the acquire
  loop alive. Raising on that thread killed it outright while every read-out still said
  "connected" — the stream simply stopped delivering, with nothing to point at.

### Changed

- Comment density cut across `examples/`, to the level of `force_ramps.py`: the start_here
  protocols and every file under `synthetic/` and `panels/`. Comments and docstrings only,
  verified by comparing docstring-stripped ASTs against the previous commit for each file.

## [2.6.0] - 2026-08-09

### Added

- `examples/start_here/myocontrol.py` is a second complete protocol: pick an amplifier from
  a dropdown, record cued Rest/Fist trials, train a classifier or a regressor, and drive the
  Virtual Hand from the prediction. The mode is bound into the model `train` returns rather
  than read live, so moving the switch under a loaded model cannot send a class index down
  the regression branch. It runs on the shipped `examples/controls/hand.toml` unmodified.
- `PongTask` renders Pong from one signed command in `[-1, +1]`, and
  `examples/start_here/pong.py` is the protocol around it: a recorded training block, one
  model, and a paddle that only returns the ball if the contraction is graded. It is
  the first shipped example whose command is signed — Down is a real `-1`, not the absence
  of Up — so the negative half a one-way fit never sees is exercised end to end. The
  Virtual Hand mirrors the paddle when the Hand tab is bound and is never required. The
  synthetic source gained a `direction` knob that splits its activation across an
  agonist/antagonist channel pair, which makes Down and Up separable with no hardware;
  the default of `0.0` is what the source did before.
- `directional_decoder` is the model that game needed, and `pong.py` now trains it by
  default (its mode switch reads Proportional / Regression / Classification, Proportional
  first). **Amplitude cannot carry direction.** On three 8-channel bracelet recordings,
  overall loudness barely tells Down from Up — d' = 0.52 — while the *amplitude-normalised*
  pattern separates the very same windows cleanly, per-channel d' up to 10.9. One regressor
  over raw features therefore learns whichever cue was louder in the training set: the
  CatBoost regressor `pong.py` shipped with learned "louder = Down", because Down simply
  happened to be recorded harder, which made it **non-monotonic in effort** — scaling every
  channel 1.0 → 1.3 → 1.6 moved its Up prediction 1.000 → 0.882 → 0.723, so contracting
  harder drove the paddle the wrong way, and it was dead below ~30% effort. The recipe
  estimates the two cues apart and multiplies them: `activation` (the row total, rescaled so
  rest reads 0 and a typical contraction reads 1) times `direction` (the unit-sum row
  projected onto the Fisher axis from the mean Down shape to the mean Up shape). A global
  electrode gain cancels out of the shape exactly *as long as every ticked feature answers
  that gain the same way* — RMS, MAV and WL all scale by `g`, VAR by `g²`, ZC not at all —
  so within one of those groups it cannot touch the sign and can only raise the magnitude.
  Across two of them it can, which is why the input contract names the condition and
  `pong.py` refuses a mixed set in Proportional mode instead of training on it. Rest needs
  no dead-zone hack because `activation` is 0 there. It has no dependencies, its only knob
  is `shrinkage` (a conditioning knob rather than a correctness requirement, and now
  range-checked), and `fit` refuses outright — naming the missing block — if the training
  set has no rest windows or only one direction, or if `X` carries a NaN, which would
  otherwise pass every `<= 0` guard and make *every* later prediction NaN. Features must be
  non-negative and grow with contraction; signed or mean-centred features break the split.
  The effort span is fitted **per window** — `median((total - rest_) / abs(y))` over the
  windows whose target reaches `abs(y) >= 0.5` — rather than read off the non-rest median,
  which treats every non-rest window as a full contraction. On a `Pursuit` block the median
  non-rest window sits at `abs(y) = 0.358`, so that rule fitted a span of 1.76 against a
  true 4.23, `activation` saturated, and the command pegged at about 40 % effort; the
  transfer curve over nine held levels goes from **MAE 0.179 and non-monotone** to **0.084
  and strictly monotone** on the identical recording. It costs a cued block nothing, and
  exactly nothing: every non-rest window there has `abs(y) == 1`, so the threshold selects
  the same windows, dividing by 1 is a no-op, and a median is translation-equivariant —
  both rules return the same float. Below three qualifying windows `fit` raises, naming the
  count and the largest `abs(y)` in the block, rather than quietly fitting a span on two.
- **Follow the cursor** is a second training block for `pong.py`, and the reason for it is
  measured rather than argued. Three cued classes are three distinct target values, so a
  tree ensemble fitted on them is a three-class model whatever it is called — its output is
  an average of training targets, so it cannot emit a level the block never asked for. On
  real recordings the CatBoost regressor was dead below ~30 % effort and non-monotonic in
  it; a simulation of the same protocol emits **-0.34** at a true **+0.50**. Training on
  densely covered levels instead cut CatBoost's intermediate-effort MAE **0.402 → 0.029**.
  `myogestic.tracking.Pursuit` is the block that covers them: rest at exactly `0`, then a
  smooth aperiodic wander over signed `[-1, +1]`, deterministic arithmetic on the hop index
  so two sessions record the identical path and a test can assert an exact value. It is
  drawn as a ghost paddle by the new `PongTask.ui(target=…)` and recorded beside the EMG by
  `TargetSource`, which now takes any `Trajectory` — the structural protocol `Trapezoid` and
  `Pursuit` both satisfy — and codes the stretches with no block running `idle` rather than
  `rest`, so the wait while the operator sets a block up cannot merge into that block's rest
  phase. `myogestic.session.iter_target_windows` pairs each EMG window with the recorded
  cursor value at the window's **end**, which is the causal choice (the centre would train
  the model to predict the past by half a window), aligns by timestamp rather than index,
  and drops a window whose end falls outside the target's own span instead of inventing
  ground truth for it. `pong.py` routes each selected session by whether it carries the
  target stream, so cursor and cued recordings train together in one signed column.
  **Be precise about what this buys.** The active ingredient is the *number of distinct
  target levels*, not pursuit and not continuity: a cued staircase of eleven holds **beat**
  the pursuit block, 0.0367 against 0.0548 MAE, on 4 of 4 seed pairs, and a linear model
  gains nothing at all, because least squares already draws a straight line through three
  levels. The win is large specifically for the tree ensembles shipped here. The argument
  for a followed cursor over a staircase is human rather than statistical: told "go to 0.6"
  a subject has no idea what 0.6 feels like, while a cursor gives continuous visual error
  feedback, so the intermediate levels are reachable at all.
- `PongTask(control="position")` maps the command straight onto the paddle's height instead
  of integrating it as a velocity. Velocity remains the default and is what turns a coarse
  decoder into a complete controller — three outputs become up / hold / down, which reach
  every height — but it accumulates a resting bias and needs a dead zone. Position cannot
  drift, needs no dead zone, and puts the paddle exactly where the model's output says,
  which makes it the honest mode to debug against once the command is genuinely continuous.
  `pong.py` exposes both on its Model tab.
- `PongTask(opponent=…)` puts a second paddle at the far wall instead of the plain wall to
  rally against, which gives the drill a score the subject is playing for rather than an
  open-ended rally. The factor is that paddle's top tracking speed as a multiple of
  `ball_speed` — ~0.6 is a fair rally, 1.0 and above is hard — and it is the whole
  difficulty. `pong.py` exposes Easy / Fair / Hard on its Model tab and ships playing Fair;
  changing it rebuilds the court, since a score against a slower paddle should not carry
  over. `opponent=None` remains the default and is the wall exactly as before.

### Fixed

- `PongTask` now advances the opponent's paddle only as far as the ball's arrival instant,
  not to the end of the frame, before deciding whether it reached. A hitch frame — a GC
  pause, a model fit, an LSL reconnect — used to buy the far paddle reach its speed cap does
  not have, so the frame rate was a difficulty knob alongside `opponent`: at shipped Hard
  settings the points it conceded moved 23% between 144 Hz and 2.5 Hz. A frame that returns
  two balls also scores two hits now instead of one, and a non-finite `ball_speed` is
  refused at construction rather than raising from inside `_bounce` one frame later.
- `open_session_store` restores `Session.name`. It is written to `meta.json` for exactly
  this reason, but the reader rebuilds the Session with `__new__`, so reading `.name` off a
  reopened session raised `AttributeError` rather than returning what was recorded.
- `DevicePicker`'s scan worker writes its results to the stream it was started for. With
  `selectable=True`, switching the panel mid-scan delivered the outlet list to whichever
  stream was showing when `discover()` returned, and left the scanned one reading "nothing
  found" permanently — its auto-rescan guard was already satisfied. `_connect` already held
  its stream's state for the same reason; `_start_scan` now does too.
- `OneEuroFilter` no longer latches on a non-finite sample. It is recursive, so one NaN from
  a diverged model used to make every later output NaN for the rest of the session; the last
  finite value is held for those components instead, and a NaN on the first call does not
  seed the filter at all.
- `PongTask` **clamps** a long frame instead of skipping it. The old rule zeroed `dt` past
  half a second, which failed on both sides: a sustained frame time just *over* the bar
  froze the game outright — ball, paddle and integrator, with the header still showing a
  rally and no way back — while a frame just *under* it was integrated whole and moved the
  paddle 0.70 court `y`, 44 % of its entire travel, in one frame, which is precisely what
  the rule existed to prevent. One frame is now worth at most 0.1 s: below 10 fps the game
  runs in slow motion rather than teleporting or freezing.
- `PongTask` sweeps the **subject's** paddle to each crossing instant, as it already did the
  opponent's. `_drive` ran before `_step`, so a ball was adjudicated against the position
  the paddle reached by the *end* of the frame — one it was never at when the ball arrived
  — which made the frame rate a difficulty knob in velocity control: 1.3 % of crossings
  scored the wrong way at 60 Hz, 6.0 % at 10 Hz, in both directions.
- `PongTask(control="position")` and the pursuit ghost now **scale** the command onto the
  paddle's travel instead of clipping it. Clipping made every command from 0.82 up one
  single place, so the top and bottom 18 % of the range were dead — and worse, the ghost
  saturated at 0.82 while the session recorded the raw `±1`, so a subject tracking it
  perfectly at full deflection was labelled up to 0.18 control units away from the
  reference they were actually shown. That is 7.4 % of a default `Pursuit()` block, all of
  it at the extremes, which is where a proportional decoder's gain is set.
- Pressing **Serve** recentres the subject's paddle, not just the opponent's, and
  `_DEAD_ZONE` no longer claims to stop drift. It stops a *constant* resting bias exactly
  and slows a noisy one; it cannot stop a noisy one, because rectifying bias-plus-noise
  clips away the half of the noise that would have cancelled the bias. Measured at 60 Hz
  with a bias of 0.05: noiseless the paddle never moves, at a command sd of 0.05 it is flat
  against the wall after 122 s and at 0.10 after 30 s. Only a leak bounds a drifting
  integrator and `_drive` gives the reason there is none, so what is left is the court
  clamp, the subject, and a Serve that starts the next rally from the centre.
- `PongTask(ball_speed=...)` refuses a non-positive speed. `max(ball_speed, 0.0)` absorbed a
  sign typo into a zero-velocity ball parked at centre court — a permanently dead game with
  the header still green — where `control`, `opponent` and a non-finite `ball_speed` are all
  refused out loud.
- `directional_decoder.fit` refuses a target outside `[-1, +1]`. Its docstring always said
  the target was signed control units, and nothing checked: every other guard in `fit` is a
  `<= 0` test, and none of them notices a wrong *scale*. `Trapezoid` records percent of MVC
  through the same `TargetSource`, under the same stream name, with the identical channel
  names, into the same `sessions/` folder, and a `StreamInfo` carries no unit — so one such
  session ticked beside a cursor block collapsed `span_` from 4.17 to 0.046 and turned a
  graded transfer curve into a hard three-step staircase, with every guard passing.
- `examples/start_here/pong.py` routes a session by what its target stream *holds*, not by
  whether it exists. `TargetSource` keeps emitting baseline with phase `idle` after a block
  ends and the stream stays attached, so every cued take recorded after a pursuit block
  carries a `target` stream — which `split_sessions_by_stream` calls a pursuit session, and
  `iter_target_windows` then correctly yields nothing from, leaving the label track unread
  and the session silently dropped. The target path is now the preferred reading and the
  label track the fallback: a session the target path cannot use (all `idle`, or a stream
  recorded empty by a take stopped inside the source's 100 ms chunk) is read from its labels
  instead of being dropped or taking the whole selection down with it. `train` also
  range-checks each session and refuses a force-ramp recording **by name**, and its
  per-session breakdown goes to `ctx.log` — which `LogPanel` renders — rather than to a
  `print` nothing in `Pipeline` captures.

## [2.5.5] - 2026-08-03

### Fixed

- `VhiMovementPanel.ui(auto_refresh=False)` can now keep cached VHI controls visible
  without scheduling periodic state RPCs. Latency-sensitive prediction views can pause
  background gRPC polling while preserving explicit Refresh and control delivery.

## [2.5.4] - 2026-08-03

### Fixed

- The synthetic EMG generator now paces chunks against an absolute monotonic deadline.
  Small operating-system sleep overshoots are corrected on the next tick instead of
  becoming permanent delivery jitter; long stalls rebase without bursty catch-up output.

## [2.5.3] - 2026-08-03

### Fixed

- Live streams no longer unwrap the entire acquisition ring on every source chunk or
  prediction tick. Acquisition appends remain constant-time, while prediction and signal
  viewers copy only their requested recent tail; long buffers therefore no longer make the
  plot progressively stutter or starve high-rate sources as they fill.

## [2.5.2] - 2026-08-03

### Added

- `ControlLinkConnector` provides rate-limited, single-flight background retries for a
  deferred `ControlLink`, so UI loops can reconnect application-launched targets without
  blocking either rendering or prediction.

### Fixed

- `myogestic-install-vhi --tag latest` now records the resolved release tag in
  `vhi-version.txt` instead of the literal moving selector `latest`. The launch-time
  compatibility gate can therefore identify an old installed VHI reliably.
- A reachable server that does not implement `GetControlManifest` is now reported as an
  incompatible pre-v2 target with an upgrade command, rather than retried forever as if it
  were unreachable.

## [2.5.1] - 2026-08-03

### Fixed

- `Session.save_meta` now writes `pose_convention` into `meta.json`. Without it, a session
  recorded by 2.5.0 was indistinguishable from a pre-2.5 one — `migrate_vhi_sessions` reads
  an absent key as legacy — so running the migration over a sessions folder negated the
  correct recordings into the old convention. The damage was silent and looked exactly like
  a hand driven backwards. Sessions written by 2.5.0 carry no stamp and still need one added
  by hand (`"pose_convention": "standard"`) or a re-pack under this version; do **not** run
  the migration on them.
- `myogestic.tools.migrate_vhi_sessions` imports `POSE_CONVENTION` from
  `myogestic.session` instead of defining its own copy, so a migrated session and a freshly
  recorded one cannot drift into disagreeing about what convention they are in.

## [2.5.0] - 2026-08-02

MyoGestic 2.5 and **Virtual Hand Interface 2.0 are one release** and must be upgraded
together: the pair negotiates a `vocabulary_version`, MyoGestic requires 2, and only VHI 2.0
serves it. A mismatched pair refuses at bind rather than half-driving. Install the matching
VHI with `myogestic-install-vhi`.


### Added

- **One target drives the whole map.** VHI used to render its two hands on two wide
  streams, and an application had to say which one it drove *before* it had read the map:
  `RemoteTarget(vhi_outlet, client=…)` bound whichever hand the outlet was built for, so a
  map naming the operator's hand rendered nowhere and the editor hid those addresses to
  stop anyone writing one. Now every control has a stream of its own, named for its own
  address, and one `RemoteTarget(client=…, interface=vhi)` owns one outlet per address the
  map names — both hands included. An application no longer chooses a hand, there is
  nothing left for it to count, and a user editing a map sees every address their
  target offers.

- **A version gate on the target.** `ControlManifest.vocabulary_version` is load-bearing
  rather than logged: MyoGestic declares the oldest vocabulary it can drive and **refuses**
  anything older, by name, at bind. These are separately installed applications, so
  shipping the two together does not make any given pair a matching pair — and the
  mismatch it catches is otherwise silent, because a target waiting for a stream nobody
  publishes any more reports no error at all and the hand simply never moves.

- **A control standard — `myogestic.controls`.** A control space is a *mapping*, written in
  a file: your name for a model output on the left, an address the target declares on the
  right (`my_index = "vhi.prediction.index"`). The left side is yours and arbitrary. The
  right side belongs to the target, which also declares what the control **is** — number or
  held state, its range, its states — so MyoGestic hard-codes no vocabulary and a target
  that grows a control needs no change here. Continuous controls are normalized: `+1` is
  the direction the control denotes, rest is `0`, signed when the target says so. Discrete
  controls are a separate kind — a held state delivered on change, never a number.
  `load_control_map` takes a plain mapping, so the library still reads no config files;
  `resolve` needs a live target, because the target is what declares the semantics.
- **A playground and a control-map editor.** `examples/synthetic/control_map_studio.py` is
  the shortest path from a mapping file to a hand that moves: a slider per name in
  `examples/controls/playground.toml`, straight to VHI's predicted hand, with no model
  and no EMG. Beside it, `myogestic.widgets.ControlMapEditor` — a reusable panel that
  asks the target what it exports and lets a control be *picked* rather than typed,
  with weights, fan-out, and `threshold_fraction` in plain words. It refuses a map the
  target would reject before it can be saved, including two aliases that would land on
  one control. The TOML stays the source of truth: the
  editor reads and writes that file through `dump_control_map` and keeps no state of its
  own.
- **`dump_control_map`** — render a `ControlMap` back to TOML that `load_control_map`
  reads. Anything that edits a control map writes through it rather than inventing its
  own formatting.
- **Grouped and weighted fan-out.** One output may reach several controls —
  `fist = ["vhi.prediction.index", "vhi.prediction.middle"]` — with an optional per-target
  `weight` applied *before* that target's own range conversion, so a gain scales a value
  but cannot push one past what the target accepts. Negative weights are permitted only on
  a target that declares signed motion.
- **Classification reaches a target the same way regression does.** A classifier produces a
  *probability*, not a position, so `threshold_fraction` on a continuous binding declares the
  cutoff: below it the value becomes `0.0`, at or above it `1.0`, gated before anything else
  sees it — before the weights, before the wire, before the recording. From there it is an
  ordinary control value: `0` to every listed control when inactive, `1 × weight` when
  active. Drop the `threshold_fraction` and the identical mapping serves a regressor. The
  gate exists because a continuous address is a *position*: streaming a raw `0.73` into one
  says the finger is 73% curled, which is not what a 73%-confident classifier meant. Map onto
  a target-declared **discrete** address instead when the thing genuinely is a state rather
  than an amount.

  The name says what it is compared against — a probability fraction, validated to `[0, 1]` —
  and is deliberately not `threshold`, because a *target* declares its own
  (`Capability.activation_threshold`: what its states cost, e.g. a prosthesis that takes a
  second to close wants a higher bar than a cursor click). The two answer different questions
  and must not be confused for one another.
- **`ControlBus` owns the one ordering that must not be re-derived per application:**
  substitute rest → clip → dead zone → smooth → substitute rest → clip again → deliver.
  Rest substitution comes first because `min(hi, max(lo, nan))` is `lo`, so a NaN
  prediction would otherwise arrive as full-scale deflection; the second clip exists
  because a smoother undershoots on a falling edge. `push` never raises — it runs on the
  predict thread, where an exception would bury the log that explains it.
- **Three smoothing layers, kept distinct.** Continuous smoothing (`ControlBus(smoothing=…)`,
  authoritative, before any target sees a frame), discrete debounce and hysteresis
  (declared on the DOF), and optional target blending
  (`control_client().set_presentation(…)`, appearance only). A discrete control is
  **never** numerically low-pass filtered — averaging "rest" and "fist" interpolates
  through a state nobody selected — and that is enforced structurally: the filter only
  ever receives the continuous vector.
- **`myogestic.remote.RemoteTarget` — drives control DOFs on a separate application.** It *asks* which
  contract the hand speaks rather than assuming, and refuses a configuration it cannot
  fully drive rather than driving part of it — a partly-understood negotiation would
  leave some DOFs believed driven and others quietly dropped, and a dropped joint is
  indistinguishable from a joint that is working and holding still. Binding is deferred
  rather than decided when the target is silent, since an application that launches VHI
  from its own UI necessarily binds before VHI exists; a target that answers and does
  not speak the contract raises.
- **`InterfaceSpec.control_client()` / `recording_client()`** for VHI's v2 control service
  and its recording aid. Exported lazily, so a plain install without the `[grpc]` extra
  still uses `stream_outlet()` / `launcher()` without importing grpc.
- **`Outlet.flush()`** — send the latest pushed value now instead of on the next tick. The
  send loop is paced, so a neutral frame pushed at teardown was never sent at all: the
  thread was mid-sleep and `stop` ended the loop before it woke. Measured against a real
  Virtual Hand, that was the difference between a hand releasing and a hand frozen in a
  fist.
- **Recordings describe the space they were made under.** `ctx.control_space` is persisted
  into `meta.json` (schema 3). Channel names alone do not say what a number meant: `-1` is
  a full excursion for a signed DOF and out of range for a one-way one, and nothing
  recoverable distinguishes "declared one-way" from "signed, but this operator never went
  negative".
- **Model provenance.** `save_pickle(..., controls=…)` writes a `<path>.controls.json`
  sidecar and `load_pickle(..., controls=…)` refuses a mismatch. A model is only meaningful
  in the space it was fitted for; loading one trained on a one-way `[0, 1]` DOF against a
  signed configuration produces motion in a direction it never learned.
- **`myogestic.vhi.pose`** — the layout of VHI's *recorded* pose stream: nine control-standard
  values in a fixed order, with `split_pose` to name them. It replaces `myogestic.vhi.legacy`,
  which is removed along with its `decode_pose`: both ends speak the control standard now, so
  there is no second convention and nothing left to decode.

- **A keyboard target — `myogestic.keyboard`.** Press a key while a control is active.
  `keyboard.hold.letter.w` is held for as long as the control is above its threshold;
  `keyboard.tap.edit.space` is one press per crossing however long you hold it. Around 220
  addresses, every key in both modes.

  **Nothing in the control standard changed for this.** A key is a two-state discrete
  control, so activating above `0.5` is `Capability.activation_threshold` selecting the
  non-rest state, overriding it per control is `threshold_fraction`, ignoring a chattering
  signal is `debounce_s`, and "it just changed" is the discrete edge `ControlBus` already
  delivers. The address rule already reserved the `keyboard.` namespace. That the second
  target needed no new mechanism is the strongest evidence the standard is the right shape.

  It starts **disarmed** and sends nothing until armed, because a resolved map types into
  whatever window has focus. It disarms on stop, on a backend failure, and on exit, letting
  go of everything it holds — a held key outlives the process that set it. Needs the
  `keyboard` extra (`pynput`, *not* the PyPI package called `keyboard`, which wants root and
  is unmaintained) and, on macOS, Accessibility permission, without which `pynput` reports
  success and does nothing.
- **The picker is a tree.** `ControlMapEditor` splits addresses on their dots and nests
  them, so `vhi` and `keyboard` are two roots and each `.` is another level. Addresses are
  dotted by contract and the first segment names the target, so this needed no
  target-specific code — the same function organises 19 VHI controls and 214 keys. Typing in
  the search box prunes the tree and opens what is left, rather than making you hunt.
- **The editor takes several manifests.** `ControlMapEditor(..., clients=[vhi, keys])` merges
  them, because one file can name controls on more than one target. `client=` still works.
- **liblsl is quiet by default.** At its own default level, building one outlet logs a line
  per network interface plus a multicast bind warning per interface it cannot use — and
  MyoGestic publishes one outlet per control it drives, so a six-control map emitted several
  hundred lines before the application logged anything. A config shipped in the package sets
  the console level to errors only, pointed at through `LSLAPICFG`. It backs off for all three
  places liblsl looks — `$LSLAPICFG`, `./lsl_api.cfg`, `~/lsl_api.cfg` — so a config of your
  own, including one that tunes discovery or disables IPv6, is never shadowed.
- **`python -m myogestic.tools.migrate_vhi_sessions`** — rewrites sessions recorded under the
  old control-space format into the current one, so a corpus recorded before this release stays
  trainable. (A module, not a console script: `myogestic-install-vhi` is the only entry point
  this release registers.)

### Removed (breaking)

- **`UDPOutput` and `SerialOutput` are gone.** They existed to drive a device without a
  control map, which is the road this release closes. Neither was constructed anywhere in the
  tree and neither had a test.

  Anything that **moves** is a [`Target`][myogestic.controls.Target]: three methods, any
  transport, and with it the map's declared ranges, clipping, dead zone, debounce and the
  neutral frame delivered before teardown. See `examples/synthetic/servo_hand.py`.

  `Outlet` (renamed from `Output`, below) and `LSLOutlet` stay, as the paced sender a target
  writes *through*. To keep a
  deleted class, copy it out of git history; each was under 60 lines.

- **`InterfaceSpec` no longer names a stream.** `output_stream_name`,
  `control_pose_stream_name`, `n_control_pose_channels` and `control_pose_hz` are gone,
  and `outlet()` / `control_outlet()` with them; one `stream_outlet(name, n_channels=…)`
  replaces both, and the *caller* supplies the name. Which streams a target publishes,
  and which controls each carries, is in the manifest it answers with — so MyoGestic
  writes no stream name down anywhere, and a target that renames a stream, or ships a third,
  needs no configuration at all. `RemoteTarget(…, stream=…)` and `stream_name=` are gone with
  them: the constructor is now `RemoteTarget(client=…, interface=…)` and it builds its own
  outlets, one per address, after negotiation says what those addresses are.
  `ControlMapEditor(…, stream=…)` is gone outright — the picker offers every address every
  manifest reports, because hiding one hand made wanting it impossible to express.

- **The VHI 1.x bridge is gone. MyoGestic now requires VHI 2.0 or newer.** The v1 gRPC
  client, the vendored v1 `.proto` and its stubs, and every fallback branch in
  `RemoteTarget` — the legacy pose path, the address-to-channel table it routed through, and
  v1 `SetMovement` for held states. (`InterfaceSpec.control_client()` stays; it returns the
  v2 client.)

  The substantive part is what replaces the fallback: **a refusal**. `bind` used to warn
  and encode a legacy pose when a handshake came back partial, disagreeing, or without a
  stated encoding; each of those now raises. The alternative to a fallback is not a guess.
  A *silent* target still defers, because an application that launches VHI from its own
  button binds before VHI exists — but one that answers and does not speak v2 is a settled
  fact and raises with the upgrade command.

  `install_vhi` resolves what `latest` actually points at before downloading and refuses
  anything below 2.0, and `launcher()` refuses to start a pre-2.0 install it finds on
  disk. Both fail where the cause is, rather than letting an unusable binary install
  cleanly and surface at bind time. Neither refuses without a version marker, since a
  source-mode checkout has none.

  `myogestic.vhi.pose` is **not** part of the bridge and stays: it names the nine slots of
  VHI's *recorded* pose stream, so a model can be trained against a corpus captured before
  this release.

### Changed (breaking)

- **`myogestic.outputs.Output` is now `Outlet`**, and `outputs/base.py` is `outputs/outlet.py`.
  The base class did not share a name stem with its own subclass — `Output` → `LSLOutlet` —
  which made the send side read as more concepts than it has, now that this release also adds
  `Target`.

  There are now two, and the difference is real: a **`Target`** takes *named* values, can
  refuse a configuration at `bind`, declares `capabilities()`, and gets range, clamping, dead
  zone and rest-on-teardown from the control map. An **`Outlet`** takes an array, paces one
  wire, and has none of that. `RemoteTarget` owning one `LSLOutlet` per address it drives is
  the relationship in one line.

  Update `class MyThing(Output)` to `class MyThing(Outlet)` and import from
  `myogestic.outputs` rather than `myogestic.outputs.base`. No alias is shipped: two names for
  one meaning is the problem being fixed.

- **`myogestic.remote` — the generic half moved out from under the hand's name.** The
  target, the two gRPC clients, `InterfaceSpec` and the wire contract were all
  in `myogestic.vhi`, and none of them is about a hand: they read a manifest, publish one
  stream per address and forward discrete edges. Someone integrating a robot arm imported
  `myogestic.vhi.VhiTarget` and reasonably concluded they had taken a wrong turn.

  | was | is |
  |---|---|
  | `myogestic.vhi.RemoteTarget` | `myogestic.remote.RemoteTarget` |
  | `myogestic.vhi.RemoteClient` | `myogestic.remote.RemoteClient` |
  | `myogestic.vhi.RecordingClient` | `myogestic.remote.RecordingClient` |
  | `myogestic.vhi.InterfaceSpec` | `myogestic.remote.InterfaceSpec` |
  | `myogestic/vhi/_proto/myogestic_vhi.proto` | `myogestic/remote/_proto/remote_control.proto` |

  **No aliases and no shims.** A second name for one thing is what this removes; update the
  import. `myogestic.vhi` keeps exactly what is about the Virtual Hand: `virtual_hand()`,
  the install/version gate behind it, and `pose` — the layout of VHI's *recorded*
  nine-channel pose.

  `InterfaceSpec` gained two fields so the generic launcher can stay generic:
  `install_hint` (appended to the "not installed" error — how a target is installed is
  the target's business) and `version_gate` (a callable that refuses an installed build
  too old to drive; VHI's reads the `vhi-version.txt` marker its own installer leaves).

  `myogestic.widgets.ControlMapEditor` moved with them, out of `myogestic/widgets/vhi/`:
  it edits a map against whatever target answers, and never knew what a hand was. The
  public import is unchanged.

- **BREAKING: the proto is named for the contract, not for VHI.** `package myogestic.vhi`
  → `package myogestic.remote`, `service VhiControl` → `service RemoteControl`. Every
  field number, name and type is unchanged — this renames identifiers, not the wire's
  data — but the **service path** moved to
  `/myogestic.remote.RemoteControl/<Method>`, so MyoGestic and VHI must be upgraded
  together. A mismatched pair fails at connect with `UNIMPLEMENTED`, not silently.

- **`ControlCapability.stream_name` and `.channel` are gone, and so is the shape they
  described.** A streamed control's LSL stream is named for the control's own address and
  is one channel wide, so both fields could only ever repeat what `address` already said.
  Field numbers 10 and 11 and both field *names* are reserved in the proto — the names as
  well, so a later field cannot inherit either spelling in JSON or text format.
  `myogestic.controls.Capability` loses the two attributes to match, and with them go the
  width computation, the outlet/stream mismatch refusal, the channel map, and the
  by-address/elsewhere split inside `RemoteTarget`. A target still serving them reports
  vocabulary 1 and is refused by version.
- **`myogestic.vhi.vhi_targets` is gone.** It existed to build one target per stream a map
  spanned; there is one target now. `[RemoteTarget(client=client, interface=vhi)]`.
- **`RemoteTarget` takes no outlet and no `stream_name`.** It owns one outlet per address it
  drives and builds every one of them, so the only sink parameter is `interface=` — the
  thing they are built from, called once per address as
  `stream_outlet(address, n_channels=1)`. A recorder or a test double substitutes there
  rather than as a single supplied outlet, because one sink can no longer stand for a
  whole binding. Replacing that set on a rebind is **transactional**: the addresses that
  survive keep the outlets they had, the ones that leave are rested, flushed and stopped,
  and the mapping is swapped last — an abandoned LSL outlet stays discoverable and shares
  a `source_id` with whatever replaced it, so what used to be one leak per rebind would
  have become one per address.
- **`load_dofs` and its kind/range/state grammar are gone.** A control space is declared by
  mapping your alias onto a target-owned address; `load_control_map` + `resolve` replace it.
  The old grammar let a *mapping* claim a control was signed, or discrete, or ranged — facts
  only the target can know, and which went silently wrong when it disagreed.
- **The recorded control-space format changed** and is tagged `alias-address/1`. Recordings
  and model sidecars written before it are refused with a message naming the format, rather
  than being reinterpreted under a grammar whose meaning has moved.
- **VHI's control plane collapsed to one gRPC service, and none of this has a compatibility
  window.** The separate `VhiTrainingAid` service is gone; its RPCs move onto `VhiControl`
  and lose "training" from their names in the process (`StartTrainingProgram` →
  `StartRecordingTrajectory`, `StopTrainingProgram` → `StopRecordingTrajectory`,
  `GetTrainingState` → `GetRecordingSessionState`) — a recording aid that cannot see what
  the control service already declared to the same hand was two sources of truth for one
  state machine, not two independent responsibilities. The per-capability
  `ContinuousEncoding` field is gone from the manifest, and so is `control_pose_encoding`:
  the sign convention it used to carry left the wire entirely once `RemoteTarget` stopped
  computing one to negate. `Declare` went with it — the manifest *is* the contract, so there
  is nothing to declare per client. On the Python side, `VhiCanonicalClient` and `VhiTrainingAidClient` become
  `RemoteClient` and `RecordingClient`, both bound to the one stub. None of this
  degrades gracefully — an old MyoGestic against a new VHI, or the reverse, refuses to link
  at all: wrong service name, wrong RPC names, a field that no longer exists. **MyoGestic
  and VHI must be upgraded together**; there is no staged rollout and no version this pair
  is backward-compatible with.

### Changed

- **`RemoteTarget` can build its own stream.** `RemoteTarget(client=…, interface=…)` with no
  outlet publishes one as wide as the target's pose layout, so an application does not
  have to know that width to construct an outlet. `RemoteTarget(outlet, …)` is unchanged.

  Values sit at the target's own channel indices, because a channel *is* an address: the
  manifest says `vhi.prediction.index` is channel 2 and both ends read that from the same
  table. An earlier version compacted the frame and labelled each channel so the receiver
  could put it back — three floats a frame, paid for with a routing table at each end and
  an LSL round-trip that crashed the target.

- **LSL outlets carry per-channel labels and a stable `source_id`.** Without an id, LSL
  cannot tell a restarted outlet from a new stream, so a consumer that resolved the old one
  keeps a dead inlet — measured against VHI, which then stayed deaf until *it* was
  restarted.
- **The VHI examples declare DOFs instead of building frames.** `emg_regression`,
  `emg_regression_raulnet`, `emg_classification_grpc` and `emg_32ch_multi_model` no longer
  contain a channel index or a sign flip. `emg_classification_grpc` also lost its
  hand-rolled `EdgeTrigger`: that debounce is a property of the DOF, so it is `debounce_s`
  and the bus owns the edge detection, dedupe and rebase-on-click.
- **`VhiMovementPanel` is a control-hand aid.** It reads VHI's recording aid for state and
  takes its click handler explicitly — there is no default, because dispatching straight at
  a target would bypass the DOF's debounce, the only thing protecting a classifier-driven
  session from state chatter.

### Fixed

- **The browser playground could not start.** `App.run()` entered a context manager that
  starts a daemon thread to filter GLFW's stderr, and Pyodide has no threads — so the boot
  path raised `RuntimeError: can't start new thread` before the first frame. It is a no-op in
  the browser now: the warning it collapses is a macOS multi-monitor artefact that cannot
  arise there. Stopping a recording packed the session in a thread too, so the playground's
  own Record button hit the same error and left the session unpacked; it packs inline there.
- **`import myogestic` could crash where there is no home directory.** The liblsl config probe
  called `Path.home()`, which raises `RuntimeError` — not `OSError` — when `~` cannot be
  resolved, from a module imported first by the package. In a container with no `HOME` and no
  passwd entry, the import died on line one. It is now skipped entirely under Emscripten and
  guarded elsewhere.
- **A stopped `LSLOutlet` no longer keeps its stream discoverable.** liblsl keeps a stream
  resolvable for as long as its `StreamOutlet` object lives, not for as long as anything is
  pushing, and a stopped-but-live outlet shares its `source_id` with whatever replaced it — so
  a consumer could resolve the dead one and read a layout that no longer matched. `stop()`
  now releases it. MyoGestic also stops binding IPv6 multicast responders it cannot use.

- **A `Bridge` could report a subprocess stopped while it was still running.** `stop()` sent
  SIGKILL and then never waited for it, recording `"stopped"` either way — but SIGKILL does
  not reach a process parked in an uninterruptible kernel wait, and a wedged driver is enough
  to put one there. It now waits the kill out, keeps the handle when it does not land, and
  logs a warning naming the PID, since nothing renders a bridge. `status` is derived from the
  subprocess on every read instead of stored, so it can no longer contradict `alive` or go
  stale when a child exits on its own — it is read-only now, with the two values it always
  had, and `process.returncode` is what says whether an exit was clean. `start()` refuses
  while a child is `alive` rather than overwriting the handle and orphaning it, which is how
  four targets stacked up in `ProcessLauncher`. And stdout/stderr go to `DEVNULL`: those
  pipes never had a reader, so a bridge that outgrew the ~64 KB buffer blocked in `write()`
  forever while still reading as alive — a silently stalled data source rather than a hang
  you would notice. Run the command in a terminal to watch a bridge's output. Registering a
  bridge still does not start it, which the docs had claimed for some time.

- **`examples/synthetic/vhi_playground.py` is now `control_map_studio.py`**, and drives VHI
  and the keyboard from one map. The old name stopped being true the moment a second target
  existed.
- **`thumb` is `thumb.flexion`** in every shipped `examples/controls/*.toml`. VHI advertises
  the explicit axis now, because the thumb has two and a bare name did not say which. A
  single-axis digit keeps its bare name. Any map outside this repo using `vhi.prediction.thumb`
  or `vhi.control.pose.thumb` needs the same one-word edit; the target still accepts the
  bare form, but `resolve()` validates against the manifest and will refuse it.
- **`tools/verify_control_direction.py`** — a live gate proving the predicted hand's
  control direction. VHI's own suite proves *direction* from its rig, but cannot drive the
  LSL inlet, which is the path every real client uses; this checks that a control `+1`
  flexes, reads back as `+1` on `VHI_Predict`, and does so identically whether the client
  declared nothing, the predicted stream, or both streams — over repeated frames, repeated
  runs, and (with `--restart`) repeated target processes. It found the target inverting
  every flexion DOF, fixed in VHI as `Vhi.StandardPose`.

  Two ordering rules it documents are properties of the target worth knowing: an
  `Outlet` repeats its last pushed vector at `hz` and the target overwrites its whole
  pose from the inlet every frame, so **a still-streaming outlet beats `SweepControl`'s own
  commands** — and a stale outlet left behind by an earlier process still wins the single
  `MyoGestic_Output` inlet, which is why a control `+1` could appear to render either way.
  A replaced outlet is also not noticed immediately: VHI re-resolves by name only while it
  has no inlet at all, so recovery rides on the outlet's stable `source_id`.
- **Four pose tables documented channel 1 as `0` in a fist; recorded VHI sessions have it at
  exactly `-1.0`.** The integration guide also described channel 0 as thumb *rotation* and
  channels 6-8 as a wrist. Channel 0 is thumb flexion, channel 1 thumb abduction, and 6-8
  are read by no consumer. All four tables are gone — the examples declare control values,
  so there is nothing left to be wrong.
- **`emg_regression` clipped predictions *before* smoothing**, letting the filter overshoot
  back out of the range just enforced. The bus clips, smooths, and clips again.
- **The regression training target used `np.abs()`**, folding any extension the operator did
  into flexion of equal magnitude. Both ends now speak the control standard, so target space
  and command space are one declaration.


## [2.4.0] - 2026-07-25

### Changed

- **Signal viewer — `channel_scope` restricts a panel to its own channels.** `initial_channels`
  only ever *seeded* a selection, so a per-electrode-grid panel stayed scoped only until the user
  touched it: **All** enabled every channel in the stream, `[Edit…]` listed every grid, and the
  count read `N/320` instead of `N/64`. `SignalViewer(channel_scope=…)` is the hard restriction —
  the columns a panel may *ever* show. It bounds the seed, All/None/Invert, the count, the grid
  selector, shift-click ranges and rubber-band drags, and forms part of the selection cache key.
  `None` (default) is unrestricted; an explicit scope matching no valid column renders
  "no channels in scope" rather than silently widening back to the whole stream. Note it also
  drives the default selection, so a 64-channel scope opens on its first 16 unless
  `initial_channels` is passed too.
- **Signal viewer — several viewers can share one stream.** New `SignalViewer(widget_id=…,
  title=…, show_controls=…)`. State and ImGui ids now key off `widget_id` (defaulting to
  `stream_name`) instead of the stream, so N viewers can show one stream through N panels — e.g.
  **one viewer per electrode grid**, tiled with the existing `Grid` layout — each keeping its own
  channels, scale, filter and pause. Previously every `SignalViewer("emg")` resolved to the same
  state and rendered identically. `title` names each panel and `show_controls=False` opens a tile
  with the control menu collapsed. Note the panels do **not** share a y-scale: give them a common
  manual range before comparing amplitudes across tiles.
- **Heatmap — shared colour range.** `Heatmap.ui(..., vrange=(lo, hi))` maps colours to an explicit
  range instead of each frame's own min/max. Needed whenever several heatmaps are compared (with
  per-instance autoscaling a quiet electrode array and a loud one render identically); also stops a
  single heatmap's colours drifting frame to frame.
- **Signal viewer — multi-grid selector tiles near-square.** The channel-grid window (`[Edit…]`)
  now lays several grids out **side by side** in a near-square block (`ceil(sqrt(n))` columns — e.g.
  6 grids as **3 × 2**) instead of one tall vertical stack, and opens sized to fit the tiling. Makes
  a multi-adapter layout (e.g. Quattrocento `IN1…IN6`) usable without endless scrolling; per-grid
  spatial click/drag is unchanged.
- **Signal viewer — hide the panel chrome.** A `≡` button on the `SIGNAL` header collapses
  *everything* around the plot — title, control menu (scale / filter / detail / window), channel bar
  and footer — so a small tiled panel is nearly all trace. Collapsed, the button shrinks to a bare
  icon so there is always a way back. `SignalViewer(show_controls=False)` opens collapsed.

- **Signal viewer — eased auto y-scale.** Auto scale mode no longer hands the y-axis to ImPlot's
  per-frame `auto_fit`, which made a variable signal in a small window zoom in/out constantly. It
  now **grows fast, shrinks slow**: the range **snaps out instantly** to contain a new peak (never
  clipped) but contracts over ~5 s (so it never jitters downward). Switching the shown stream /
  channels / display-filter / notch / gain / RMS window snaps once, then settles. Manual mode and
  the Rescale button (snap-and-hold) are unchanged (and Rescale is now gain-correct).
  **Per-channel** mode gets the same treatment: each channel's normalisation range is eased
  (snap-out / slow-shrink) and the axis is pinned to the lane geometry, instead of recomputed
  every frame, so per-lane amplitudes no longer breathe. The underlying per-channel range scan is
  now vectorized (a single NaN-aware axis-0 reduction), cutting per-frame cost ~15× at 256
  channels so per-channel mode stays smooth on high-density grids.
- **Signal viewer — per-channel Auto/Manual.** Per-Ch no longer greys out Auto/Manual/Rescale: it
  is the scaling *basis* (shared vs one lane per channel) and Auto/Manual is the adaptation policy
  applied to either. Per-channel **Manual** freezes each lane's current range, so a channel
  weakening / strengthening / drifting stays visible against its captured reference (instead of
  always being re-normalised to fill its lane); **Rescale** ("Fit & lock") re-fits every channel
  and locks; **Gain** is live in per-channel Manual (magnifies each trace against its frozen
  range) and inert in per-channel Auto.
- **Signal viewer — artifact-robust y-scale.** Fitting the range (Auto, per-channel, and Rescale)
  now ignores transients shorter than a configurable budget (**"Artifact" control, default 20 ms**),
  so a brief movement-artifact spike no longer blows up the scale and dwarfs the real EMG. It works
  by *duration*, not amplitude — the visible window is split into equal-time bins and the few most
  extreme bin-maxima/minima that a sub-budget transient could occupy are dropped — because a 10 ms
  artifact and a 10 ms real event are indistinguishable by amplitude alone. Mode-aware
  (rectify/rms_env pin the lower bound to 0), per-channel then unioned for the shared axis (never a
  flattened percentile that would drown out a contraction on one of many channels), and cheap
  enough for the per-frame path (~11 ms at 256 ch). `0 ms` restores plain min/max.
- **Signal viewer — width-relative "Detail" control.** The fixed **"Point cap"** slider (100–10000
  points) is replaced by a **"Detail"** slider (shown as a percentage of full, default 100%) that
  sets draw density *relative to the plot width* (full = a few points per pixel). The old cap fought
  the width-derived target
  (`min(n_pixels, plot_width × 3)`), so on a typical plot the top half of its range was a dead zone
  (raising it past `plot_width × 3` did nothing) and the default under-resolved wide plots; the new
  control is meaningful end-to-end — full detail always tracks the plot, and you only turn it *down*
  for a coarser, cheaper trace when many channels tax the frame rate. The `SignalViewer(n_pixels=…)`
  constructor arg is demoted to an optional hard-cap override (default `None` = no cap).

### Fixed

- **Light theme: hardcoded colours now follow the theme.** Nineteen colours were typed as literals
  across eight widget files and could not respond to the active theme — a near-white session-manager
  label and the raw viewer's footer were washed out on the light theme, the channel-grid hover
  outline was white-on-white (invisible), and the prediction readout flashed *toward white*, i.e.
  into the card. They now read the theme (`muted()` / `primary()` / `hairline()`) or a named token.
  Colours that are deliberately fixed in both themes (the console surface, the status pill) are now
  named tokens in `widgets/common.py` rather than inline literals.
- **`RawSignalViewer` renders in the app's plot style.** It called `implot.begin_plot` without
  `ensure_implot_style()`, so it drew with stock ImPlot chrome — chart border, opaque background,
  heavy grid — instead of matching every other plot.
- **`ProcessLauncher`** used its own red/green rather than the shared `DANGER` / `SUCCESS` status
  colours, so Stop/Launch didn't match status elsewhere in the app.

### Added

- **`docs/concepts/visual-language.md`** — the visual contract (type, colour, panel headers, state
  cues, plot styling, units, pop-out vs collapse, widget identity), beside the existing code
  contract in `design-principles.md`. `tests/test_visual_language.py` enforces the two rules a
  machine can decide honestly: no colour literals outside the design layer, and every module that
  opens a plot styles it.

## [2.3.2] - 2026-07-23

### Changed

- **Signal viewer — incremental mains-notch.** The display notch now filters
  only the newly-arrived samples each frame (persisting the causal IIR state on
  the viewer) instead of re-filtering the whole visible window, which made the
  notch "super slow" at 10 kHz. At 10240 Hz × 16 channels this is ~300× less
  notch computation per frame (~40 ms → ~0.15 ms). The displayed trace is
  unchanged except for a microscopic improvement at the far-left settling edge:
  persistent state means an already-drawn sample is never revised as the window
  scrolls (the old per-frame notch re-seeded a fresh 0.5 s warm-up each frame).
  `Stream` gained a locked `get_raw_snapshot_stable()` (a copy tagged with an
  `epoch` + absolute sample sequence) so the stateful filter can tell new
  samples from seen ones and never tears on a concurrent buffer refresh. The
  cached filter is robust to a mid-stream reconnect (the sample rate is captured
  atomically with each snapshot), to widening the window while paused, and to a
  looping `ReplaySource` (a backward timestamp cold-resets the cached state).

## [2.3.1] - 2026-07-22

### Added

- **Signal viewer — mains-hum Notch.** A new `Notch` control (Off / 50 Hz /
  60 Hz) on the signal viewer's control bar removes mains-line interference and
  its low harmonics from the display, applied before the `View` transform. It is
  a visual-only, **causal** IIR notch (`scipy.signal.iirnotch` cascaded over the
  fundamental + first harmonics), so a given sample's filtered value never
  changes as the scope scrolls — the trace does not jitter. Recording and model
  input are left untouched.

### Changed

- `scipy` is now a core dependency, used by the signal viewer's causal notch
  (`scipy.signal.iirnotch` / `lfilter`).

## [2.3.0] - 2026-07-22

A large release on two fronts: the **widget API is unified on classes**
(construct once, render with `.ui(...)`, replacing the old mix of free functions
and `.ui()` objects), and the whole UI gets an aesthetic pass ("Calm Instrument")
plus native pop-out windows.

### Changed (breaking)

- **Every widget is a class rendered via `.ui(...)`.** Construct once (config in
  the constructor), then call `.ui(...)` each frame with only the per-frame
  inputs — `ctx` for stream/recording/log widgets, live data for plots, nothing
  for widgets that read from held refs. Renames: `signal_viewer` →
  `SignalViewer`, `raw_signal_viewer` → `RawSignalViewer`, `stream_panel` →
  `StreamPanel`, `line_plot` → `LinePlot`, `heatmap` → `Heatmap`, `scatter2d` /
  `scatter3d` → `Scatter2D` / `Scatter3D`, `recording_controls` →
  `RecordingControls`, `session_manager` → `SessionManager`, `prediction_label`
  → `PredictionLabel`, `template_inspector` → `TemplateInspector`,
  `trial_preview` → `TrialPreview`, `log_panel` → `LogPanel`, `app_logo` →
  `AppLogo`, `image` → `Image`, `process_launcher` → `ProcessLauncher`; and in
  `myogestic.ml.widgets`: `pipeline_panel` → `PipelinePanel`, `train_button` /
  `predict_button` → `TrainButton` / `PredictButton`, `training_log` →
  `TrainingLog`, `save_model_button` / `load_model_button` → `SaveModelButton` /
  `LoadModelButton`. `FeatureSelector`, `FilterControl`, and `VhiMovementPanel`
  were already classes and are unchanged.

  ```python
  # before
  @app.ui
  def ui(ctx):
      signal_viewer(ctx, "emg", selectable=True)

  # after — construct once, render each frame
  viewer = SignalViewer("emg", selectable=True)

  @app.ui
  def ui(ctx):
      viewer.ui(ctx)
  ```

  **Construct the widget once (module/app scope), not inside `@app.ui`** —
  instances hold state, so rebuilding one every frame resets its selections /
  tuning.

- **`FilterControl` replaced by `PostProcessor` / `FilterProcessor`.** The
  output-smoothing widget is now an **extensible** palette: `PostProcessor(hz=…)`
  is the drop-in preset (three built-in filters, one-euro default) and
  `FilterProcessor(filters=[…])` accepts your own filters as `FilterSpec`s
  (auto-generated sliders from each spec's `FilterParam`s). `FilterControl(hz=32,
  default="one_euro")` becomes `PostProcessor(hz=32)`.

### Added

- **Extensible output filters.** Register custom smoothers via `FilterSpec` /
  `FilterParam`, and compose several into one with
  [`chain`][myogestic.outputs.chain] (`chain(GaussianFilter(...),
  OneEuroFilter(...))` is a single `VectorFilter`). One Euro now retains its
  smoothing history while you tune it (in-place reconfigure, no reset-on-drag).
- **Native pop-out windows (multi-viewport).** On desktop, ImGui viewports are
  enabled by default; the signal viewer's channel-grid `Edit…` opens as its own
  OS window you can move to another monitor.
- **Bundled fonts** (OFL / permissive): Instrument Serif for the prediction hero
  readout, IBM Plex Mono for the console logs.
- **`Heatmap(colormap=…)`** with a perceptually-uniform default (viridis).
- **Reason tooltips on disabled ML buttons** — Predict / Save / Load explain
  why they are unavailable.

### Changed

- **Aesthetic theme pass ("Calm Instrument", from a codex + fable design
  consult).** Surface elevation (flat `#1E1E1E` → canvas / card / raised /
  control tiers); accent reserved for selection / primary action / focus with a
  neutral pressed state; the previously un-styled ImGui slots filled (tabs,
  tables, text-selection, nav, docking); a 4/8 spacing + rounding rhythm; and one
  semantic status palette (`SUCCESS`/`WARNING`/`DANGER`/`INFO`/`IDLE`) across the
  status dots, the recording pill and the pipeline states.
- **Selection cue** is now a translucent accent tint + underline (from one shared
  `push_selected()` primitive), not a solid fill.
- **Themed plots** — every multi-series plot uses the shared class palette, the
  heatmap uses viridis, and ImPlot itself is styled (no chart border, faint grid,
  clear background).
- **Signature touches** — an Instrument Serif hero prediction readout; mono / dark
  **console logs** (still selectable & copyable, per 2.2.1); a macOS **segmented
  control** for the signal viewer's Auto/Manual; a **value-flash** on the
  prediction readout; Font Awesome transport icons; `panel_header` on every
  widget; and muted empty-states.
- **Signal control bar** split into grouped rows (source / transport / view ·
  y-scaling · resolution) so it composes when narrow.

### Fixed

- **`FeatureSelector` ImGui id collision.** Two selectors in one window no longer
  collide (the render is scoped per instance), and columns are laid out in a
  content-sized table so a label never clips under the next checkbox.
- **Session manager** lists the sessions already in its folder on open, accepts
  any `.zip` containing a `meta.json`, and dedups by canonical path (fixes the
  macOS `/var` vs `/private/var` double-add through the file dialog).
- **Responsive control layouts** — the process launcher, the recording class
  buttons, and the post-processing Reset no longer overflow or clip in narrow
  cells.
- **Heatmap axis ticks** align to the cell grid; the **VHI movements example** no
  longer crashes its refresh thread on an incomplete reply.

## [2.2.1] - 2026-07-20

### Fixed

- **Log boxes are selectable and copyable again.** `render_log` — used by the
  model training log and the process launcher — drew each line with
  `imgui.text_unformatted`, which paints static glyphs that cannot be selected,
  so the log text could not be copied out. It now renders a read-only
  `input_text_multiline`, the same widget `log_panel` uses, so the text can be
  selected and copied (Ctrl/Cmd+C).

## [2.2.0] - 2026-07-19

Signal-viewer overhaul for high-channel HD-EMG: a spatial channel selector, an
RMS-envelope display mode, and the performance work to make hundreds of channels
usable. Backward-compatible — old sessions still load.

### Added

- **Spatial channel-grid selector.** A compact bar opens a floating grid of
  cells laid out by electrode grid (showing the channel index); click to toggle,
  drag to rubber-band a rectangle, shift-click for a linear range. Replaces the
  one-button-per-channel wall.
- **Configurable RMS-envelope display** (`display = rms_env`) with adjustable
  **RMS window** and **RMS shift** — a sparse, scroll-stable trailing-RMS trace
  computed on the incoming signal. Visual-only (recording/model input unaffected).
- **`StreamInfo.channel_grids`** channel topology, persisted across session
  save/load so a replayed recording keeps its layout.
- **`signal_viewer(..., initial_channels=...)`** to bound the initially-enabled
  channel set so a 256-channel stream doesn't open as 256 lines.

### Changed

- **M4 display decimation now runs lazily on the render thread**, not on the
  acquire loop — where computing it for every channel ~60×/s starved
  high-channel-count acquisition and pinned the viewer's frame rate.
- **Viewer decimation rebuilt** as one vectorized shared-x MinMax over only the
  enabled channels, anchored to an absolute-time bucket grid (scroll-stable).
- **Per-channel viewer stats throttled** (~10 Hz) and computed without an
  all-column copy.

### Fixed

- **Windows:** retry zarr's chunk-rename on transient file locks (antivirus /
  search-indexer handles), fixing intermittent `PermissionError` crashes
  mid-recording.
- Guard the MinMax decimator against an out-of-memory blow-up on degenerate
  flat-timestamp runs (a device clock stall or a monotonic-clamped session).
- Size the M4 output scratch to the sample count instead of
  `n_out * n_channels` (~2 GiB → ~21 MB at 256 ch).

## [2.1.0] - 2026-06-07

Library reorganization, public-API standardization, and Windows session-save
reliability. The API changes are **breaking** but mostly mechanical renames —
old → new below.

### Changed

- **Reorganized into responsibility subpackages** (`sources`, `outputs`, `ml`,
  `recipes`, `session`, `vhi`, `widgets`, `bridges`). Most public imports are
  unchanged — thin facades re-export the same names — but a few moved:
  - `myogestic.interfaces` (VHI) → `myogestic.vhi`
  - `myogestic.contrib.*` and `myogestic.models.*` → `myogestic.recipes`
    (feature recipes `myogestic.recipes.features`; estimator recipes
    `myogestic.recipes.estimators`)
  - model persistence: `myogestic.models.save_model` / `load_model` →
    `myogestic.ml.save_pickle` / `load_pickle`
  - output-smoothing filters → `myogestic.outputs.filters` (also re-exported
    from `myogestic.outputs`); `EdgeTrigger` → `myogestic.outputs` (and still
    top-level `myogestic.EdgeTrigger`)

- **BREAKING — public parameters renamed** for a self-descriptive surface:
  durations now carry unit suffixes (`_ms` / `_s`), rates use `hz` / `*_hz`,
  counts use `n_`, and cryptic/abbreviated names are spelled out.

  *Streams & window extraction*
  - `Stream(window_seconds=, buffer_seconds=)` → `Stream(window_ms=, buffer_ms=)`
  - `iter_labeled_windows(win_seconds=, hop_seconds=)` → `(window_ms=, hop_ms=)`
  - `iter_aligned_windows(primary_stream=, aligned_streams=, win_seconds=, hop_seconds=, align_window_samples=)`
    → `(primary_stream_name=, aligned_stream_names=, window_ms=, hop_ms=, n_alignment_samples=)`
  - `signal_viewer(window_seconds=)` → `signal_viewer(window_s=)`

  *Session*
  - `Session.init_stream(name=)`, `Session.append(name=)` → `stream_name=`
  - `Session.get_trials(pre=, post=)` → `pre_s=, post_s=`

  *Filters & outputs*
  - `OneEuroFilter(freq=, min_cutoff=, d_cutoff=)` → `(hz=, min_cutoff_hz=, derivative_cutoff_hz=)`
  - `GaussianFilter(window=)` → `n_vectors=`
  - `make_filter(...)` forwards these kwargs, so `make_filter("one_euro", min_cutoff=, d_cutoff=)`
    → `min_cutoff_hz=, derivative_cutoff_hz=` and `make_filter("gaussian", window=)` → `n_vectors=`
  - filter `__call__(x, t=)` → `__call__(x, timestamp=)` (every filter and `FilterControl`)

  *Recipes & VHI*
  - `constant_classifier(class_idx=)` → `class_index=`
  - `InterfaceSpec`: `output_stream=/control_stream=/control_pose_stream=` →
    `*_stream_name=`; `output_channels=/control_channels=/control_pose_channels=` →
    `n_output_channels=/n_control_channels=/n_control_pose_channels=`
  - `virtual_hand(mode=)` → `launch_mode=`
  - `VhiMovementPanel(refresh_min_interval_s=)` → `min_interval_s=`

  *Widgets*
  - `template_inspector(uid=)`, `trial_preview(uid=)` → `widget_id=`
  - `trial_preview(window=)` → `as_window=`
  - `process_launcher(label=)`, `FilterControl.ui(label=)` → `widget_id=`
  - panel-heading `label=` → `title=` (`prediction_label`, `session_manager`,
    `vhi_movement_palette`, `VhiMovementPanel`)
  - `prediction_label(key=, proba_key=)` → `class_key=, probability_key=`
  - `FeatureSelector.set_active(on=)` → `active=`

  *CLI tools* (flag names unchanged — `--channels`, `--classes`, `--chunk`,
  `--control`): the Python params of `emg_generator` / `lsl_dummy` `main()`
  were renamed `channels`/`classes`/`chunk`/`control` →
  `n_channels`/`n_classes`/`chunk_size`/`control_stream_name`.

### Added

- Streams accept integer and float dtypes (`StreamInfo(dtype=...)`, default
  `float32`).
- `EdgeTrigger(n_stable_ticks=N)` debounce — fire only after a value holds for
  N consecutive ticks (swallows classifier flicker).
- Docstring coverage is enforced (ruff pydocstyle, NumPy convention): every
  public module, class, and function is documented.

### Fixed

- **Windows session saving**: finalizing a recording (`Session.pack_to_zip`)
  assumed POSIX file semantics and failed on Windows with
  `PermissionError: [WinError 32]` — open zarr / `ZipStore` handles can't be
  deleted or renamed there. Packing now releases handles, retries the folder
  cleanup, and uses `os.replace`, so saving a recording works on Windows.
- **Leaked session file handles**: reading a session (`open_session_store`,
  `ReplaySource`, `iter_labeled_windows` / `iter_aligned_windows`) left the
  `.session.zip` open, which locks the file on Windows. `Session` is now
  closeable (and usable as a context manager) and every reader releases the
  handle when it is done.
- **VHI connection robustness**: while the Virtual Hand is disconnected, the
  gRPC state poll backs off and uses a short probe deadline, and repeated
  failures are deduped/quieted — a closed or absent VHI no longer floods the log
  or stutters the render loop.

### Changed (internal)

- CLI tools (`emg_generator`, `lsl_dummy`, `install_vhi`, `webcam`) migrated
  from `argparse` to Typer.
- Tests + CI: documentation code blocks are parse-checked (and the tagged ones
  executed) and the example scripts are smoke-run, with the full test suite now
  running on Linux **and Windows** (previously CI only built the docs).

## [2.0.2] - 2026-06-03

### Fixed
- **Recording crash on Stop**: clicking Stop while data was still streaming could kill the per-stream acquisition thread with `KeyError: '<stream>'`. The acquire loop checked and used `Stream._session` outside any lock while `App.stop_recording()` nulled it and a daemon thread cleared the session's Zarr stores, so an append already in flight ran after the stores were gone. A new per-stream `Stream._session_lock` now makes attach/detach atomic with the acquire loop: `detach_session()` waits for any in-flight append before returning, so the subsequent pack-and-clear can no longer race. The lock is deliberately separate from the buffer/window lock used by UI-facing reads (`get_window()`, `last_timestamp()`), so disk writes never block the display path
- **Same-second session folder collision**: starting a new recording within the same wall-clock second as stopping the previous one could destroy the new recording. `Session.__init__` named the folder with a second-resolution timestamp and created it with `mkdir(exist_ok=True)`, so two sessions shared one folder and the first session's background `pack_to_zip()` (which deletes its own folder and writes `<name>.session.zip`) could remove or collide with the new session's data. Each session folder now gets a short `uuid4` suffix, so rapid same-second sessions no longer share a folder. The folder name is only used to derive the zip name and for display and logging, so the format change is safe
- **Silent loss masking**: `Session.append()` now drops a late append for a finalized stream and logs it at debug level instead of raising, as defense in depth around the teardown path

## [2.0.1] - 2026-05-17

### Changed
- **PyPI metadata republish**: re-released so PyPI picks up the README fix (absolute URLs for the image and for the docs and examples links). No code changes; the wheel content is identical apart from the metadata version and the embedded description

## [2.0.0] - 2026-05-17

### Added
- **v2 rewrite**: ground-up redesign of the framework, replacing v1 with a focus on small, composable API surfaces and live extensibility
- **Core primitives**: new App, Stream, Pipeline, and Source/Output building blocks. User code is plain decorated functions (`@app.ui`, `@pipeline.extract` / `train` / `predict`) with no base classes, registries, or config files
- **Real-time viewers**: signal viewers backed by a dvg-ringbuffer with M4 display decimation. Recording lands as a Zarr session zip
- **ML lifecycle**: train and predict run on dedicated threads (asyncio-cooperative under Pyodide)
- **UI toolkit**: Dear ImGui widgets via imgui-bundle, with a Px/Fr typed grid for layout
- **VHI integration**: gRPC plus LSL dual-plane integration with the Virtual Hand Interface

---

## Types of Changes
- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for any bug fixes
- **Security** for vulnerability fixes
