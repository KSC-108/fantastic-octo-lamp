import type { Unit } from './types.ts';

const UNIT_ALIASES: Record<string, { unit: Unit; factor: number }> = {
  g: { unit: 'g', factor: 1 },
  gm: { unit: 'g', factor: 1 },
  gms: { unit: 'g', factor: 1 },
  gram: { unit: 'g', factor: 1 },
  grams: { unit: 'g', factor: 1 },
  kg: { unit: 'g', factor: 1000 },
  kgs: { unit: 'g', factor: 1000 },
  ml: { unit: 'ml', factor: 1 },
  l: { unit: 'ml', factor: 1000 },
  lt: { unit: 'ml', factor: 1000 },
  ltr: { unit: 'ml', factor: 1000 },
  litre: { unit: 'ml', factor: 1000 },
  liter: { unit: 'ml', factor: 1000 },
  litres: { unit: 'ml', factor: 1000 },
  pc: { unit: 'pc', factor: 1 },
  pcs: { unit: 'pc', factor: 1 },
  piece: { unit: 'pc', factor: 1 },
  pieces: { unit: 'pc', factor: 1 },
  pack: { unit: 'pc', factor: 1 },
  packs: { unit: 'pc', factor: 1 },
  nos: { unit: 'pc', factor: 1 },
  unit: { unit: 'pc', factor: 1 },
  units: { unit: 'pc', factor: 1 },
};

const QTY = String.raw`(\d+(?:\.\d+)?)\s*(?:x\s*(\d+(?:\.\d+)?)\s*)?([a-zA-Z]+)`;

/** Parses "200 g", "1 L", "5kg", "2 x 500 ml", "12 pcs" into base units. */
export function parseQuantity(text: string): { size: number; unit: Unit } | null {
  const m = new RegExp(`^\\s*${QTY}\\s*$`).exec(text.trim());
  if (!m) return null;
  return fromMatch(m[1]!, m[2], m[3]!);
}

function fromMatch(a: string, b: string | undefined, unitText: string) {
  const alias = UNIT_ALIASES[unitText.toLowerCase()];
  if (!alias) return null;
  // "2 x 500 ml" means two packs of 500 ml.
  const size = b ? Number(a) * Number(b) : Number(a);
  return { size: round(size * alias.factor), unit: alias.unit };
}

/**
 * Parses a list-line description in the Phase 0 sheet format, for example
 * "Paneer 200 g, any brand" or "Butter 100 g, only Dairyfields".
 */
export function parseLineText(text: string): {
  name: string;
  quantity: number;
  unit: Unit;
  flexible: boolean;
  pinnedBrand?: string;
} | null {
  const m = new RegExp(`^(.*?)\\s+${QTY}\\b(.*)$`).exec(text.trim());
  if (!m) return null;
  const qty = fromMatch(m[2]!, m[3], m[4]!);
  if (!qty) return null;
  const rest = (m[5] ?? '').replace(/^[\s,;:-]+/, '');
  const only = /\bonly\s+(.+)$/i.exec(rest);
  return {
    name: m[1]!.trim(),
    quantity: qty.size,
    unit: qty.unit,
    flexible: !only,
    ...(only ? { pinnedBrand: only[1]!.trim() } : {}),
  };
}

/** Whole packs needed to cover a required quantity. */
export function packsNeeded(required: number, packSize: number): number {
  if (packSize <= 0) return Infinity;
  return Math.max(1, Math.ceil(required / packSize - 1e-9));
}

export function formatQuantity(size: number, unit: Unit): string {
  if (unit === 'g') return size >= 1000 ? `${round(size / 1000)} kg` : `${size} g`;
  if (unit === 'ml') return size >= 1000 ? `${round(size / 1000)} L` : `${size} ml`;
  return `${size} pc`;
}

export function round(n: number, digits = 2): number {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}
