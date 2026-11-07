import { expect, it } from 'vitest';
import { createFieldState, GESTURES, mulberry32, setGesture, stepField, type Gesture } from '../src/components/signal-field/field';

// Derived from filtered 8-channel forearm bracelet recordings, point sampled at
// 120 Hz, then circularly interpolated. These are aggregates, never samples.
const reference = {
  Rest: {ratio: 1.0, electrode: 0.1051, neighbour: 0.982, p99: 2.6214, p999: 3.6242, lag1: -0.1618, kurtosis: 3.1675},
  Fist: {ratio: 26.1249, electrode: 0.4088, neighbour: 0.987, p99: 3.0616, p999: 4.6701, lag1: -0.1412, kurtosis: 5.0896},
  Pinch: {ratio: 15.8912, electrode: 0.354, neighbour: 0.9828, p99: 3.0687, p999: 4.1582, lag1: -0.2157, kurtosis: 4.4205},
  Index: {ratio: 9.5577, electrode: 0.3667, neighbour: 0.9845, p99: 3.0989, p999: 4.5391, lag1: -0.1253, kurtosis: 5.0658},
};

function correlation(a: Float32Array, b: Float32Array, lag = 0) {
  const n = a.length - lag;
  let x = 0, y = 0, xx = 0, yy = 0, xy = 0;
  for (let i = 0; i < n; i++) {
    const av = a[i], bv = b[i + lag];
    x += av; y += bv; xx += av * av; yy += bv * bv; xy += av * bv;
  }
  return (xy - x * y / n) / Math.sqrt((xx - x * x / n) * (yy - y * y / n));
}

function statistics(gesture: Gesture) {
  const s = createFieldState(64, 24000), rand = mulberry32(314159);
  setGesture(s, gesture);
  stepField(s, 2400, rand);
  stepField(s, s.samples, rand);
  const rows = Array.from({ length: 64 }, (_, c) => s.data.slice(c * s.samples, (c + 1) * s.samples));
  const rms = rows.map(row => Math.sqrt(row.reduce((sum, v) => sum + v * v, 0) / row.length));
  const z = Array.from(s.data, (v, i) => Math.abs(v) / rms[Math.floor(i / s.samples)]).sort((a, b) => a - b);
  return {
    rms: Math.sqrt(rms.reduce((sum, v) => sum + v * v, 0) / 64),
    neighbour: rows.reduce((sum, row, c) => sum + correlation(row, rows[(c + 1) % 64]), 0) / 64,
    electrode: Array.from({ length: 8 }, (_, c) => correlation(rows[c * 8], rows[((c + 1) % 8) * 8])).reduce((a, b) => a + b) / 8,
    p99: z[Math.floor(z.length * 0.99)], p999: z[Math.floor(z.length * 0.999)],
    lag1: rows.reduce((sum, row) => sum + correlation(row, row, 1), 0) / 64,
    kurtosis: z.reduce((sum, v) => sum + v ** 4, 0) / z.length,
  };
}

it('matches bracelet contrast, circular spatial correlation and sampled amplitude distributions', () => {
  const measured = Object.fromEntries(GESTURES.map(g => [g, statistics(g)])) as Record<Gesture, ReturnType<typeof statistics>>;
  console.info('Matched field statistics', JSON.stringify(measured));
  for (const gesture of GESTURES) {
    const real = reference[gesture], synthetic = measured[gesture];
    expect(Math.abs(synthetic.rms / measured.Rest.rms / real.ratio - 1), `${gesture} rest/active ratio`).toBeLessThanOrEqual(0.2);
    expect(Math.abs(synthetic.neighbour - real.neighbour), `${gesture} lane neighbours`).toBeLessThanOrEqual(0.1);
    expect(Math.abs(synthetic.electrode - real.electrode), `${gesture} electrode neighbours`).toBeLessThanOrEqual(0.1);
    expect(Math.abs(synthetic.lag1 - real.lag1), `${gesture} lag-1`).toBeLessThanOrEqual(0.1);
    expect(Math.abs(synthetic.p99 / real.p99 - 1), `${gesture} p99`).toBeLessThanOrEqual(0.1);
    expect(Math.abs(synthetic.p999 / real.p999 - 1), `${gesture} p99.9`).toBeLessThanOrEqual(0.15);
    expect(Math.abs(synthetic.kurtosis / real.kurtosis - 1), `${gesture} kurtosis`).toBeLessThanOrEqual(0.25);
  }
});

it('keeps all four circular maps distinct by at least 0.18 normalized RMS', () => {
  const maps = GESTURES.map(g => { const s = createFieldState(); setGesture(s, g); return s.target; });
  for (let a = 0; a < maps.length; a++) for (let b = a + 1; b < maps.length; b++) {
    const distance = Math.sqrt(maps[a].reduce((sum, v, c) => sum + (v - maps[b][c]) ** 2, 0) / 64);
    expect(distance, `${GESTURES[a]} / ${GESTURES[b]}`).toBeGreaterThanOrEqual(0.18);
  }
});
