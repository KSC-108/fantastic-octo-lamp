import type { Candidate, PlatformId, PlatformRules } from './types.ts';
import { sortTiers } from './fees.ts';

/**
 * Builds a mixed-integer program in CPLEX LP format.
 *
 * Variables
 *   z{k}      1 when candidate k is bought
 *   y{p}      1 when an order is placed on platform p
 *   s{p}      order subtotal on p
 *   wd{p}_{j} 1 when s{p} clears delivery threshold j; ws{p}_{j} likewise for small-cart fees
 *   c{p}_{q}  1 when coupon q is applied on p;  g{p}_{q} its rupee value
 *
 * Penalised cost = sum over p of
 *   s{p} + (handling + platform + surge + lambda + first delivery fee + first small-cart fee) y{p}
 *   - sum of fee steps released by thresholds - sum of coupon values
 * The fee evaluator in fees.ts computes the same number for a chosen selection.
 */
export interface ModelSpec {
  candidates: Candidate[];
  lineIds: string[];
  rules: Map<PlatformId, PlatformRules>;
  lambda: number;
  maxOrders?: number;
  objective: 'min-cost' | 'max-value';
  /** Per-candidate value, indexed like `candidates`, for max-value objectives and floors. */
  values?: number[];
  costCap?: number;
  valueFloor?: number;
  /** Minimum total quality score per line (no downgrade). */
  lineQualityFloors?: Map<string, number>;
}

export interface BuiltModel {
  lp: string;
  candidateVar: (position: number) => string;
}

export function buildModel(spec: ModelSpec): BuiltModel {
  const { candidates, rules } = spec;
  const platforms = [...new Set(candidates.map((c) => c.listing.platform))];
  const pIndex = new Map(platforms.map((p, i) => [p, i] as const));
  const z = (i: number) => `z${i}`;
  const binaries: string[] = candidates.map((_, i) => z(i));
  const constraints: string[] = [];
  const costTerms: Term[] = [];
  const bigM = Math.max(1, candidates.reduce((sum, c) => sum + c.cost, 0)) * 2;

  // Each line gets exactly one candidate.
  for (const lineId of spec.lineIds) {
    const terms = candidates.flatMap((c, i) => (c.line.id === lineId ? [t(1, z(i))] : []));
    if (terms.length === 0) throw new Error(`No candidates for line ${lineId}`);
    constraints.push(row(`line_${safe(lineId)}`, terms, '=', 1));
  }

  for (const p of platforms) {
    const r = rules.get(p);
    if (!r) throw new Error(`No fee rules for platform ${p}`);
    const pi = pIndex.get(p)!;
    const y = `y${pi}`;
    const s = `s${pi}`;
    binaries.push(y);
    const own = candidates.flatMap((c, i) => (c.listing.platform === p ? [i] : []));

    // Subtotal definition and linking.
    constraints.push(row(`sub_${pi}`, [t(1, s), ...own.map((i) => t(-candidates[i]!.cost, z(i)))], '=', 0));
    for (const i of own) constraints.push(row(`link_${i}`, [t(1, z(i)), t(-1, y)], '<=', 0));
    constraints.push(row(`open_${pi}`, [t(1, y), ...own.map((i) => t(-1, z(i)))], '<=', 0));
    if (r.minOrderValue > 0) constraints.push(row(`mov_${pi}`, [t(1, s), t(-r.minOrderValue, y)], '>=', 0));

    let fixed = r.handlingFee + r.platformFee + r.surgeFee + spec.lambda;
    costTerms.push(t(1, s));

    // Stepped fees: fee = F0 y - sum of steps released by clearing each threshold.
    for (const [tag, tiers] of [['wd', r.deliveryFee], ['ws', r.smallCartFee]] as const) {
      const sorted = sortTiers(tiers);
      if (sorted.length === 0) continue;
      fixed += sorted[0]!.fee;
      sorted.forEach((tier, j) => {
        const next = sorted[j + 1]?.fee ?? 0;
        const step = tier.fee - next;
        if (step <= 0) return;
        const w = `${tag}${pi}_${j}`;
        binaries.push(w);
        constraints.push(row(`${w}_thr`, [t(1, s), t(-tier.below, w)], '>=', 0));
        constraints.push(row(`${w}_open`, [t(1, w), t(-1, y)], '<=', 0));
        costTerms.push(t(-step, w));
      });
    }
    costTerms.push(t(fixed, y));

    // Coupons: at most one per order, value bounded by its rate, its cap and the subtotal.
    if (r.coupons.length > 0) {
      const cs: string[] = [];
      r.coupons.forEach((cp, q) => {
        const c = `c${pi}_${q}`;
        const g = `g${pi}_${q}`;
        binaries.push(c);
        cs.push(c);
        const cap = cp.kind === 'flat' ? cp.value : cp.cap ?? bigM;
        const rate = cp.kind === 'flat' ? 1 : cp.value / 100;
        constraints.push(row(`${c}_min`, [t(1, s), t(-cp.minSpend, c)], '>=', 0));
        constraints.push(row(`${g}_cap`, [t(1, g), t(-cap, c)], '<=', 0));
        constraints.push(row(`${g}_rate`, [t(1, g), t(-rate, s)], '<=', 0));
        costTerms.push(t(-1, g));
      });
      constraints.push(row(`cpn_${pi}`, [...cs.map((c) => t(1, c)), t(-1, y)], '<=', 0));
    }
  }

  if (spec.maxOrders !== undefined) {
    constraints.push(row('max_orders', platforms.map((_, pi) => t(1, `y${pi}`)), '<=', spec.maxOrders));
  }
  if (spec.costCap !== undefined) {
    constraints.push(row('cost_cap', costTerms, '<=', spec.costCap));
  }
  if (spec.valueFloor !== undefined) {
    constraints.push(row('value_floor', valueTerms(spec), '>=', spec.valueFloor));
  }
  if (spec.lineQualityFloors) {
    for (const [lineId, floor] of spec.lineQualityFloors) {
      const terms = candidates.flatMap((c, i) => (c.line.id === lineId ? [t(c.quality.score, z(i))] : []));
      constraints.push(row(`qfloor_${safe(lineId)}`, terms, '>=', floor));
    }
  }

  const objective = spec.objective === 'min-cost'
    ? `Minimize\n obj: ${expr(costTerms)}`
    : `Maximize\n obj: ${expr(valueTerms(spec))}`;

  const lp = [objective, 'Subject To', ...constraints, 'Binary', ...chunk(binaries, 20).map((b) => ` ${b.join(' ')}`), 'End', ''].join('\n');
  return { lp, candidateVar: z };
}

