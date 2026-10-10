import { describe, expect, it } from 'vitest';
import { optimise, type Basket, type Listing, type PlatformRules } from '../src/index.ts';
import { getSolver } from './helpers.ts';

/** The Rs 2,000 worked example from the plan document (hypothetical prices). */
const prices: Record<string, Record<string, number>> = {
  staples: { X: 900, Y: 870, Z: 910 },
  dairy: { X: 410, Y: 400, Z: 380 },
  fresh: { X: 340, Y: 370, Z: 360 },
  household: { X: 380, Y: 350, Z: 345 },
};
const free = [{ below: 199, fee: 30 }];
const rule = (platform: string, handlingFee: number, coupons: PlatformRules['coupons'] = []): PlatformRules => ({
  platform, name: platform, minOrderValue: 0, deliveryFee: free, smallCartFee: [], handlingFee, platformFee: 0, surgeFee: 0, coupons,
});

const basket: Basket = {
  lines: Object.keys(prices).map((id) => ({ id, name: id, quantity: 1, unit: 'pc' as const, flexible: true })),
  listings: Object.entries(prices).flatMap(([lineId, byPlatform]) =>
    Object.entries(byPlatform).map(([platform, price]): Listing => ({
      id: `${platform}-${lineId}`, lineId, platform, title: lineId, packSize: 1, unit: 'pc', price, inStock: true,
    }))),
  rules: [rule('X', 12), rule('Y', 5, [{ id: 'c', label: 'Rs 40 off', minSpend: 800, kind: 'flat', value: 40 }]), rule('Z', 10)],
};

describe('worked example', () => {
  it('splits across three platforms when deliveries are free of penalty', async () => {
    const plan = optimise(basket, { lambda: 0, upgradesEnabled: false }, await getSolver());
    expect(plan.totals.total).toBe(1922);
    expect(plan.orders).toHaveLength(3);
    expect(plan.bestSingle?.platform).toBe('Y');
    expect(plan.bestSingle?.totals?.total).toBe(1955);
    expect(plan.savings.split).toBe(33);
  });

  it('switches to two platforms when each order carries a penalty above Rs 8', async () => {
    const plan = optimise(basket, { lambda: 10, upgradesEnabled: false }, await getSolver());
    expect(plan.totals.total).toBe(1930);
    expect(plan.orders.map((o) => o.platform).sort()).toEqual(['Y', 'Z']);
  });

  it('honours a cap on the number of orders', async () => {
    const plan = optimise(basket, { lambda: 0, maxOrders: 1, upgradesEnabled: false }, await getSolver());
    expect(plan.totals.total).toBe(1955);
  });
});
