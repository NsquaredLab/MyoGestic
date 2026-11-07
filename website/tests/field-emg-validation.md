# Signal-field EMG validation

The fit uses 8-channel forearm bracelet recordings sampled at 1000 Hz. This fit supersedes the previous simulated narrowband common-mode fit, which did not establish a muscle-activity reference. Only rounded RMS maps and scalar aggregates are committed. Recording arrays remain private; the optional comparison bridge holds excerpts in memory on loopback and is never used by the deployed website.

## Selection and filtering

Six complete recording sets were compared, with each set normalized by its own maximum Fist-channel RMS. One set was selected because it maximized the minimum pairwise RMS difference between the four normalized eight-electrode maps. Keeping a single electrode placement preserves spatial selectivity that pooling differently oriented bracelets would blur. The six minimum distances were 0.0973, 0.0640, 0.0343, 0.2076, 0.1307, 0.0786. The selected distance is 0.2076. The selection provides a visual reference. Population estimates and classifier validation require separate analyses.

Each take has a single gesture label near its start. Index means index flexion. A fourth-order Butterworth 20–450 Hz band-pass is applied forward and backward, followed by forward/backward Q=30 notches at 50, 100, …, 450 Hz. The first 650 ms after the later of the label and first sample, and the final 100 ms, are excluded. There is one selected take per gesture, with 9.19–9.26 stationary seconds each. There is no rest-to-contraction cue or offset segment in these takes; onset and offset are not estimable. Both generator envelope constants remain 18 ms.

Per-channel RMS is measured at 1000 Hz after filtering. These eight-number maps, normalized to maximum Fist RMS, are interpolated around a closed bracelet. Lane c uses position 8c/N and wraps electrode 7 back to electrode 0; 64 interpolated lanes are not 64 independent electrodes.

| Gesture | Eight-electrode RMS map |
| --- | --- |
| Rest | 0.0166, 0.0247, 0.0258, 0.0187, 0.0237, 0.0444, 0.0259, 0.0229 |
| Fist | 0.6122, 1.0000, 0.7758, 0.3918, 0.6676, 0.5276, 0.3552, 0.6188 |
| Pinch | 0.0851, 0.1671, 0.7326, 0.4169, 0.5279, 0.4671, 0.1561, 0.0877 |
| Index | 0.2221, 0.1321, 0.4732, 0.3591, 0.1783, 0.1133, 0.0770, 0.0653 |

All six pairwise map distances remain at least 0.18 after spreading to 64 lanes; the seeded test enforces this margin. Rest is low-amplitude texture, Fist has broad recruitment, Pinch emphasizes the middle bracelet sector, and Index has a narrower flexion profile. The four measured maps are used directly.

## Real versus synthetic at the displayed rate

Point sampling uses floor(j × 1000/120), with the clock reset for each take. Point sampling uses no additional anti-alias filter. At full-tier cadence, 480 columns represent four seconds. Both real and synthetic signed signals are circularly interpolated from eight carriers. The synthetic interpolation normalizes variance so each lane follows its interpolated RMS map. This explains its slightly higher absolute RMS and adjacent-lane correlation.

The table reports the selected recordings and generator seed 314159 after 2400 settling columns and 24000 stationary columns per gesture. Tails are pooled absolute amplitudes divided by each channel's own RMS. Electrode neighbours include 7→0; lane neighbours include 63→0. Negative displayed lag-1 is a point-sampling effect; native recorded lag-1 is positive (0.59–0.77).

| Gesture | Statistic | Real | Synthetic |
| --- | --- | ---: | ---: |
| Rest | Native active/rest RMS | 1.0000 | n/a |
| Rest | Displayed electrode active/rest RMS | 1.0000 | 1.0000 |
| Rest | Displayed lane active/rest RMS | 1.0000 | 1.0000 |
| Rest | Electrode neighbour correlation | 0.1051 | 0.1114 |
| Rest | Lane neighbour correlation | 0.9820 | 0.9829 |
| Rest | Lane lag-1 correlation | -0.1618 | -0.1504 |
| Rest | Lane p99 / RMS | 2.6214 | 2.5505 |
| Rest | Lane p99.9 / RMS | 3.6242 | 3.3664 |
| Rest | Lane kurtosis | 3.1675 | 3.0187 |
| Fist | Native active/rest RMS | 24.4451 | n/a |
| Fist | Displayed electrode active/rest RMS | 25.0618 | 24.3978 |
| Fist | Displayed lane active/rest RMS | 26.1249 | 24.3857 |
| Fist | Electrode neighbour correlation | 0.4088 | 0.4078 |
| Fist | Lane neighbour correlation | 0.9870 | 0.9896 |
| Fist | Lane lag-1 correlation | -0.1412 | -0.1522 |
| Fist | Lane p99 / RMS | 3.0616 | 3.0426 |
| Fist | Lane p99.9 / RMS | 4.6701 | 4.8700 |
| Fist | Lane kurtosis | 5.0896 | 4.9975 |
| Pinch | Native active/rest RMS | 15.0487 | n/a |
| Pinch | Displayed electrode active/rest RMS | 14.7577 | 15.0706 |
| Pinch | Displayed lane active/rest RMS | 15.8912 | 14.7407 |
| Pinch | Electrode neighbour correlation | 0.3540 | 0.3566 |
| Pinch | Lane neighbour correlation | 0.9828 | 0.9885 |
| Pinch | Lane lag-1 correlation | -0.2157 | -0.2171 |
| Pinch | Lane p99 / RMS | 3.0687 | 2.9537 |
| Pinch | Lane p99.9 / RMS | 4.1582 | 4.6919 |
| Pinch | Lane kurtosis | 4.4205 | 4.6015 |
| Index | Native active/rest RMS | 9.1803 | n/a |
| Index | Displayed electrode active/rest RMS | 9.0407 | 9.1880 |
| Index | Displayed lane active/rest RMS | 9.5577 | 8.9860 |
| Index | Electrode neighbour correlation | 0.3667 | 0.3711 |
| Index | Lane neighbour correlation | 0.9845 | 0.9888 |
| Index | Lane lag-1 correlation | -0.1253 | -0.1256 |
| Index | Lane p99 / RMS | 3.0989 | 3.0504 |
| Index | Lane p99.9 / RMS | 4.5391 | 4.8906 |
| Index | Lane kurtosis | 5.0658 | 5.0313 |

