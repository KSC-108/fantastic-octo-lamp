import { useState } from 'react';
import { formatQuantity, type Order, type PlanResult } from '@splitcart/engine';
import { Badge, Button, Card, CardHeader, Empty, PlatformMark, SectionTitle, Stat, cx } from '../components/ui.tsx';
import { plural, rs, signedRs } from '../format.ts';

export function PlanView({ plan, solving, error, onGoTo }: {
  plan: PlanResult | null;
  solving: boolean;
  error: string | null;
  onGoTo: (tab: 'basket' | 'prices') => void;
}) {
  if (!plan) {
    if (error) return <Empty title="No plan yet">{error}</Empty>;
    return <Empty title="Finding the best split">Solving across all five platforms.</Empty>;
  }
  const best = plan.bestSingle;
  const lineCount = plan.orders.reduce((n, o) => n + o.items.length, 0);

  return (
    <div className={cx('space-y-8 transition-opacity', solving && 'opacity-60')}>
      {error && <p className="rounded-lg border border-line bg-warn-soft px-4 py-2.5 text-[13px] text-warn">{error} Showing the last valid plan.</p>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Your total" value={rs(plan.totals.total)} note={`${plural(lineCount, 'item')} across ${plural(plan.orders.length, 'order')}`} />
        <Stat
          label="Best single platform"
          value={best ? rs(best.totals!.total) : '—'}
          note={best ? `${best.name}, everything in one order` : 'No platform stocks the whole list'}
        />
        <Stat
          label="Saved by splitting"
          tone="gain"
          value={plan.savings.split !== null ? rs(Math.max(0, plan.savings.split)) : '—'}
          note={plan.savings.split !== null ? 'Cheapest split versus the best single platform, before upgrades' : 'Needs at least one platform with every item'}
        />
        <Stat
          label="Spent on upgrades"
          tone="accent"
          value={rs(plan.upgradeSpend)}
          note={`${plural(plan.upgrades.length, 'premium upgrade')}, within your ${rs(plan.tolerance)} allowance`}
        />
      </div>

      {plan.savings.breakdown && best && <SavingsBreakdown plan={plan} />}

      {plan.unfulfilled.length > 0 && (
        <p className="rounded-lg border border-line bg-warn-soft px-4 py-3 text-[13px] text-warn">
          No in-stock listing yet for {plan.unfulfilled.map((l) => l.name).join(', ')}. These are left out of the plan.{' '}
          <button className="font-medium underline underline-offset-2" onClick={() => onGoTo('prices')}>Add prices</button>
        </p>
      )}

      <div>
        <SectionTitle hint="Each card is one cart. You check out and pay in the app.">Orders</SectionTitle>
        <div className="grid gap-4 lg:grid-cols-2">
          {plan.orders.map((o) => <OrderCard key={o.platform} order={o} />)}
        </div>
      </div>

      {(plan.upgrades.length > 0 || plan.optionalUpgrades.length > 0) && <Upgrades plan={plan} />}

      <Comparison plan={plan} />
    </div>
  );
}

function SavingsBreakdown({ plan }: { plan: PlanResult }) {
  const b = plan.savings.breakdown!;
  const rows: [string, number, string][] = [
    ['Item prices', b.items, 'Buying each item where it is cheapest'],
    ['Fees', b.fees, 'Delivery, handling, small-cart and platform fees across your orders'],
    ['Coupons', b.coupons, 'Platform coupons applied before payment'],
  ];
  return (
    <Card>
      <CardHeader
        title="Where the money comes from"
        meta={`Compared with ordering everything from ${plan.bestSingle!.name}. Positive numbers are savings.`}
      />
      <dl className="divide-y divide-line text-[13.5px]">
        {rows.map(([label, value, hint]) => (
          <div key={label} className="flex items-center justify-between gap-4 px-5 py-2.5">
            <dt><span className="font-medium">{label}</span><span className="ml-2 text-muted">{hint}</span></dt>
            <dd className={cx('tabular-nums', value > 0 && 'text-gain', value < 0 && 'text-loss')}>{signedRs(value)}</dd>
          </div>
        ))}
        <div className="flex items-center justify-between gap-4 px-5 py-2.5 font-semibold">
          <dt>Saved by splitting</dt>
          <dd className="tabular-nums text-gain">{signedRs(plan.savings.split!)}</dd>
        </div>
        <div className="flex items-center justify-between gap-4 px-5 py-2.5">
          <dt><span className="font-medium">Premium upgrades</span><span className="ml-2 text-muted">Spent by choice, within your allowance</span></dt>
          <dd className="tabular-nums text-accent">{signedRs(-plan.upgradeSpend)}</dd>
        </div>
        <div className="flex items-center justify-between gap-4 rounded-b-xl bg-canvas px-5 py-3 font-semibold">
          <dt>Net versus the best single platform</dt>
          <dd className={cx('tabular-nums', plan.savings.net! >= 0 ? 'text-gain' : 'text-loss')}>{signedRs(plan.savings.net!)}</dd>
        </div>
      </dl>
    </Card>
  );
}

function OrderCard({ order }: { order: Order }) {
  const [copied, setCopied] = useState(false);
  const feeRows = (
    [['Delivery', order.fees.delivery], ['Small cart', order.fees.smallCart], ['Handling', order.fees.handling], ['Platform', order.fees.platform], ['Surge', order.fees.surge]] as const
  ).filter(([, v]) => v > 0);

  const copy = async () => {
    const text = [
      `${order.name}: ${order.items.length} items, expected total ${rs(order.total)}`,
      ...order.items.map((i) => `- ${i.listing.title}${i.listing.brand ? ` (${i.listing.brand})` : ''}, ${formatQuantity(i.listing.packSize, i.listing.unit)} x ${i.packs}`),
    ].join('\n');
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      window.prompt('Copy this checklist', text);
    }
  };

  return (
    <Card className="flex flex-col">
      <header className="flex items-center gap-3 border-b border-line px-5 py-4">
        <PlatformMark platform={order.platform} name={order.name} />
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold tracking-tight">{order.name}</h3>
          <p className="text-[12.5px] text-muted">{plural(order.items.length, 'item')}</p>
        </div>
        <p className="text-[18px] font-semibold tabular-nums">{rs(order.total)}</p>
      </header>
      <ul className="flex-1 divide-y divide-line">
        {order.items.map((i) => (
          <li key={i.line.id} className="flex items-start gap-3 px-5 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="text-[13.5px] leading-snug">
                {i.listing.title}
                {i.upgraded && <span className="ml-2 align-[1px]"><Badge tone="accent" title={i.quality.reasons.join(', ')}>Upgrade</Badge></span>}
              </p>
              <p className="mt-0.5 text-[12px] text-muted">
                {i.line.name}, {formatQuantity(i.line.quantity, i.line.unit)} needed · {i.packs} × {formatQuantity(i.listing.packSize, i.listing.unit)}
                {i.quality.reasons.length > 0 && <span className="text-faint"> · {i.quality.reasons.slice(0, 2).join(', ')}</span>}
              </p>
            </div>
            <p className="pt-0.5 text-[13.5px] tabular-nums">{rs(i.cost)}</p>
          </li>
        ))}
      </ul>
      <footer className="border-t border-line px-5 py-3 text-[12.5px] text-muted">
        <div className="flex justify-between"><span>Items</span><span className="tabular-nums">{rs(order.subtotal)}</span></div>
        {feeRows.map(([label, v]) => (
          <div key={label} className="flex justify-between"><span>{label} fee</span><span className="tabular-nums">{rs(v)}</span></div>
        ))}
        {order.coupon && (
          <div className="flex justify-between text-gain"><span>{order.coupon.label}</span><span className="tabular-nums">−{rs(order.coupon.amount)}</span></div>
        )}
        {feeRows.length === 0 && !order.coupon && <p>No fees at this cart size.</p>}
        <div className="mt-3 flex gap-2">
          <Button onClick={copy}>{copied ? 'Copied' : 'Copy checklist'}</Button>
          <Button disabled title="The browser extension fills carts once its platform adapters are built in Phase 3.">Fill cart</Button>
        </div>
      </footer>
    </Card>
  );
}

