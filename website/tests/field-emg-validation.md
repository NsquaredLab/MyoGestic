# Signal-field EMG validation

The private session is opened with `myogestic.session.open_session_store`. No
recording arrays or excerpts are checked in or served by the website. The optional
reference bridge binds only to loopback and holds its comparison windows in memory.
Its session argument must be supplied locally.

## Reference and display choice

The recording has 320 channels, 2048 Hz, and 190464 samples. Select the contiguous
64-channel block with the greatest mean squared amplitude across **all labelled
Fist samples**: zero-based channels **45–108**. Use only stationary labelled
intervals, excluding the first 650 ms after each label, for distribution/RMS maps.
Centre each channel by its median; apply no filter or interpolation. Round each
Rest/Fist RMS map to three decimals relative to maximum Fist channel RMS.

Compare 480 point samples spanning four seconds, paired min/max extrema of each
17–18-sample bin, and 480 consecutive native samples (234 ms, about 17× slow motion).
Point sampling at 120 columns/s preserves the original four-second crossing time
and is readable. Min/max fills too much of each lane; the native view is much
smoother and slower. `field-three-mappings.png` records the three real-data views.
The table below uses the selected point-sample view; p99 and p99.9 use each
channel's stationary RMS as their normalizer and pool absolute amplitudes.

| Statistic | Real | Synthetic (seed 314159) |
| --- | ---: | ---: |
| Fist/rest RMS | 7.4948 | 7.8880 |
| Rest signed neighbour correlation | -0.2581 | -0.2315 |
| Fist signed neighbour correlation | 0.1577 | 0.1590 |
| Rest p99 / channel RMS | 1.5871 | 1.5322 |
| Fist p99 / channel RMS | 1.8759 | 1.8484 |
| Rest p99.9 / channel RMS | 13.0889 | 13.9533 |
| Fist p99.9 / channel RMS | 2.0522 | 1.9531 |
| Rest lag-1 correlation | -0.2521 | -0.3112 |
| Fist lag-1 correlation | -0.3130 | -0.3147 |
| Onset envelope tau | 18.0 ms | 18.0 ms (generator constant) |
| Offset envelope tau | 18.0 ms | 18.0 ms (generator constant) |

Envelope measurements use 50 ms RMS, 10–90% width divided by ln(9), then the
median over three Fist transitions. Recorded Fist activation precedes its label
by approximately 531 ms; the side-by-side screenshot aligns the observed onset.
The synthetic noise combines reflected phase jitter (bounded active amplitudes),
spatially correlated background, and sparse alternating-polarity low-effort
potentials. It matches the stated aggregate statistics. Open and Pinch use synthetic smooth spatial envelopes on the Fist RMS profile. `FIELD_GAIN =
0.26` keeps the maximum-channel active p99 estimate at 0.473 lane while retaining
visible resting texture and sparse spikes.

## Thickness and rendering

DPR 1 was compared on Apple M5 Pro / ANGLE Metal at 1440×900 against geometry.
It thickens a 2× canvas but leaves a 1× canvas unchanged. Keep the existing DPR
policy and draw each segment as a two-device-pixel quad perpendicular to its
slope, including steep MUAP reversals. Composite colour against the background
once in the shader with blending disabled, so overlapping joins cannot glare.
Canvas 2D doubles `lineWidth` from one to two CSS pixels and uses source-over.
Both full (64×480) and reduced (32×240) tiers are covered at DPR 1 and 2.
Software WebGL uses the existing Canvas fallback to avoid its synchronous shader
compilation cost. Adaptive tier density, cadence, thresholds, sample speed, reduced
motion and offscreen scheduling are unchanged. The still-frame browser test waits for load/idle drawing and font
layout before checking pixel equality.

Screenshots are local, uncommitted artifacts in `.superpowers/screens/`:
`field-real-vs-synthetic.png`, `field-three-mappings.png`,
`field-thickness-1x.png`, `field-thickness-2x.png`,
`field-hero-dpr1.png`, and `field-hero-geometry.png`.

## Reproduction

From the repository root, start the private bridge (stop it after capture):

```sh
uv run python website/tests/field-reference.py "$SESSION" --serve 4381
```

With a built-site preview running, from `website/`:

```sh
node tests/field-visual-check.mjs http://127.0.0.1:4381 ../.superpowers/screens http://localhost:4339/MyoGestic/
npm run ci
```

The screenshot harness also reads the original line renderer from commit
`0c1afc6` for the DPR 1 comparison. The source tree contains only synthetic code,
rounded RMS maps and derived statistics. Measurement and Lighthouse results follow below.


## Final checks (2026-11-07)

`npm run ci` passed under Node 22.23.4, with `CI=1 PLAYWRIGHT_PORT=4340`
for an isolated preview: 19 unit-test files / 79 tests passed; 40 browser tests
passed and one skipped. The existing context-loss browser test skips when
software rendering selects Canvas instead of WebGL; controller unit coverage
still exercises context loss, replacement and lifecycle behaviour.

The island is **5356 bytes gzipped**, measured by the existing esbuild/gzip budget
test and an independent final bundle. GPU textures remain **123136 bytes**.

The supplied `ref/measure-field.mjs` ran for one minute on the final built page
with Apple M5 Pro / ANGLE Metal. At 1440×900, 600 timed callbacks: **0.056 ms mean,
0.100 ms p95, 0.300 ms maximum**. Offscreen: zero callbacks and zero script/task
CPU. Clean-page heap after forced GC: **0.846, 0.863, 0.863 MiB** at 0/30/60 s.
The small startup increase settles; no sustained heap growth was observed.

Lighthouse 12 mobile, `--chrome-flags="--headless=new"`:

| Page | Performance | Accessibility | Best practices | SEO | TBT | LCP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `/MyoGestic/` | 98 | 100 | 100 | 100 | 0 ms | 2029 ms |
| `/MyoGestic/getting-started/` | 98 | 100 | 100 | 100 | 0 ms | 2181 ms |

The homepage trace records long tasks of 205 ms (field startup) and 62 ms (page);
the docs trace records a 77 ms page task. All produce zero reported TBT. Software
WebGL shader compilation initially scored 89 with a 1020 ms task; selecting the
existing Canvas fallback on software renderers resolves that startup cost while
retaining reduced-tier density, cadence and thresholds.

Saved local evidence: `/tmp/field-ci.log`, `/tmp/field-statistics.log`,
`/tmp/field-measurement.json`, `/tmp/field-lh-home.json`,
`/tmp/field-lh-docs.json`, and `/tmp/field-reference-final.json` (derived metrics
only). All six PNGs listed above are 1440×900 and remain uncommitted.

CI tail:

```text
Test Files  19 passed (19)
     Tests  79 passed (79)
Running 41 tests using 2 workers
  1 skipped
  40 passed (20.0s)
```
