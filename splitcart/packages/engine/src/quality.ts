import type { BrandTier, Listing, Preferences, QualityScore, TraitRule } from './types.ts';

/**
 * Default quality ladder. It reflects the stated preference for premium, organic,
 * pesticide-free, cold-pressed and more nutritious products. Points are a starting
 * assumption; every rule is editable in the app.
 */
export const DEFAULT_TRAITS: TraitRule[] = [
  { id: 'organic', label: 'Organic', keywords: ['organic', 'certified organic'], points: 25 },
  { id: 'cold-pressed', label: 'Cold-pressed', keywords: ['cold pressed', 'wood pressed', 'kachi ghani', 'kachchi ghani', 'kolhu', 'chekku'], points: 25 },
  { id: 'pesticide-free', label: 'Pesticide-free', keywords: ['pesticide free', 'residue free', 'chemical free', 'natural farming', 'naturally grown'], points: 20 },
  { id: 'a2', label: 'A2', keywords: ['a2'], points: 20 },
  { id: 'grass-fed', label: 'Grass-fed or free-range', keywords: ['grass fed', 'free range', 'pasture raised'], points: 15 },
  { id: 'nutritious', label: 'More nutritious', keywords: ['whole wheat', 'whole grain', 'wholegrain', 'multigrain', 'millet', 'high protein', 'high fibre', 'high fiber', 'unpolished', 'sprouted', 'fortified'], points: 10 },
  { id: 'premium', label: 'Premium', keywords: ['premium', 'gourmet', 'artisanal', 'handmade', 'small batch'], points: 10 },
  { id: 'clean-label', label: 'No additives', keywords: ['no added sugar', 'no preservatives', 'preservative free', 'no maida'], points: 8 },
  { id: 'fresh', label: 'Fresh', keywords: ['fresh', 'malai'], points: 5 },
  { id: 'frozen', label: 'Frozen', keywords: ['frozen'], points: -10 },
  { id: 'palm', label: 'Palm oil', keywords: ['palm', 'palmolein'], points: -10 },
];

const TRAIT_CAP = 60;
const RATING_MAX = 20;
const BRAND_MAX = 20;
const TIER_POINTS: Record<BrandTier, number> = { premium: 20, standard: 10, value: 0 };

export function normalise(text: string): string {
  return ` ${text.toLowerCase().replace(/[-_/]+/g, ' ').replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim()} `;
}

/** Scores a listing from 0 to 100: traits up to 60, rating up to 20, brand tier up to 20. */
export function scoreListing(listing: Listing, prefs: Pick<Preferences, 'traits' | 'brandTiers'>): QualityScore {
  const traits = prefs.traits ?? DEFAULT_TRAITS;
  const text = normalise([listing.title, ...(listing.attributes ?? [])].join(' '));
  const reasons: string[] = [];
  let traitPoints = 0;
  for (const rule of traits) {
    if (rule.keywords.some((k) => text.includes(normalise(k)))) {
      traitPoints += rule.points;
      reasons.push(rule.label);
    }
  }
  traitPoints = Math.max(0, Math.min(TRAIT_CAP, traitPoints));

  // Bayesian-adjusted rating, so a 5.0 from 3 ratings does not beat a 4.6 from 2,000.
  let rating = RATING_MAX / 2;
  if (listing.rating !== undefined && listing.rating > 0) {
    const n = listing.ratingCount ?? 20;
    const prior = 4.0;
    const weight = 50;
    const adjusted = (prior * weight + listing.rating * n) / (weight + n);
    rating = clamp((adjusted - 3.5) / (4.8 - 3.5), 0, 1) * RATING_MAX;
    if (adjusted >= 4.4) reasons.push(`Rated ${listing.rating.toFixed(1)}`);
  }

  const tier = listing.brand ? prefs.brandTiers?.[listing.brand.toLowerCase()] : undefined;
  const brand = tier ? TIER_POINTS[tier] : BRAND_MAX / 2;
  if (tier === 'premium') reasons.push('Premium brand');

  const score = Math.round((traitPoints + rating + brand) * 10) / 10;
  return { score, traits: traitPoints, rating: Math.round(rating * 10) / 10, brand, reasons };
}

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n));
}
