import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import { buildCandidates, evaluate, optimise, type Basket, type Candidate, type Listing, type PlatformRules } from '../src/index.ts';
import { getSolver } from './helpers.ts';

const PLATFORMS = ['p0', 'p1', 'p2'];
const TITLES = ['Plain', 'Organic', 'Cold Pressed', 'Frozen', 'Premium Whole Wheat', 'Fresh'];

const rulesArb = (platform: string) =>
  fc.record({
    minOrderValue: fc.constantFrom(0, 0, 100, 250),
    deliveryFee: fc.constantFrom([], [{ below: 199, fee: 30 }], [{ below: 99, fee: 40 }, { below: 299, fee: 20 }]),
    smallCartFee: fc.constantFrom([], [{ below: 100, fee: 15 }]),
    handlingFee: fc.integer({ min: 0, max: 12 }),
    platformFee: fc.integer({ min: 0, max: 5 }),
    coupons: fc.constantFrom(
      [],
      [{ id: 'f', label: 'flat', minSpend: 300, kind: 'flat' as const, value: 25 }],
      [{ id: 'p', label: 'pct', minSpend: 200, kind: 'percent' as const, value: 10, cap: 30 }],
    ),
  }).map((r): PlatformRules => ({
    platform, name: platform, surgeFee: 0, ...r,
    deliveryFee: [...r.deliveryFee], smallCartFee: [...r.smallCartFee], coupons: [...r.coupons],
  }));

const basketArb: fc.Arbitrary<Basket> = fc
  .record({
    lineCount: fc.integer({ min: 1, max: 4 }),
    rules: fc.tuple(...PLATFORMS.map(rulesArb)),
    offers: fc.array(
      fc.record({
        line: fc.integer({ min: 0, max: 3 }),
        platform: fc.constantFrom(...PLATFORMS),
        price: fc.integer({ min: 20, max: 400 }),
        title: fc.constantFrom(...TITLES),
        rating: fc.constantFrom(3.8, 4.2, 4.6),
      }),
      { minLength: 1, maxLength: 9 },
    ),
  })
  .map(({ lineCount, rules, offers }) => {
    const lines = Array.from({ length: lineCount }, (_, i) => ({ id: `l${i}`, name: `line ${i}`, quantity: 1, unit: 'pc' as const, flexible: true }));
    const listings: Listing[] = offers
      .filter((o) => o.line < lineCount)
      .map((o, i) => ({
        id: `o${i}`, lineId: `l${o.line}`, platform: o.platform, title: o.title, packSize: 1, unit: 'pc' as const,
        price: o.price, rating: o.rating, ratingCount: 500, inStock: true,
      }));
    return { lines, listings, rules: [...rules] };
  });

/** Enumerates every assignment of one candidate per line and returns the lowest penalised cost. */
function bruteForce(candidates: Candidate[], lineIds: string[], basket: Basket, lambda: number): number | null {
  const rules = new Map(basket.rules.map((r) => [r.platform, r] as const));
  const perLine = lineIds.map((id) => candidates.filter((c) => c.line.id === id));
  let best: number | null = null;
  const pick: Candidate[] = [];
  const walk = (i: number) => {
    if (i === perLine.length) {
      const { orders, totals } = evaluate(pick, rules, new Set());
      if (orders.some((o) => o.belowMinimum)) return;
      const cost = totals.total + lambda * orders.length;
      if (best === null || cost < best) best = cost;
      return;
    }
    for (const c of perLine[i]!) { pick.push(c); walk(i + 1); pick.pop(); }
  };
  walk(0);
  return best;
}

describe('optimiser properties', () => {
  it('matches brute force and never loses to a single platform', async () => {
    const solver = await getSolver();
    fc.assert(
      fc.property(basketArb, fc.constantFrom(0, 7), (basket, lambda) => {
        const prefs = { lambda, upgradeTolerancePct: 5, minQualityGain: 8 };
        const { candidates } = buildCandidates(basket, prefs);
        const lineIds = [...new Set(candidates.map((c) => c.line.id))];
        if (lineIds.length === 0) {
          expect(() => optimise(basket, prefs, solver)).toThrow(/No list line/);
          return;
        }
        const expected = bruteForce(candidates, lineIds, basket, lambda);
        let plan;
        try {
          plan = optimise(basket, prefs, solver);
        } catch {
          expect(expected).toBeNull();
          return;
        }
        expect(expected).not.toBeNull();
        const penalisedCheapest = plan.cheapestTotals.total + lambda * plan.cheapestOrderCount;
        expect(penalisedCheapest).toBeCloseTo(expected!, 2);

        // Upgrades stay within the tolerance and never lower any line's quality.
        expect(plan.totals.total + lambda * plan.orders.length).toBeLessThanOrEqual(expected! + plan.tolerance + 0.01);
        for (const u of plan.upgrades) expect(u.to.quality.score).toBeGreaterThan(u.from.quality.score);

        // With no order penalty, the cheapest split is never worse than any single platform.
        if (lambda === 0) {
          for (const b of plan.baselines) if (b.totals) expect(plan.cheapestTotals.total).toBeLessThanOrEqual(b.totals.total + 0.01);
        }
        for (const o of plan.orders) expect(o.belowMinimum).toBe(false);
      }),
      { numRuns: 60, seed: 400068 },
    );
  }, 60_000);
});