interface Term {
  coef: number;
  name: string;
}

function t(coef: number, name: string): Term {
  return { coef, name };
}

function valueTerms(spec: ModelSpec): Term[] {
  const values = spec.values;
  if (!values) throw new Error('values are required for value objectives and floors');
  const terms = spec.candidates.map((_, i) => t(values[i] ?? 0, `z${i}`));
  // A zero objective is still a valid row; keep at least one term.
  return terms.some((x) => x.coef !== 0) ? terms : [t(0, 'z0')];
}

function row(name: string, terms: Term[], sense: '<=' | '>=' | '=', rhs: number): string {
  return ` ${name}: ${expr(terms)} ${sense} ${num(rhs)}`;
}

function expr(terms: Term[]): string {
  const kept = terms.filter((x) => x.coef !== 0);
  const list = kept.length > 0 ? kept : terms.slice(0, 1);
  const parts = list.map((x, i) => {
    const sign = x.coef < 0 ? '-' : '+';
    const mag = num(Math.abs(x.coef));
    return `${i === 0 && sign === '+' ? '' : `${sign} `}${mag} ${x.name}`;
  });
  return chunk(parts, 8).map((c) => c.join(' ')).join('\n   ');
}

/** Fixed-point formatting: the LP reader must never see exponent notation. */
function num(n: number): string {
  if (!Number.isFinite(n)) throw new Error(`Non-finite coefficient ${n}`);
  const s = n.toFixed(6).replace(/\.?0+$/, '');
  return s === '-0' || s === '' ? '0' : s;
}

function safe(id: string): string {
  return id.replace(/[^A-Za-z0-9_]/g, '_');
}

function chunk<T>(xs: T[], n: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n));
  return out;
}
