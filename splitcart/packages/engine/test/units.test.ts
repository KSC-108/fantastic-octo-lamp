import { describe, expect, it } from 'vitest';
import { packsNeeded, parseLineText, parseQuantity } from '../src/index.ts';

describe('units', () => {
  it('parses pack sizes into base units', () => {
    expect(parseQuantity('200 g')).toEqual({ size: 200, unit: 'g' });
    expect(parseQuantity('5kg')).toEqual({ size: 5000, unit: 'g' });
    expect(parseQuantity('1 L')).toEqual({ size: 1000, unit: 'ml' });
    expect(parseQuantity('2 x 500 ml')).toEqual({ size: 1000, unit: 'ml' });
    expect(parseQuantity('12 pcs')).toEqual({ size: 12, unit: 'pc' });
    expect(parseQuantity('a bag')).toBeNull();
  });

  it('parses Phase 0 list lines', () => {
    expect(parseLineText('Paneer 200 g, any brand')).toEqual({ name: 'Paneer', quantity: 200, unit: 'g', flexible: true });
    expect(parseLineText('Butter 100 g, only Dairyfields')).toEqual({
      name: 'Butter', quantity: 100, unit: 'g', flexible: false, pinnedBrand: 'Dairyfields',
    });
    expect(parseLineText('Cold pressed oil 1 L')).toMatchObject({ name: 'Cold pressed oil', quantity: 1000, unit: 'ml' });
  });

  it('rounds packs up to cover the need', () => {
    expect(packsNeeded(1000, 500)).toBe(2);
    expect(packsNeeded(1500, 1000)).toBe(2);
    expect(packsNeeded(12, 12)).toBe(1);
  });
});
