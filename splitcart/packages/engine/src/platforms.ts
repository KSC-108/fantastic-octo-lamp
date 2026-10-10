import type { PlatformRules } from './types.ts';

export const PLATFORM_NAMES: Record<string, string> = {
  blinkit: 'Blinkit',
  zepto: 'Zepto',
  instamart: 'Swiggy Instamart',
  minutes: 'Flipkart Minutes',
  'amazon-now': 'Amazon Now',
};

/** Maps names as people write them ("Swiggy Instamart", "Flipkart Minutes") to platform ids. */
export function platformId(name: string): string {
  const n = name.toLowerCase().replace(/[^a-z]/g, '');
  if (n.includes('blinkit')) return 'blinkit';
  if (n.includes('zepto')) return 'zepto';
  if (n.includes('instamart') || n === 'swiggy') return 'instamart';
  if (n.includes('minutes') || n === 'flipkart') return 'minutes';
  if (n.includes('amazon')) return 'amazon-now';
  return n;
}

const SOURCE = 'Indicative, from public reports summarised on 9 Oct 2026. Replace with what your app shows at 400068.';

/**
 * Starting fee rules. These are not verified: the plan document lists conflicting reports.
 * Amazon Now values are placeholders because no current public figure was found.
 */
export const DEFAULT_RULES: PlatformRules[] = [
  { platform: 'blinkit', name: 'Blinkit', minOrderValue: 0, deliveryFee: [{ below: 199, fee: 30 }], smallCartFee: [{ below: 99, fee: 15 }], handlingFee: 9, platformFee: 0, surgeFee: 0, coupons: [], asOf: '2026-10-09', source: SOURCE },
  { platform: 'zepto', name: 'Zepto', minOrderValue: 0, deliveryFee: [{ below: 199, fee: 30 }], smallCartFee: [], handlingFee: 0, platformFee: 0, surgeFee: 0, coupons: [], asOf: '2026-10-09', source: SOURCE },
  { platform: 'instamart', name: 'Swiggy Instamart', minOrderValue: 0, deliveryFee: [{ below: 199, fee: 30 }], smallCartFee: [], handlingFee: 10, platformFee: 5, surgeFee: 0, coupons: [], asOf: '2026-10-09', source: SOURCE },
  { platform: 'minutes', name: 'Flipkart Minutes', minOrderValue: 0, deliveryFee: [{ below: 99, fee: 30 }], smallCartFee: [], handlingFee: 0, platformFee: 5, surgeFee: 0, coupons: [], asOf: '2026-10-09', source: SOURCE },
  { platform: 'amazon-now', name: 'Amazon Now', minOrderValue: 0, deliveryFee: [{ below: 199, fee: 30 }], smallCartFee: [], handlingFee: 0, platformFee: 0, surgeFee: 0, coupons: [], asOf: '2026-10-09', source: 'Placeholder: no current public figure found. Enter what your app shows.' },
];
