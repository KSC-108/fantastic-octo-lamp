import { readFileSync } from 'node:fs';
import { parseArgs } from 'node:util';
import {
  createHighsSolver, DEFAULT_RULES, importItemSheet, optimise, sampleBasket, formatQuantity, type Basket,
} from './index.ts';

const { values } = parseArgs({
  options: {
    csv: { type: 'string' },
    basket: { type: 'string' },
    tolerance: { type: 'string', default: '5' },
    lambda: { type: 'string', default: '0' },
    'max-orders': { type: 'string' },
  },
});

let basket: Basket;
if (values.csv) {
  const imported = importItemSheet(readFileSync(values.csv, 'utf8'), values.basket ? { basket: values.basket } : {});
  for (const w of imported.warnings) console.warn(`warning: ${w}`);
  basket = { lines: imported.lines, listings: imported.listings, rules: DEFAULT_RULES };
} else {
  basket = sampleBasket();
  console.log('Using the built-in sample basket (invented prices).\n');
}

const solver = await createHighsSolver();
const plan = optimise(basket, {
  upgradeTolerancePct: Number(values.tolerance),
  lambda: Number(values.lambda),
  ...(values['max-orders'] ? { maxOrders: Number(values['max-orders']) } : {}),
}, solver);

const rs = (n: number) => `Rs ${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
for (const o of plan.orders) {
  console.log(`${o.name}: ${rs(o.total)} (items ${rs(o.subtotal)}, fees ${rs(o.feeTotal)}${o.coupon ? `, coupon -${rs(o.coupon.amount)}` : ''})`);
  for (const i of o.items) {
    console.log(`  ${i.upgraded ? '*' : ' '} ${i.line.name} (${formatQuantity(i.line.quantity, i.line.unit)}): ${i.packs} x ${i.listing.title} = ${rs(i.cost)}`);
  }
}
console.log(`\nTotal: ${rs(plan.totals.total)} across ${plan.orders.length} orders`);
console.log(`Cheapest plan before upgrades: ${rs(plan.cheapestTotals.total)}; upgrade spend ${rs(plan.upgradeSpend)} of ${rs(plan.tolerance)} allowed`);
if (plan.bestSingle) {
  console.log(`Best single platform: ${plan.bestSingle.name} at ${rs(plan.bestSingle.totals!.total)}`);
  console.log(`Saved by splitting: ${rs(plan.savings.split!)}; net after upgrades: ${rs(plan.savings.net!)}`);
} else {
  console.log('No single platform carries the whole list.');
}
for (const u of plan.upgrades) {
  console.log(`Upgrade: ${u.line.name}: ${u.from.listing.title} -> ${u.to.listing.title} (${u.itemCostChange >= 0 ? '+' : ''}${rs(u.itemCostChange)}, +${u.qualityGain} quality)`);
}
if (plan.unfulfilled.length) console.log(`No listing found for: ${plan.unfulfilled.map((l) => l.name).join(', ')}`);
console.log(`Solved in ${plan.solveMs} ms`);
