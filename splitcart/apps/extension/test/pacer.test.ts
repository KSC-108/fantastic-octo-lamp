import { describe, expect, it } from 'vitest';
import { DEFAULT_PACER, Pacer, PacerStopped } from '../src/pacer.ts';
import { assertAllowedAction, assertSafeUrl, looksLikeChallenge } from '../src/guardrails.ts';
import { fillCarts } from '../src/fill.ts';

/** Deterministic random source and a sleep that only records the requested waits. */
function harness(seed = 1) {
  let s = seed;
  const random = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  const waits: number[] = [];
  const sleep = async (ms: number, signal: AbortSignal) => {
    if (signal.aborted) throw new PacerStopped('Stopped');
    waits.push(ms);
  };
  return { random, sleep, waits };
}

describe('pacer', () => {
  it('keeps pauses within bounds and centred near the median', async () => {
    const h = harness(42);
    const pacer = new Pacer({ ...DEFAULT_PACER, breakEvery: [1000, 1000], maxActionsPerSession: 1000 }, h.random, h.sleep);
    for (let i = 0; i < 400; i++) await pacer.run('add', async () => i);
    expect(Math.min(...h.waits)).toBeGreaterThanOrEqual(DEFAULT_PACER.minGapMs);
    expect(Math.max(...h.waits)).toBeLessThanOrEqual(DEFAULT_PACER.maxGapMs);
    const sorted = [...h.waits].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)]!;
    expect(median).toBeGreaterThan(DEFAULT_PACER.addMedianMs * 0.8);
    expect(median).toBeLessThan(DEFAULT_PACER.addMedianMs * 1.2);
  });

  it('takes longer breaks periodically', async () => {
    const h = harness(7);
    const pacer = new Pacer(DEFAULT_PACER, h.random, h.sleep);
    for (let i = 0; i < 30; i++) await pacer.run('browse', async () => i);
    expect(h.waits.filter((w) => w >= DEFAULT_PACER.breakMs[0]).length).toBeGreaterThanOrEqual(2);
  });

  it('runs actions one at a time, in order', async () => {
    const h = harness(3);
    const pacer = new Pacer(DEFAULT_PACER, h.random, h.sleep);
    const order: number[] = [];
    let running = 0;
    await Promise.all([1, 2, 3, 4].map((n) => pacer.run('add', async () => {
      running += 1;
      expect(running).toBe(1);
      order.push(n);
      running -= 1;
    })));
    expect(order).toEqual([1, 2, 3, 4]);
  });

  it('stops on request and enforces the session cap', async () => {
    const h = harness(5);
    const capped = new Pacer({ ...DEFAULT_PACER, maxActionsPerSession: 2 }, h.random, h.sleep);
    await capped.run('add', async () => 1);
    await capped.run('add', async () => 2);
    await expect(capped.run('add', async () => 3)).rejects.toThrow(/Session limit/);
    const stopped = new Pacer(DEFAULT_PACER, h.random, h.sleep);
    stopped.stop();
    await expect(stopped.run('add', async () => 1)).rejects.toBeInstanceOf(PacerStopped);
  });
});

describe('guardrails', () => {
  it('never allows payment or checkout', () => {
    expect(() => assertAllowedAction('add-to-cart')).not.toThrow();
    expect(() => assertAllowedAction('place-order')).toThrow(/never pays/);
    expect(() => assertSafeUrl('https://example.com/checkout')).toThrow();
    expect(() => assertSafeUrl('https://example.com/payment/upi')).toThrow();
    expect(() => assertSafeUrl('https://example.com/product/cupid-cake')).not.toThrow();
    expect(looksLikeChallenge('Please verify you are human')).toBe(true);
  });

  it('falls back to the checklist while adapters are pending', async () => {
    const h = harness(9);
    const reports = await fillCarts(
      [{ platform: 'zepto', items: [{ title: 'Paneer', packSize: '200 g', packs: 1 }] }],
      new Pacer(DEFAULT_PACER, h.random, h.sleep),
      async () => 1,
    );
    expect(reports[0]).toMatchObject({ platform: 'zepto', status: 'adapter-pending' });
    expect(h.waits).toHaveLength(0);
  });
});
