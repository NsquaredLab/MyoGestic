import { describe, expect, it } from 'vitest';
import { channelColor, CONFIDENCE, createFieldState, GESTURES, mulberry32, setGesture, stepField } from './field';

describe('synthetic signal field', () => {
  it('exposes the approved gestures and confidences', () => {
    expect(GESTURES).toEqual(['Rest', 'Fist', 'Open', 'Pinch']);
    expect(CONFIDENCE).toEqual({ Rest: 0.97, Fist: 0.94, Open: 0.91, Pinch: 0.88 });
    expect(createFieldState().data.length).toBe(30720);
  });

  it('fills the approved spatial patterns in place', () => {
    const s = createFieldState();
    const target = s.target;
    setGesture(s, 'Fist');
    expect(s.target[0]).toBe(1);
    expect(s.target[21]).toBeCloseTo(0.789);
    expect(s.target[63]).toBeCloseTo(0.787);
    setGesture(s, 'Open');
    expect(s.target[44]).toBeGreaterThan(0.77);
    setGesture(s, 'Pinch');
    expect(s.target[16]).toBeGreaterThan(0.78);
    setGesture(s, 'Rest');
    expect(s.target[0]).toBeCloseTo(0.136);
    expect(s.target[63]).toBeCloseTo(0.089);
    expect(s.target).toBe(target);
    expect(s.gesture).toBe('Rest');
  });

  it('wraps without replacing any storage and reproduces seeded samples', () => {
    const a = createFieldState();
    const b = createFieldState();
    const data = a.data, act = a.act, target = a.target;
    const phase = a.phase, pulse = a.pulse, rest = a.rest;
    const randA = mulberry32(17), randB = mulberry32(17);
    setGesture(a, 'Fist');
    setGesture(b, 'Fist');
    for (let i = 0; i < 1000; i++) {
      stepField(a, 7, randA);
      stepField(b, 7, randB);
    }
    expect(a.head).toBe(7000 % 480);
    expect(a.data).toBe(data);
    expect(a.act).toBe(act);
    expect(a.target).toBe(target);
    expect(a.phase).toBe(phase);
    expect(a.pulse).toBe(pulse);
    expect(a.rest).toBe(rest);
    expect(a.data).toEqual(b.data);
    expect(a.act).toEqual(b.act);
  });

  it('eases RMS using the measured 18 ms onset and 18 ms offset constants', () => {
    const s = createFieldState(1, 8);
    setGesture(s, 'Fist');
    const before = s.act[0];
    stepField(s, 1, () => 0.5);
    expect(s.act[0]).toBeCloseTo(before + (s.target[0] - before) * (1 - Math.exp(-1 / (120 * 0.018))));
    setGesture(s, 'Rest');
    const active = s.act[0];
    stepField(s, 1, () => 0.5);
    expect(s.act[0]).toBeCloseTo(active + (s.target[0] - active) * (1 - Math.exp(-1 / (120 * 0.018))));
    expect(Number.isFinite(s.data[0])).toBe(true);
  });

  it('keeps the reference Mulberry32 sequence when storing its seed in place', () => {
    const rand = mulberry32(1);
    expect([rand(), rand(), rand(), rand()]).toEqual([
      0.6270739405881613, 0.002735721180215478, 0.5274470399599522, 0.9810509674716741,
    ]);
  });

  it('interpolates through all three brand colours', () => {
    expect(channelColor(0)).toEqual([107, 165, 219]);
    expect(channelColor(0.5)).toEqual([142, 149, 218]);
    expect(channelColor(1)).toEqual([177, 132, 217]);
    expect(channelColor(0.25)).toEqual([125, 157, 219]);
  });
});
