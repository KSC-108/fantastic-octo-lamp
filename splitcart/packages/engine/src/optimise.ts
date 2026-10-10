import type {
  Baseline, Basket, Candidate, ListLine, OptionalUpgrade, Order, OrderItem, PlanResult,
  PlatformId, PlatformRules, Preferences, Totals, Upgrade,
} from './types.ts';
import { buildModel, type ModelSpec } from './model.ts';
import { orderCost, validateRules } from './fees.ts';
import { scoreListing } from './quality.ts';
import { packsNeeded, round } from './units.ts';
import type { Solver } from './solver.ts';

export const DEFAULT_PREFERENCES: Preferences = {
  lambda: 0,
  upgradeTolerancePct: 5,
  minQualityGain: 8,
  upgradesEnabled: true,
};

export class PlanError extends Error {}

const EPS = 1e-4;

/** Every in-stock listing that can satisfy a line, with packs, cost and quality. */
export function buildCandidates(basket: Basket, prefs: Preferences) {
  const excluded = new Set(prefs.excludedPlatforms ?? []);
  const rules = new Map(basket.rules.filter((r) => !excluded.has(r.platform)).map((r) => [r.platform, r] as const));
  const candidates: Candidate[] = [];
  const unfulfilled: ListLine[] = [];
  for (const line of basket.lines) {
    const before = candidates.length;
    for (const listing of basket.listings) {
      if (listing.lineId !== line.id || !listing.inStock || !rules.has(listing.platform)) continue;
      if (listing.unit !== line.unit || !(listing.price > 0) || !(listing.packSize > 0)) continue;
      if (line.pinnedBrand && (listing.brand ?? '').toLowerCase() !== line.pinnedBrand.toLowerCase()) continue;
      const packs = packsNeeded(line.quantity, listing.packSize);
      candidates.push({
        index: candidates.length,
        line,
        listing,
        packs,
        cost: round(packs * listing.price),
        quality: scoreListing(listing, prefs),
      });
    }
    if (candidates.length === before) unfulfilled.push(line);
  }
  return { candidates, unfulfilled, rules };
}

/** Finds the cheapest split, then spends up to the tolerance on quality upgrades. */
export function optimise(basket: Basket, preferences: Partial<Preferences>, solver: Solver): PlanResult {
  const started = Date.now();
  const prefs: Preferences = { ...DEFAULT_PREFERENCES, ...preferences };
  const problems = basket.rules.flatMap(validateRules);
  if (problems.length > 0) throw new PlanError(problems.join('; '));

  const { candidates, unfulfilled, rules } = buildCandidates(basket, prefs);
  const lineIds = [...new Set(candidates.map((c) => c.line.id))];
  if (lineIds.length === 0) throw new PlanError('No list line has a matching in-stock listing yet.');
  const base = { candidates, lineIds, rules, lambda: prefs.lambda, ...(prefs.maxOrders ? { maxOrders: prefs.maxOrders } : {}) };

  // Stage 1: lowest penalised cost.
  const cheapest = solveSelection(solver, { ...base, objective: 'min-cost' });
  if (!cheapest) {
    throw new PlanError('No plan satisfies the minimum order values and order limit. Relax the limit or add listings.');
  }
  const cheapestEval = evaluate(cheapest, rules, new Set());
  const cheapestPenalised = cheapestEval.totals.total + prefs.lambda * cheapestEval.orders.length;
  const tolerance = round((prefs.upgradeTolerancePct / 100) * cheapestEval.totals.total);

  let final = cheapest;
  if (prefs.upgradesEnabled !== false) {
    const s1ByLine = new Map(cheapest.map((c) => [c.line.id, c] as const));
    const floors = new Map(cheapest.map((c) => [c.line.id, c.quality.score - EPS] as const));
    // Only gains of at least minQualityGain count, so tolerance is not spent on trivial rating differences.
    const values = candidates.map((c) => {
      const baseQ = s1ByLine.get(c.line.id)!.quality.score;
      return c.quality.score >= baseQ + prefs.minQualityGain ? c.quality.score : baseQ;
    });
    const cap = cheapestPenalised + tolerance + EPS;
    // Stage 2: most quality within the tolerance, never downgrading a line.
    const best = solveSelection(solver, { ...base, objective: 'max-value', values, costCap: cap, lineQualityFloors: floors });
    if (best) {
      const bestValue = best.reduce((sum, c) => sum + values[c.index]!, 0);
      // Stage 3: cheapest way to reach that quality.
      const cheapestAtBest = solveSelection(solver, {
        ...base, objective: 'min-cost', values, costCap: cap, valueFloor: bestValue - EPS, lineQualityFloors: floors,
      });
      final = cheapestAtBest ?? best;
    }
  }

  const upgradedLines = new Set<string>();
  const cheapestByLine = new Map(cheapest.map((c) => [c.line.id, c] as const));
  for (const c of final) {
    const was = cheapestByLine.get(c.line.id)!;
    if (c.listing.id !== was.listing.id && c.quality.score >= was.quality.score + prefs.minQualityGain) upgradedLines.add(c.line.id);
  }
  const finalEval = evaluate(final, rules, upgradedLines);

  const upgrades: Upgrade[] = [];
  for (const c of final) {
    if (!upgradedLines.has(c.line.id)) continue;
    const was = cheapestByLine.get(c.line.id)!;
    upgrades.push({
      line: c.line,
      from: toItem(was, false),
      to: toItem(c, true),
      itemCostChange: round(c.cost - was.cost),
      qualityGain: round(c.quality.score - was.quality.score, 1),
    });
  }

  const optionalUpgrades: OptionalUpgrade[] = [];
  for (const c of final) {
    const better = candidates
      .filter((o) => o.line.id === c.line.id && o.quality.score >= c.quality.score + prefs.minQualityGain)
      .sort((a, b) => b.quality.score - a.quality.score || a.cost - b.cost)[0];
    if (!better) continue;
    optionalUpgrades.push({
      line: c.line,
      current: toItem(c, upgradedLines.has(c.line.id)),
      alternative: { listing: better.listing, packs: better.packs, cost: better.cost, quality: better.quality },
      itemCostChange: round(better.cost - c.cost),
      qualityGain: round(better.quality.score - c.quality.score, 1),
    });
  }

  const baselines = singlePlatformBaselines(solver, basket, candidates, lineIds, rules, prefs);
  const feasible = baselines.filter((b) => b.feasible && b.totals);
  const bestSingle = feasible.sort((a, b) => a.totals!.total - b.totals!.total)[0] ?? null;
  const usual = prefs.usualPlatform ? baselines.find((b) => b.platform === prefs.usualPlatform && b.feasible) ?? null : null;

  const split = bestSingle ? round(bestSingle.totals!.total - cheapestEval.totals.total) : null;
  return {
    orders: finalEval.orders,
    totals: finalEval.totals,
    cheapestTotals: cheapestEval.totals,
    cheapestOrderCount: cheapestEval.orders.length,
    tolerance,
    upgradeSpend: round(finalEval.totals.total - cheapestEval.totals.total),
    upgrades,
    optionalUpgrades,
    baselines: baselines.sort((a, b) => (a.totals?.total ?? Infinity) - (b.totals?.total ?? Infinity)),
    bestSingle,
    usual,
    savings: {
      split,
      breakdown: bestSingle
        ? {
            items: round(bestSingle.totals!.items - cheapestEval.totals.items),
            fees: round(bestSingle.totals!.fees - cheapestEval.totals.fees),
            coupons: round(cheapestEval.totals.coupons - bestSingle.totals!.coupons),
          }
        : null,
      net: bestSingle ? round(bestSingle.totals!.total - finalEval.totals.total) : null,
      vsUsual: usual ? round(usual.totals!.total - finalEval.totals.total) : null,
    },
    unfulfilled,
    solveMs: Date.now() - started,
  };
}