The generator uses eight correlated carriers with a common component fitted to circular electrode correlation, a per-gesture negative AR(1) term at the displayed rate, and occasional broad innovations for the measured tails. Six summed uniforms approximate Gaussian innovations without frame-path allocations. Use this aggregate visual fit for display; it does not reconstruct motor-unit physiology or native-frequency spectra. Tests require active/rest RMS ratios within ±20%, both neighbour correlations within ±0.1, lag-1 within ±0.1, p99 within ±10%, p99.9 within ±15%, and kurtosis within ±25%.

The real recordings' raw stationary spectra are broad. Line notches intentionally reduce spectral flatness; compare raw and filtered values separately.

| Gesture | Raw peak (Hz) | Raw flatness, 20–450 Hz | Filtered peak (Hz) | Filtered flatness, 20–450 Hz |
| --- | ---: | ---: | ---: | ---: |
| Rest | 20.51 | 0.6818 | 28.32 | 0.4022 |
| Fist | 72.27 | 0.3154 | 72.27 | 0.1632 |
| Pinch | 49.80 | 0.2659 | 59.57 | 0.1375 |
| Index | 107.42 | 0.3822 | 84.96 | 0.2016 |

## Rendering and reproduction

The fit leaves rendering unchanged. It retains two-device-pixel quads, the Canvas 2D software-renderer fallback, renderer tiers, sample cadence, gain, reduced-motion handling and offscreen scheduling. All per-frame storage is preallocated. The 64-lane texture budget remains 123136 bytes.

Define local take-path arrays, then run the reference script with repeated `--group` arguments, one group of local take arguments per recording set. It automatically selects the complete group with the largest minimum map distance. Standard output contains only aggregates; no path, identity or recording excerpt is printed. Add `--serve 4381` only for local comparison capture, then stop the bridge. From the website directory, with a built-site preview running:

```sh
uv run python tests/field-reference.py --group "${TAKES_A[@]}" --group "${TAKES_B[@]}" --serve 4381
# In a separate terminal, after the bridge and built-site preview are ready:
node tests/field-visual-check.mjs "$BRIDGE_URL" "$SCREENSHOT_DIRECTORY" "$SITE_URL"
npm run ci
```

The 1440×900 comparison shows one second each of Rest → Fist → Pinch → Index at the same 120 Hz point-sampling scale on both sides. Each real segment comes from the selected take after settling; each side uses the same circular signal interpolation. Four hero screenshots show each held gesture. Images contain private visual excerpts and remain local, uncommitted evidence.

## Final verification

The foreground `npm run ci` passed under Node 22.23.4 on 2026-11-07. All 19 unit-test files / 80 tests passed; 41 browser tests passed and three skipped. Two playground browser tests skip because this website-only build omits the optional wheel; the context-loss browser test skips when software rendering chooses Canvas 2D. Controller unit tests exercise context loss and replacement, while screenshot and performance checks use hardware WebGL. The gesture, distribution and map tests detect deviations from the measured reference. They were run against the old generator and failed before this implementation. Final focused field tests (37) and the reference script's Ruff check also pass.

CI tail:

```text
All 61 legacy URLs resolve in dist/.
Checked 5645 internal links across 63 HTML pages: no broken links.
Resolved 808/808 legacy API symbols across 11 pages; no exemptions.
Resolved 1325/1325 generated API references.
Test Files  19 passed (19)
     Tests  80 passed (80)
Running 44 tests using 2 workers
  3 skipped
  41 passed (14.3s)
```

The complete field island is 5323 bytes gzipped (12269 minified bytes), below the 10240-byte limit. Textures remain 123136 bytes. The measurement script ran with one minute of clean-page heap sampling on Apple M5 Pro / ANGLE Metal at 1440×900. Across 600 timed callbacks, mean main-thread cost was 0.036 ms, p95 0.100 ms, maximum 0.200 ms. Offscreen callbacks and script/task CPU were zero. Forced-GC heap at 0/30/60 s was 0.850, 0.864, 0.863 MiB; no sustained growth was observed.

Lighthouse 12 mobile, with a fresh headless browser for each page:

| Page | Performance | Accessibility | Best practices | SEO | TBT | LCP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Homepage | 98 | 100 | 100 | 100 | 0 ms | 2031 ms |
| Getting started | 98 | 100 | 100 | 100 | 0 ms | 2179 ms |

Local, uncommitted screenshots: `field-real-vs-synthetic-v2.png`, `field-hero-rest-v2.png`, `field-hero-fist-v2.png`, `field-hero-pinch-v2.png`, and `field-hero-index-v2.png`. All five are 1440×900 and were visually inspected. The comparison shows the expected shared spatial structure and the distinct gesture amplitudes; the live hero remains legible in all four held states.
