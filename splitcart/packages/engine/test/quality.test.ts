import { describe, expect, it } from 'vitest';
import { scoreListing, type Listing } from '../src/index.ts';

const listing = (title: string, extra: Partial<Listing> = {}): Listing => ({
  id: title, lineId: 'x', platform: 'p', title, packSize: 1, unit: 'pc', price: 10, inStock: true, ...extra,
});

describe('quality', () => {
  it('prefers cold-pressed, organic and pesticide-free products', () => {
    const refined = scoreListing(listing('Refined Sunflower Oil'), {});
    const cold = scoreListing(listing('Cold-Pressed Groundnut Oil'), {});
    const organic = scoreListing(listing('Organic Toor Dal', { attributes: ['pesticide free'] }), {});
    expect(cold.score).toBeGreaterThan(refined.score + 20);
    expect(organic.traits).toBe(45);
    expect(cold.reasons).toContain('Cold-pressed');
  });

  it('penalises frozen and adjusts ratings for few reviews', () => {
    const frozen = scoreListing(listing('Frozen Paneer'), {});
    const plain = scoreListing(listing('Paneer'), {});
    expect(frozen.traits).toBe(0);
    const fewReviews = scoreListing(listing('Tea', { rating: 5, ratingCount: 3 }), {});
    const manyReviews = scoreListing(listing('Tea', { rating: 4.6, ratingCount: 2000 }), {});
    expect(manyReviews.rating).toBeGreaterThan(fewReviews.rating);
    expect(plain.score).toBeGreaterThanOrEqual(frozen.score);
  });

  it('uses brand tiers', () => {
    const premium = scoreListing(listing('Butter', { brand: 'Gauri Farms' }), { brandTiers: { 'gauri farms': 'premium' } });
    expect(premium.brand).toBe(20);
  });
});
