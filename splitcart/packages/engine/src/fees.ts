import type { Coupon, FeeBreakdown, FeeTier, PlatformRules } from './types.ts';
import { round } from './units.ts';

/** Fee for a subtotal under a tier schedule: the first tier whose `below` exceeds the subtotal. */
export function tierFee(tiers: FeeTier[], subtotal: number): number {
  const sorted = sortTiers(tiers);
  for (const t of sorted) if (subtotal < t.below) return t.fee;
  return 0;
}

export function sortTiers(tiers: FeeTier[]): FeeTier[] {
  return [...tiers].filter((t) => t.fee > 0 && t.below > 0).sort((a, b) => a.below - b.below);
}

/** Throws when a schedule cannot be modelled: fees must not rise as the threshold rises. */
export function validateRules(rules: PlatformRules): string[] {
  const problems: string[] = [];
  for (const [label, tiers] of [['delivery', rules.deliveryFee], ['small-cart', rules.smallCartFee]] as const) {
    const sorted = sortTiers(tiers);
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i]!.fee > sorted[i - 1]!.fee) {
        problems.push(`${rules.name}: ${label} fee rises from Rs ${sorted[i - 1]!.fee} to Rs ${sorted[i]!.fee} as the cart grows`);
      }
    }
  }
  for (const c of rules.coupons) {
    if (c.kind === 'percent' && (c.value <= 0 || c.value > 100)) problems.push(`${rules.name}: coupon ${c.label} has an invalid percent`);
  }
  return problems;
}

export function couponValue(coupon: Coupon, subtotal: number): number {
  if (subtotal < coupon.minSpend) return 0;
  if (coupon.kind === 'flat') return Math.min(coupon.value, subtotal);
  const raw = (coupon.value / 100) * subtotal;
  return coupon.cap !== undefined ? Math.min(raw, coupon.cap) : raw;
}

export function bestCoupon(coupons: Coupon[], subtotal: number): { coupon: Coupon; amount: number } | null {
  let best: { coupon: Coupon; amount: number } | null = null;
  for (const c of coupons) {
    const amount = couponValue(c, subtotal);
    if (amount > 0 && (!best || amount > best.amount)) best = { coupon: c, amount };
  }
  return best;
}

/** Landed cost of one order on one platform. The optimiser's model must agree with this function. */
export function orderCost(rules: PlatformRules, subtotal: number) {
  const fees: FeeBreakdown = {
    delivery: tierFee(rules.deliveryFee, subtotal),
    smallCart: tierFee(rules.smallCartFee, subtotal),
    handling: rules.handlingFee,
    platform: rules.platformFee,
    surge: rules.surgeFee,
  };
  const feeTotal = fees.delivery + fees.smallCart + fees.handling + fees.platform + fees.surge;
  const coupon = bestCoupon(rules.coupons, subtotal);
  const total = round(subtotal + feeTotal - (coupon?.amount ?? 0));
  return { fees, feeTotal: round(feeTotal), coupon, total, belowMinimum: subtotal < rules.minOrderValue };
}
