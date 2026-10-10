/** Platform identifiers. Free-form so tests and imports can add platforms. */
export type PlatformId = string;

/** Base units: grams, millilitres, pieces. */
export type Unit = 'g' | 'ml' | 'pc';

/** A fee that applies while the order subtotal is below `below` (rupees). */
export interface FeeTier {
  below: number;
  fee: number;
}

/** A platform coupon visible in the cart before payment. Payment-method offers are out of scope. */
export interface Coupon {
  id: string;
  label: string;
  minSpend: number;
  kind: 'flat' | 'percent';
  /** Rupees for `flat`, percent (0-100) for `percent`. */
  value: number;
  /** Maximum discount in rupees for `percent` coupons. */
  cap?: number;
}

export interface PlatformRules {
  platform: PlatformId;
  name: string;
  /** Hard minimum: checkout is blocked below it. */
  minOrderValue: number;
  /** Soft thresholds: delivery fee tiers, fees must not rise as the threshold rises. */
  deliveryFee: FeeTier[];
  smallCartFee: FeeTier[];
  handlingFee: number;
  platformFee: number;
  surgeFee: number;
  coupons: Coupon[];
  asOf?: string;
  source?: string;
}

/** One line of the shopping list. */
export interface ListLine {
  id: string;
  name: string;
  quantity: number;
  unit: Unit;
  /** Any brand is acceptable. */
  flexible: boolean;
  /** When set, only listings of this brand are acceptable. */
  pinnedBrand?: string;
}

/** A product as listed on one platform. */
export interface Listing {
  id: string;
  lineId: string;
  platform: PlatformId;
  title: string;
  brand?: string;
  packSize: number;
  unit: Unit;
  price: number;
  mrp?: number;
  rating?: number;
  ratingCount?: number;
  inStock: boolean;
  /** Extra tags such as "organic" or "cold pressed", in addition to the title. */
  attributes?: string[];
}

export interface TraitRule {
  id: string;
  label: string;
  keywords: string[];
  points: number;
}

export type BrandTier = 'premium' | 'standard' | 'value';

export interface Preferences {
  /** Convenience penalty per order, rupees. 0 = as many deliveries as needed. */
  lambda: number;
  /** Upgrade tolerance as a percent of the cheapest basket cost. */
  upgradeTolerancePct: number;
  /** Quality points an alternative must add before it counts as an upgrade. */
  minQualityGain: number;
  /** Optional cap on the number of orders. */
  maxOrders?: number;
  excludedPlatforms?: PlatformId[];
  /** Lower-case brand name to tier. */
  brandTiers?: Record<string, BrandTier>;
  usualPlatform?: PlatformId;
  traits?: TraitRule[];
  /** Set false to skip the upgrade stage entirely. */
  upgradesEnabled?: boolean;
}

export interface QualityScore {
  score: number;
  traits: number;
  rating: number;
  brand: number;
  reasons: string[];
}

export interface Candidate {
  index: number;
  line: ListLine;
  listing: Listing;
  packs: number;
  cost: number;
  quality: QualityScore;
}

export interface FeeBreakdown {
  delivery: number;
  smallCart: number;
  handling: number;
  platform: number;
  surge: number;
}

export interface OrderItem {
  line: ListLine;
  listing: Listing;
  packs: number;
  cost: number;
  quality: QualityScore;
  upgraded: boolean;
}

export interface Order {
  platform: PlatformId;
  name: string;
  items: OrderItem[];
  subtotal: number;
  fees: FeeBreakdown;
  feeTotal: number;
  coupon: { id: string; label: string; amount: number } | null;
  total: number;
  /** True when the subtotal is below the platform's hard minimum (should not happen in a solved plan). */
  belowMinimum: boolean;
}

export interface Totals {
  items: number;
  fees: number;
  coupons: number;
  total: number;
}

export interface Baseline {
  platform: PlatformId;
  name: string;
  feasible: boolean;
  missing: string[];
  totals: Totals | null;
}

export interface Upgrade {
  line: ListLine;
  from: OrderItem;
  to: OrderItem;
  itemCostChange: number;
  qualityGain: number;
}

export interface OptionalUpgrade {
  line: ListLine;
  current: OrderItem;
  alternative: { listing: Listing; packs: number; cost: number; quality: QualityScore };
  itemCostChange: number;
  qualityGain: number;
}

export interface PlanResult {
  orders: Order[];
  totals: Totals;
  /** Cheapest plan before upgrades. */
  cheapestTotals: Totals;
  cheapestOrderCount: number;
  tolerance: number;
  upgradeSpend: number;
  upgrades: Upgrade[];
  optionalUpgrades: OptionalUpgrade[];
  baselines: Baseline[];
  bestSingle: Baseline | null;
  usual: Baseline | null;
  savings: {
    /** Cheapest split versus best single platform, before upgrades. */
    split: number | null;
    breakdown: { items: number; fees: number; coupons: number } | null;
    /** Best single platform minus final total, after upgrade spend. */
    net: number | null;
    vsUsual: number | null;
  };
  unfulfilled: ListLine[];
  solveMs: number;
}

export interface Basket {
  lines: ListLine[];
  listings: Listing[];
  rules: PlatformRules[];
}
