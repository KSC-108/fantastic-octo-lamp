import type { Basket, Listing, ListLine, Unit } from './types.ts';
import { DEFAULT_RULES } from './platforms.ts';

/**
 * A made-up weekly basket of about Rs 2,000 for demonstrating the app.
 * Brands are fictional and every price is invented; nothing here is a real quote.
 */
interface SampleProduct {
  key: string;
  title: string;
  brand?: string;
  pack: number;
  price: number;
  rating?: number;
  ratingCount?: number;
  /** Platforms that do not stock it. */
  missing?: string[];
  /** Fixed prices on specific platforms (discounts), overriding the generated variation. */
  fixed?: Record<string, number>;
}

interface SampleLine {
  id: string;
  name: string;
  quantity: number;
  unit: Unit;
  flexible: boolean;
  pinnedBrand?: string;
  products: SampleProduct[];
}

const LINES: SampleLine[] = [
  { id: 'milk', name: 'Toned milk', quantity: 3000, unit: 'ml', flexible: true, products: [
    { key: 'df-milk', title: 'Dairyfields Toned Milk', brand: 'Dairyfields', pack: 1000, price: 56, rating: 4.3, ratingCount: 12000 },
    { key: 'gf-a2-milk', title: 'Gauri Farms A2 Cow Milk', brand: 'Gauri Farms', pack: 1000, price: 84, rating: 4.6, ratingCount: 3100, missing: ['minutes'] },
  ] },
  { id: 'paneer', name: 'Paneer', quantity: 200, unit: 'g', flexible: true, products: [
    { key: 'df-paneer', title: 'Dairyfields Paneer', brand: 'Dairyfields', pack: 200, price: 90, rating: 4.2, ratingCount: 8000 },
    { key: 'gf-paneer', title: 'Gauri Farms Fresh Malai Paneer', brand: 'Gauri Farms', pack: 200, price: 96, rating: 4.5, ratingCount: 2100, fixed: { zepto: 89 } },
    { key: 'fl-paneer', title: 'Frostline Frozen Paneer Cubes', brand: 'Frostline', pack: 200, price: 80, rating: 3.9, ratingCount: 600, missing: ['zepto', 'amazon-now'] },
  ] },
  { id: 'curd', name: 'Curd', quantity: 400, unit: 'g', flexible: true, products: [
    { key: 'df-curd', title: 'Dairyfields Dahi', brand: 'Dairyfields', pack: 400, price: 35, rating: 4.3, ratingCount: 9000 },
    { key: 'gf-curd', title: 'Gauri Farms A2 Dahi', brand: 'Gauri Farms', pack: 400, price: 62, rating: 4.5, ratingCount: 900, missing: ['blinkit'] },
  ] },
  { id: 'oil', name: 'Cooking oil', quantity: 1000, unit: 'ml', flexible: true, products: [
    { key: 'sf-oil', title: 'Sunfarm Refined Sunflower Oil', brand: 'Sunfarm', pack: 1000, price: 155, rating: 4.3, ratingCount: 21000 },
    { key: 'gh-oil', title: 'Ghanihouse Cold Pressed Groundnut Oil', brand: 'Ghanihouse', pack: 1000, price: 182, rating: 4.5, ratingCount: 4200, fixed: { instamart: 158 } },
    { key: 'kr-oil', title: 'Kisan Roots Wood Pressed Mustard Oil', brand: 'Kisan Roots', pack: 1000, price: 194, rating: 4.4, ratingCount: 1300, missing: ['minutes', 'blinkit'] },
  ] },
  { id: 'atta', name: 'Atta', quantity: 5000, unit: 'g', flexible: true, products: [
    { key: 'an-atta', title: 'Annapurni Whole Wheat Atta', brand: 'Annapurni', pack: 5000, price: 245, rating: 4.4, ratingCount: 30000 },
    { key: 'kr-atta', title: 'Kisan Roots Organic Chakki Atta', brand: 'Kisan Roots', pack: 5000, price: 330, rating: 4.5, ratingCount: 2500, missing: ['minutes'] },
    { key: 'mc-atta', title: 'Millet and Co Multigrain Atta', brand: 'Millet and Co', pack: 5000, price: 289, rating: 4.2, ratingCount: 1800, missing: ['amazon-now'] },
  ] },
  { id: 'rice', name: 'Basmati rice', quantity: 1000, unit: 'g', flexible: true, products: [
    { key: 'rg-rice', title: 'Royal Grain Basmati Rice', brand: 'Royal Grain', pack: 1000, price: 135, rating: 4.3, ratingCount: 9000 },
    { key: 'kr-rice', title: 'Kisan Roots Organic Brown Basmati', brand: 'Kisan Roots', pack: 1000, price: 178, rating: 4.4, ratingCount: 1100, missing: ['zepto'] },
  ] },
  { id: 'dal', name: 'Toor dal', quantity: 1000, unit: 'g', flexible: true, products: [
    { key: 'an-dal', title: 'Annapurni Toor Dal', brand: 'Annapurni', pack: 1000, price: 165, rating: 4.3, ratingCount: 14000 },
    { key: 'kr-dal', title: 'Kisan Roots Organic Unpolished Toor Dal', brand: 'Kisan Roots', pack: 500, price: 104, rating: 4.5, ratingCount: 2600, fixed: { 'amazon-now': 92 } },
  ] },
  { id: 'eggs', name: 'Eggs', quantity: 12, unit: 'pc', flexible: true, products: [
    { key: 'hh-eggs', title: 'Henhouse Classic White Eggs', brand: 'Henhouse', pack: 12, price: 86, rating: 4.2, ratingCount: 7000 },
    { key: 'md-eggs', title: 'Meadow Free Range Brown Eggs', brand: 'Meadow', pack: 6, price: 78, rating: 4.6, ratingCount: 2000, missing: ['minutes'] },
  ] },
  { id: 'bread', name: 'Bread', quantity: 1, unit: 'pc', flexible: true, products: [
    { key: 'bw-white', title: 'Bakewell White Bread 400 g', brand: 'Bakewell', pack: 1, price: 45, rating: 4.1, ratingCount: 5000 },
    { key: 'bw-wheat', title: 'Bakewell 100% Whole Wheat Bread 400 g', brand: 'Bakewell', pack: 1, price: 55, rating: 4.4, ratingCount: 3200 },
  ] },
  { id: 'tomato', name: 'Tomatoes', quantity: 1000, unit: 'g', flexible: true, products: [
    { key: 'tomato', title: 'Fresh Tomato (Hybrid)', pack: 500, price: 28, rating: 4.0, ratingCount: 4000 },
    { key: 'ng-tomato', title: 'Naturally Grown Tomato', brand: 'Greenroot', pack: 500, price: 39, rating: 4.3, ratingCount: 700, missing: ['minutes', 'amazon-now'] },
  ] },
  { id: 'onion', name: 'Onions', quantity: 2000, unit: 'g', flexible: true, products: [
    { key: 'onion', title: 'Onion', pack: 1000, price: 38, rating: 4.1, ratingCount: 9000 },
  ] },
  { id: 'banana', name: 'Bananas', quantity: 6, unit: 'pc', flexible: true, products: [
    { key: 'banana', title: 'Robusta Banana', pack: 6, price: 48, rating: 4.0, ratingCount: 6000 },
    { key: 'org-banana', title: 'Organic Yelakki Banana', brand: 'Greenroot', pack: 6, price: 66, rating: 4.4, ratingCount: 800, missing: ['zepto'] },
  ] },
  { id: 'tea', name: 'Tea', quantity: 250, unit: 'g', flexible: true, products: [
    { key: 'hc-tea', title: 'Hillcrest Classic Tea', brand: 'Hillcrest', pack: 250, price: 120, rating: 4.3, ratingCount: 11000 },
    { key: 'hc-premium', title: 'Hillcrest Premium Assam Tea', brand: 'Hillcrest', pack: 250, price: 148, rating: 4.5, ratingCount: 3000 },
  ] },
  { id: 'dishwash', name: 'Dishwash gel', quantity: 500, unit: 'ml', flexible: true, products: [
    { key: 'sp-dish', title: 'Sparkle Dishwash Gel', brand: 'Sparkle', pack: 500, price: 105, rating: 4.3, ratingCount: 16000 },
    { key: 'en-dish', title: 'EcoNest Plant-based Dishwash Liquid', brand: 'EcoNest', pack: 500, price: 149, rating: 4.4, ratingCount: 900, missing: ['minutes', 'blinkit'] },
  ] },
  { id: 'detergent', name: 'Detergent powder', quantity: 1000, unit: 'g', flexible: true, products: [
    { key: 'bw-det', title: 'Brightwash Detergent Powder', brand: 'Brightwash', pack: 1000, price: 122, rating: 4.2, ratingCount: 8000 },
  ] },
  { id: 'butter', name: 'Butter', quantity: 100, unit: 'g', flexible: false, pinnedBrand: 'Dairyfields', products: [
    { key: 'df-butter', title: 'Dairyfields Salted Butter', brand: 'Dairyfields', pack: 100, price: 58, rating: 4.6, ratingCount: 25000 },
  ] },
  { id: 'honey', name: 'Honey', quantity: 500, unit: 'g', flexible: true, products: [
    { key: 'bv-honey', title: 'Beevalley Honey', brand: 'Beevalley', pack: 500, price: 199, rating: 4.2, ratingCount: 6000 },
    { key: 'bv-raw', title: 'Beevalley Raw Organic Honey', brand: 'Beevalley', pack: 500, price: 265, rating: 4.4, ratingCount: 1200, missing: ['minutes'] },
  ] },
];