function singlePlatformBaselines(
  solver: Solver, basket: Basket, candidates: Candidate[], lineIds: string[],
  rules: Map<PlatformId, PlatformRules>, prefs: Preferences,
): Baseline[] {
  const names = new Map(basket.lines.map((l) => [l.id, l.name] as const));
  return [...rules.values()].map((r) => {
    const own = candidates.filter((c) => c.listing.platform === r.platform).map((c, i) => ({ ...c, index: i }));
    const covered = new Set(own.map((c) => c.line.id));
    const missing = lineIds.filter((id) => !covered.has(id)).map((id) => names.get(id) ?? id);
    if (missing.length > 0) return { platform: r.platform, name: r.name, feasible: false, missing, totals: null };
    const sel = solveSelection(solver, { candidates: own, lineIds, rules, lambda: prefs.lambda, objective: 'min-cost' });
    if (!sel) return { platform: r.platform, name: r.name, feasible: false, missing: ['below the minimum order value'], totals: null };
    return { platform: r.platform, name: r.name, feasible: true, missing: [], totals: evaluate(sel, rules, new Set()).totals };
  });
}

function solveSelection(solver: Solver, spec: ModelSpec): Candidate[] | null {
  const { lp } = buildModel(spec);
  const result = solver.solve(lp);
  if (result.status === 'infeasible') return null;
  if (result.status !== 'optimal') throw new PlanError(`Solver failed: ${result.message ?? 'unknown error'}`);
  const chosen = spec.candidates.filter((_, i) => (result.values[`z${i}`] ?? 0) > 0.5);
  if (chosen.length !== spec.lineIds.length) throw new PlanError('Solver returned an inconsistent selection.');
  return chosen;
}

/** Groups a selection into orders and prices each with the fee evaluator. */
export function evaluate(selection: Candidate[], rules: Map<PlatformId, PlatformRules>, upgraded: Set<string>) {
  const byPlatform = new Map<PlatformId, Candidate[]>();
  for (const c of selection) {
    const list = byPlatform.get(c.listing.platform) ?? [];
    list.push(c);
    byPlatform.set(c.listing.platform, list);
  }
  const orders: Order[] = [];
  for (const [platform, items] of byPlatform) {
    const r = rules.get(platform)!;
    const subtotal = round(items.reduce((sum, c) => sum + c.cost, 0));
    const cost = orderCost(r, subtotal);
    orders.push({
      platform,
      name: r.name,
      items: items.map((c) => toItem(c, upgraded.has(c.line.id))),
      subtotal,
      fees: cost.fees,
      feeTotal: cost.feeTotal,
      coupon: cost.coupon ? { id: cost.coupon.coupon.id, label: cost.coupon.coupon.label, amount: round(cost.coupon.amount) } : null,
      total: cost.total,
      belowMinimum: cost.belowMinimum,
    });
  }
  orders.sort((a, b) => b.total - a.total);
  const totals: Totals = {
    items: round(orders.reduce((s, o) => s + o.subtotal, 0)),
    fees: round(orders.reduce((s, o) => s + o.feeTotal, 0)),
    coupons: round(orders.reduce((s, o) => s + (o.coupon?.amount ?? 0), 0)),
    total: round(orders.reduce((s, o) => s + o.total, 0)),
  };
  return { orders, totals };
}

function toItem(c: Candidate, upgraded: boolean): OrderItem {
  return { line: c.line, listing: c.listing, packs: c.packs, cost: c.cost, quality: c.quality, upgraded };
}
