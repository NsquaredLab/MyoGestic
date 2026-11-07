import { expect, it } from 'vitest';
import { createFieldState, FIELD_GAIN, mulberry32, setGesture, stepField, type Gesture } from '../src/components/signal-field/field';

// 120 Hz point samples, stationary labelled intervals after 650 ms settling.
// Derived statistics only. Reproduce with field-reference.py and a local session.
function statistics(gesture: Gesture) {
  const s = createFieldState(64, 12000), rand = mulberry32(314159);
  setGesture(s, gesture);
  stepField(s, 2400, rand);
  stepField(s, s.samples, rand);
  const rms = Array.from({ length: 64 }, (_, c) => Math.sqrt(s.data.slice(c * s.samples, (c + 1) * s.samples).reduce((sum, v) => sum + v * v, 0) / s.samples));
  const z = Array.from(s.data, (v, i) => Math.abs(v) / rms[Math.floor(i / s.samples)]).sort((a, b) => a - b);
  let corr = 0, lag = 0;
  for (let c = 0; c < 64; c++) {
    let xy = 0, xx = 0;
    for (let i = 0; i < s.samples; i++) {
      if (c < 63) xy += s.data[c * s.samples + i] * s.data[(c + 1) * s.samples + i];
      if (i) xx += s.data[c * s.samples + i] * s.data[c * s.samples + i - 1];
    }
    if (c < 63) corr += xy / s.samples / rms[c] / rms[c + 1];
    lag += xx / (s.samples - 1) / rms[c] ** 2;
  }
  return { rms: Math.sqrt(rms.reduce((sum, v) => sum + v * v, 0) / 64), neighbour: corr / 63,
    tail: z[Math.floor(z.length * 0.999)], p99: z[Math.floor(z.length * 0.99)], lag1: lag / 64,
    laneP99: Math.max(...rms) * z[Math.floor(z.length * 0.99)] * FIELD_GAIN };
}

it('matches the measured rest/active contrast, signed spatial correlation and p99.9 tails', () => {
  const rest = statistics('Rest'), fist = statistics('Fist');
  console.info('Matched field statistics', JSON.stringify({ rest, fist, ratio: fist.rms / rest.rms }));
  expect(Math.abs(fist.rms / rest.rms / 7.4948 - 1)).toBeLessThanOrEqual(0.2);
  expect(Math.abs(rest.neighbour + 0.2581)).toBeLessThanOrEqual(0.1);
  expect(Math.abs(fist.neighbour - 0.1577)).toBeLessThanOrEqual(0.1);
  expect(Math.abs(rest.tail / 13.0889 - 1)).toBeLessThanOrEqual(0.2);
  expect(Math.abs(fist.tail / 2.0522 - 1)).toBeLessThanOrEqual(0.1);
  expect(Math.abs(rest.lag1 + 0.2521)).toBeLessThanOrEqual(0.1);
  expect(Math.abs(fist.lag1 + 0.3130)).toBeLessThanOrEqual(0.1);
  expect(fist.laneP99).toBeLessThanOrEqual(0.5);
});
