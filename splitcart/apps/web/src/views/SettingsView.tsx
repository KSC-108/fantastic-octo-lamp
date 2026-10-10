import { useState } from 'react';
import { DEFAULT_TRAITS, type BrandTier, type TraitRule } from '@splitcart/engine';
import { Button, Card, CardHeader, Field, NumberInput, Select, TextInput, Toggle } from '../components/ui.tsx';
import { defaultState, type AppState, type SetState } from '../state.ts';

export function SettingsView({ state, setState }: { state: AppState; setState: SetState }) {
  const p = state.prefs;
  const setPrefs = (patch: Partial<AppState['prefs']>) => setState((s) => ({ ...s, prefs: { ...s.prefs, ...patch } }));
  const traits = p.traits ?? DEFAULT_TRAITS;
  const setTrait = (i: number, patch: Partial<TraitRule>) => setPrefs({ traits: traits.map((t, j) => (j === i ? { ...t, ...patch } : t)) });

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
      <div className="space-y-6">
        <Card>
          <CardHeader title="Planning" meta="How the optimiser trades money for convenience and quality." />
          <div className="space-y-4 px-5 py-4">
            <Field label="Pincode" hint="Prices and fees should be captured for this pincode.">
              <TextInput value={state.pincode} onChange={(e) => setState((s) => ({ ...s, pincode: e.target.value }))} />
            </Field>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-[12.5px] font-medium">Premium upgrades</p>
                <p className="text-[12px] text-faint">Swap in better products when the basket stays within the allowance.</p>
              </div>
              <Toggle label="Premium upgrades" checked={p.upgradesEnabled !== false} onChange={(v) => setPrefs({ upgradesEnabled: v })} />
            </div>
            <Field label={`Upgrade allowance: ${p.upgradeTolerancePct}% of the cheapest basket`} hint="Rs 25 on a Rs 500 basket at 5%.">
              <input type="range" min={0} max={15} step={0.5} value={p.upgradeTolerancePct} onChange={(e) => setPrefs({ upgradeTolerancePct: Number(e.target.value) })} className="w-full accent-[#134e3a]" />
            </Field>
            <Field label="Minimum quality gain for an upgrade" hint="Points on the 0 to 100 quality score. Stops spending on tiny rating differences.">
              <NumberInput value={p.minQualityGain} min={0} max={50} onChange={(n) => setPrefs({ minQualityGain: n ?? 0 })} />
            </Field>
            <Field label="Cost per extra delivery (Rs)" hint="0 means as many deliveries as the order needs.">
              <NumberInput value={p.lambda} min={0} onChange={(n) => setPrefs({ lambda: n ?? 0 })} />
            </Field>
            <Field label="Maximum number of orders" hint="Leave blank for no limit.">
              <NumberInput value={p.maxOrders} min={1} max={5} onChange={(n) => setPrefs({ maxOrders: n })} />
            </Field>
            <Field label="Usual platform" hint="Adds a 'versus how you shop today' comparison.">
              <Select className="w-full" value={p.usualPlatform ?? ''} onChange={(e) => setPrefs({ usualPlatform: e.target.value || undefined })}>
                <option value="">None</option>
                {state.basket.rules.map((r) => <option key={r.platform} value={r.platform}>{r.name}</option>)}
              </Select>
            </Field>
          </div>
        </Card>
        <BrandTiers tiers={p.brandTiers ?? {}} onChange={(brandTiers) => setPrefs({ brandTiers })} />
        <Card>
          <CardHeader title="Reset" meta="Restores the sample basket, default fees and default preferences. Your imported data is cleared." />
          <div className="px-5 py-4"><Button onClick={() => { if (confirm('Reset everything to the defaults?')) setState(defaultState()); }}>Reset to defaults</Button></div>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Quality ladder"
          meta="Words found in a product's name or tags add these points, up to 60. Ratings add up to 20 and brand tier up to 20."
          action={<Button variant="ghost" onClick={() => setPrefs({ traits: structuredClone(DEFAULT_TRAITS) })}>Restore defaults</Button>}
        />
        <div className="divide-y divide-line">
          {traits.map((t, i) => (
            <div key={t.id} className="grid grid-cols-[9rem_1fr_5rem] items-center gap-3 px-5 py-2.5">
              <TextInput value={t.label} onChange={(e) => setTrait(i, { label: e.target.value })} aria-label="Trait" />
              <TextInput value={t.keywords.join(', ')} onChange={(e) => setTrait(i, { keywords: e.target.value.split(',').map((k) => k.trim()).filter(Boolean) })} aria-label={`${t.label} keywords`} />
              <NumberInput value={t.points} min={-30} max={40} onChange={(n) => setTrait(i, { points: n ?? 0 })} aria-label={`${t.label} points`} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function BrandTiers({ tiers, onChange }: { tiers: Record<string, BrandTier>; onChange: (t: Record<string, BrandTier>) => void }) {
  const [text, setText] = useState(Object.entries(tiers).map(([b, t]) => `${b}: ${t}`).join('\n'));
  const apply = (value: string) => {
    setText(value);
    const out: Record<string, BrandTier> = {};
    for (const line of value.split('\n')) {
      const m = /^(.+?):\s*(premium|standard|value)\s*$/i.exec(line.trim());
      if (m) out[m[1]!.trim().toLowerCase()] = m[2]!.toLowerCase() as BrandTier;
    }
    onChange(out);
  };
  return (
    <Card>
      <CardHeader title="Brand tiers" meta="One brand per line, as 'Brand: premium', 'standard' or 'value'. Unlisted brands count as standard." />
      <div className="px-5 py-4">
        <textarea
          value={text}
          onChange={(e) => apply(e.target.value)}
          rows={5}
          placeholder={'Gauri Farms: premium\nGhanihouse: premium'}
          className="w-full rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[12.5px] outline-none focus:border-accent"
        />
      </div>
    </Card>
  );
}
