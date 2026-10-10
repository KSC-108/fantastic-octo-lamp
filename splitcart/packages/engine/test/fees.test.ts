import { describe, expect, it } from 'vitest';
import { orderCost, validateRules, type PlatformRules } from '../src/index.ts';

const rules: PlatformRules = {
  platform: 'p', name: 'P', minOrderValue: 0,
  deliveryFee: [{ below: 199, fee: 30 }, { below: 99, fee: 50 }],
  smallCartFee: [{ below: 100, fee: 15 }],
  handlingFee: 9, platformFee: 2, surgeFee: 0,
  coupons: [
    { id: 'flat', label: 'Rs 40 off over Rs 800', minSpend: 800, kind: 'flat', value: 40 },
    { id: 'pct', label: '10% up to Rs 60', minSpend: 500, kind: 'percent', value: 10, cap: 60 },
  ],
};

describe('fees', () => {
  it('applies stepped fees and the best coupon', () => {
    expect(orderCost(rules, 80).total).toBe(80 + 50 + 15 + 11);
    expect(orderCost(rules, 150).total).toBe(150 + 30 + 11);
    expect(orderCost(rules, 600).total).toBe(600 + 11 - 60);
    expect(orderCost(rules, 900).coupon?.amount).toBe(60);
  });

  it('rejects fee schedules that rise with the cart', () => {
    expect(validateRules({ ...rules, deliveryFee: [{ below: 99, fee: 10 }, { below: 199, fee: 30 }] })).toHaveLength(1);
    expect(validateRules(rules)).toHaveLength(0);
  });
});