function Upgrades({ plan }: { plan: PlanResult }) {
  const optional = plan.optionalUpgrades.filter((o) => !plan.upgrades.some((u) => u.line.id === o.line.id && u.to.listing.id === o.alternative.listing.id));
  return (
    <div>
      <SectionTitle hint={`Allowance: ${rs(plan.tolerance)}, 5% of the cheapest basket by default`}>Premium upgrades</SectionTitle>
      <Card>
        {plan.upgrades.length === 0 && <p className="px-5 py-4 text-[13px] text-muted">No upgrade fits within the allowance for this basket.</p>}
        <ul className="divide-y divide-line">
          {plan.upgrades.map((u) => (
            <li key={u.line.id} className="grid gap-1 px-5 py-3 sm:grid-cols-[1fr_auto] sm:items-center">
              <div>
                <p className="text-[13.5px]"><span className="font-medium">{u.line.name}</span>: {u.to.listing.title}</p>
                <p className="text-[12px] text-muted">
                  Instead of {u.from.listing.title} · {u.to.quality.reasons.join(', ') || 'higher rated'}
                </p>
              </div>
              <div className="flex items-center gap-2 sm:justify-end">
                <Badge tone="accent">+{u.qualityGain} quality</Badge>
                <span className="w-20 text-right text-[13.5px] tabular-nums">{signedRs(u.itemCostChange)}</span>
              </div>
            </li>
          ))}
        </ul>
        {optional.length > 0 && (
          <div className="border-t border-line bg-canvas/60 px-5 py-3">
            <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-muted">Over the allowance, not taken</p>
            <ul className="mt-2 space-y-1.5">
              {optional.map((o) => (
                <li key={o.line.id} className="flex justify-between gap-4 text-[13px]">
                  <span><span className="font-medium">{o.line.name}</span>: {o.alternative.listing.title} <span className="text-faint">({o.alternative.quality.reasons.join(', ') || 'higher rated'})</span></span>
                  <span className="tabular-nums text-muted">{signedRs(o.itemCostChange)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}

function Comparison({ plan }: { plan: PlanResult }) {
  return (
    <div>
      <SectionTitle hint="Each platform's own cheapest cart for the whole list">Single-platform comparison</SectionTitle>
      <Card>
        <table className="w-full text-[13.5px]">
          <thead>
            <tr className="border-b border-line text-left text-[12px] uppercase tracking-[0.06em] text-muted">
              <th className="px-5 py-2.5 font-medium">Platform</th>
              <th className="px-5 py-2.5 text-right font-medium">Items</th>
              <th className="px-5 py-2.5 text-right font-medium">Fees</th>
              <th className="px-5 py-2.5 text-right font-medium">Total</th>
              <th className="px-5 py-2.5 text-right font-medium">You save</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            <tr className="bg-accent-soft/50 font-medium">
              <td className="px-5 py-2.5">Your split plan</td>
              <td className="px-5 py-2.5 text-right tabular-nums">{rs(plan.totals.items)}</td>
              <td className="px-5 py-2.5 text-right tabular-nums">{rs(plan.totals.fees)}</td>
              <td className="px-5 py-2.5 text-right tabular-nums">{rs(plan.totals.total)}</td>
              <td className="px-5 py-2.5 text-right text-muted">includes upgrades</td>
            </tr>
            {plan.baselines.map((b) => (
              <tr key={b.platform}>
                <td className="px-5 py-2.5">{b.name}</td>
                {b.totals ? (
                  <>
                    <td className="px-5 py-2.5 text-right tabular-nums">{rs(b.totals.items)}</td>
                    <td className="px-5 py-2.5 text-right tabular-nums">{rs(b.totals.fees)}</td>
                    <td className="px-5 py-2.5 text-right tabular-nums">{rs(b.totals.total)}</td>
                    <td className="px-5 py-2.5 text-right tabular-nums text-gain">{signedRs(b.totals.total - plan.totals.total)}</td>
                  </>
                ) : (
                  <td colSpan={4} className="px-5 py-2.5 text-right text-[12.5px] text-muted">Cannot fulfil: {b.missing.join(', ')}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