const PLATFORMS = ['blinkit', 'zepto', 'instamart', 'minutes', 'amazon-now'];

/** Small deterministic PRNG (mulberry32) so the sample is identical on every load. */
function rng(seed: number) {
  let a = seed;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let x = Math.imul(a ^ (a >>> 15), 1 | a);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

export function sampleBasket(): Basket {
  const rand = rng(400068);
  const lines: ListLine[] = [];
  const listings: Listing[] = [];
  for (const l of LINES) {
    lines.push({ id: l.id, name: l.name, quantity: l.quantity, unit: l.unit, flexible: l.flexible, ...(l.pinnedBrand ? { pinnedBrand: l.pinnedBrand } : {}) });
    for (const p of l.products) {
      for (const platform of PLATFORMS) {
        const variation = 0.92 + rand() * 0.16; // each platform within +/- 8% of the base price
        const outOfStock = rand() < 0.04;
        if (p.missing?.includes(platform)) continue;
        const price = p.fixed?.[platform] ?? Math.round(p.price * variation);
        listings.push({
          id: `${platform}:${p.key}`,
          lineId: l.id,
          platform,
          title: p.title,
          ...(p.brand ? { brand: p.brand } : {}),
          packSize: p.pack,
          unit: l.unit,
          price,
          mrp: Math.ceil((p.price * 1.1) / 5) * 5,
          ...(p.rating ? { rating: p.rating, ratingCount: p.ratingCount ?? 100 } : {}),
          inStock: !outOfStock,
        });
      }
    }
  }
  return { lines, listings, rules: structuredClone(DEFAULT_RULES) };
}
