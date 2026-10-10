import { describe, expect, it } from 'vitest';
import { importItemSheet, ITEM_SHEET_TEMPLATE, parseCsv } from '../src/index.ts';

describe('csv import', () => {
  it('parses quoted fields', () => {
    expect(parseCsv('a,"b, c","d ""e"""\r\n1,2,3\n')).toEqual([['a', 'b, c', 'd "e"'], ['1', '2', '3']]);
  });

  it('imports the Phase 0 item sheet template', () => {
    const r = importItemSheet(ITEM_SHEET_TEMPLATE);
    expect(r.warnings).toEqual([]);
    expect(r.baskets).toEqual(['B01']);
    expect(r.lines.map((l) => l.name)).toEqual(['Paneer', 'Butter']);
    expect(r.lines[1]).toMatchObject({ flexible: false, pinnedBrand: 'Example Dairy' });
    expect(r.listings).toHaveLength(3);
    expect(r.listings[0]).toMatchObject({ platform: 'zepto', price: 96, packSize: 200, unit: 'g', rating: 4.5, attributes: ['fresh'] });
  });

  it('reports rows it cannot read', () => {
    const r = importItemSheet('Platform,List line,Product as listed,Pack size,Price (Rs)\nZepto,Milk 1 L,Milk,500 g,30\n');
    expect(r.warnings[0]).toMatch(/does not match/);
  });
});
