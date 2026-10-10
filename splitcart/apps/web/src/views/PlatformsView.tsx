import type { Coupon, FeeTier, PlatformRules } from '@splitcart/engine';
import { Button, Card, CardHeader, Field, NumberInput, PlatformMark, Select, TextInput, Toggle } from '../components/ui.tsx';
import type { AppState, SetState } from '../state.ts';

export function PlatformsView({ state, setState }: { state: AppState; setState: SetState }) {
  const excluded = new Set(state.prefs.excludedPlatforms ?? []);
  const update = (platform: string, patch: Partial<PlatformRules>) =>
    setState((s) => ({ ...s, basket: { ...s.basket, rules: s.basket.rules.map((r) => (r.platform === platform ? { ...r, ...patch, asOf: new Date().toISOString().slice(0, 10), source: 'Entered by you' } : r)) } }));
  const setIncluded = (platform: string, on: boolean) =>
    setState((s) => {
      const set = new Set(s.prefs.excludedPlatforms ?? []);
      if (on) set.delete(platform); else set.add(platform);
      return { ...s, prefs: { ...s.prefs, excludedPlatforms: [...set] } };
    });

  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted">
        Starting values are indicative figures from public reports and may be wrong for pincode {state.pincode}. Replace them with what each app shows on its bill summary.
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        {state.basket.rules.map((r) => (
          <Card key={r.platform} className={excluded.has(r.platform) ? 'opacity-60' : ''}>
            <header className="flex items-center gap-3 border-b border-line px-5 py-4">
              <PlatformMark platform={r.platform} name={r.name} />
              <div className="min-w-0 flex-1">
                <h3 className="text-[15px] font-semibold tracking-tight">{r.name}</h3>
                <p className="truncate text-[12px] text-faint" title={r.source}>{r.source} {r.asOf && `· ${r.asOf}`}</p>
              </div>
              <Toggle label={`Use ${r.name}`} checked={!excluded.has(r.platform)} onChange={(v) => setIncluded(r.platform, v)} />
            </header>
            <div className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-3">
              <Field label="Minimum order" hint="Checkout blocked below this">
                <NumberInput value={r.minOrderValue} min={0} onChange={(n) => update(r.platform, { minOrderValue: n ?? 0 })} />
              </Field>
              <Field label="Handling fee"><NumberInput value={r.handlingFee} min={0} onChange={(n) => update(r.platform, { handlingFee: n ?? 0 })} /></Field>
              <Field label="Platform fee"><NumberInput value={r.platformFee} min={0} onChange={(n) => update(r.platform, { platformFee: n ?? 0 })} /></Field>
              <Field label="Surge fee" hint="Peak hours, rain"><NumberInput value={r.surgeFee} min={0} onChange={(n) => update(r.platform, { surgeFee: n ?? 0 })} /></Field>
            </div>
            <Tiers title="Delivery fee" tiers={r.deliveryFee} onChange={(t) => update(r.platform, { deliveryFee: t })} />
            <Tiers title="Small-cart fee" tiers={r.smallCartFee} onChange={(t) => update(r.platform, { smallCartFee: t })} />
            <Coupons coupons={r.coupons} onChange={(c) => update(r.platform, { coupons: c })} />
          </Card>
        ))}
      </div>
    </div>
  );
}

function Tiers({ title, tiers, onChange }: { title: string; tiers: FeeTier[]; onChange: (t: FeeTier[]) => void }) {
  return (
    <div className="border-t border-line px-5 py-3">
      <div className="flex items-center justify-between">
        <p className="text-[12.5px] font-medium">{title}</p>
        <Button variant="ghost" onClick={() => onChange([...tiers, { below: 199, fee: 30 }])}>Add tier</Button>
      </div>
      {tiers.length === 0 && <p className="text-[12.5px] text-faint">None</p>}
      {tiers.map((t, i) => (
        <div key={i} className="mt-1.5 flex items-center gap-2 text-[13px] text-muted">
          <span>Rs</span>
          <NumberInput className="w-20" value={t.fee} min={0} onChange={(n) => onChange(tiers.map((x, j) => (j === i ? { ...x, fee: n ?? 0 } : x)))} aria-label={`${title} amount`} />
          <span>when the cart is below Rs</span>
          <NumberInput className="w-24" value={t.below} min={0} onChange={(n) => onChange(tiers.map((x, j) => (j === i ? { ...x, below: n ?? 0 } : x)))} aria-label={`${title} threshold`} />
          <Button variant="ghost" onClick={() => onChange(tiers.filter((_, j) => j !== i))}>Remove</Button>
        </div>
      ))}
    </div>
  );
}

function Coupons({ coupons, onChange }: { coupons: Coupon[]; onChange: (c: Coupon[]) => void }) {
  const set = (i: number, patch: Partial<Coupon>) => onChange(coupons.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <div className="border-t border-line px-5 py-3">
      <div className="flex items-center justify-between">
        <p className="text-[12.5px] font-medium">Platform coupons <span className="font-normal text-faint">(not bank or UPI offers)</span></p>
        <Button variant="ghost" onClick={() => onChange([...coupons, { id: `c${Date.now()}`, label: 'Rs 50 off', minSpend: 999, kind: 'flat', value: 50 }])}>Add coupon</Button>
      </div>
      {coupons.length === 0 && <p className="text-[12.5px] text-faint">None</p>}
      {coupons.map((c, i) => (
        <div key={c.id} className="mt-1.5 flex flex-wrap items-center gap-2 text-[13px] text-muted">
          <TextInput className="w-36" value={c.label} onChange={(e) => set(i, { label: e.target.value })} aria-label="Coupon label" />
          <Select value={c.kind} onChange={(e) => set(i, { kind: e.target.value as Coupon['kind'] })} aria-label="Coupon type">
            <option value="flat">Flat Rs</option>
            <option value="percent">Percent</option>
          </Select>
          <NumberInput className="w-20" value={c.value} min={0} onChange={(n) => set(i, { value: n ?? 0 })} aria-label="Coupon value" />
          {c.kind === 'percent' && <><span>up to Rs</span><NumberInput className="w-20" value={c.cap} min={0} onChange={(n) => set(i, n === undefined ? { cap: undefined } : { cap: n })} aria-label="Coupon cap" /></>}
          <span>on carts from Rs</span>
          <NumberInput className="w-20" value={c.minSpend} min={0} onChange={(n) => set(i, { minSpend: n ?? 0 })} aria-label="Coupon minimum" />
          <Button variant="ghost" onClick={() => onChange(coupons.filter((_, j) => j !== i))}>Remove</Button>
        </div>
      ))}
    </div>
  );
}
