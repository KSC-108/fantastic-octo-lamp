import { useState } from 'react';
import { formatQuantity, slug, type ListLine, type Unit } from '@splitcart/engine';
import { Badge, Button, Card, CardHeader, NumberInput, Select, TextInput, Toggle } from '../components/ui.tsx';
import type { AppState, SetState } from '../state.ts';

export function BasketView({ state, setState }: { state: AppState; setState: SetState }) {
  const { lines, listings } = state.basket;
  const counts = new Map<string, number>();
  for (const l of listings) if (l.inStock) counts.set(l.lineId, (counts.get(l.lineId) ?? 0) + 1);

  const update = (id: string, patch: Partial<ListLine>) =>
    setState((s) => ({ ...s, basket: { ...s.basket, lines: s.basket.lines.map((l) => (l.id === id ? { ...l, ...patch } : l)) } }));
  const remove = (id: string) =>
    setState((s) => ({ ...s, basket: { ...s.basket, lines: s.basket.lines.filter((l) => l.id !== id) } }));

  return (
    <Card>
      <CardHeader
        title="Shopping list"
        meta="Quantities are what you need; the plan buys whole packs to cover them. Pin a brand to stop substitutions."
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-[13.5px]">
          <thead>
            <tr className="border-b border-line text-left text-[12px] uppercase tracking-[0.06em] text-muted">
              <th className="px-5 py-2.5 font-medium">Item</th>
              <th className="px-3 py-2.5 font-medium">Quantity</th>
              <th className="px-3 py-2.5 font-medium">Any brand</th>
              <th className="px-3 py-2.5 font-medium">Only this brand</th>
              <th className="px-3 py-2.5 font-medium">Prices</th>
              <th className="px-5 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {lines.map((l) => (
              <tr key={l.id}>
                <td className="px-5 py-2"><TextInput value={l.name} onChange={(e) => update(l.id, { name: e.target.value })} aria-label="Item name" /></td>
                <td className="px-3 py-2">
                  <div className="flex gap-1.5">
                    <NumberInput className="w-24" value={l.quantity} min={1} onChange={(n) => update(l.id, { quantity: n ?? 1 })} aria-label="Quantity" />
                    <Select value={l.unit} onChange={(e) => update(l.id, { unit: e.target.value as Unit })} aria-label="Unit">
                      <option value="g">g</option><option value="ml">ml</option><option value="pc">pc</option>
                    </Select>
                  </div>
                </td>
                <td className="px-3 py-2">
                  <Toggle label="Any brand" checked={!l.pinnedBrand} onChange={(v) => update(l.id, v ? { pinnedBrand: undefined, flexible: true } : { pinnedBrand: brandOf(state, l.id) ?? '', flexible: false })} />
                </td>
                <td className="px-3 py-2">
                  <TextInput
                    value={l.pinnedBrand ?? ''}
                    placeholder="Any"
                    onChange={(e) => update(l.id, e.target.value ? { pinnedBrand: e.target.value, flexible: false } : { pinnedBrand: undefined, flexible: true })}
                    aria-label="Pinned brand"
                  />
                </td>
                <td className="px-3 py-2">
                  {counts.get(l.id) ? <Badge>{counts.get(l.id)} listings</Badge> : <Badge tone="warn">None yet</Badge>}
                </td>
                <td className="px-5 py-2 text-right"><Button variant="ghost" onClick={() => remove(l.id)} aria-label={`Remove ${l.name}`}>Remove</Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <AddLine onAdd={(line) => setState((s) => ({ ...s, source: s.source.kind === 'sample' ? s.source : { kind: 'manual', label: 'Edited by hand' }, basket: { ...s.basket, lines: [...s.basket.lines, line] } }))} existing={lines} />
    </Card>
  );
}

function brandOf(state: AppState, lineId: string): string | undefined {
  return state.basket.listings.find((l) => l.lineId === lineId && l.brand)?.brand;
}

function AddLine({ onAdd, existing }: { onAdd: (l: ListLine) => void; existing: ListLine[] }) {
  const [name, setName] = useState('');
  const [quantity, setQuantity] = useState<number | undefined>(1);
  const [unit, setUnit] = useState<Unit>('pc');
  const submit = () => {
    if (!name.trim() || !quantity) return;
    let id = slug(name) || 'item';
    while (existing.some((l) => l.id === id)) id += '-2';
    onAdd({ id, name: name.trim(), quantity, unit, flexible: true });
    setName('');
  };
  return (
    <form className="flex flex-wrap items-end gap-2 border-t border-line px-5 py-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <TextInput className="max-w-xs" placeholder="Add an item, e.g. Ghee" value={name} onChange={(e) => setName(e.target.value)} aria-label="New item" />
      <NumberInput className="w-24" value={quantity} min={1} onChange={setQuantity} aria-label="New quantity" />
      <Select value={unit} onChange={(e) => setUnit(e.target.value as Unit)} aria-label="New unit">
        <option value="g">g</option><option value="ml">ml</option><option value="pc">pc</option>
      </Select>
      <Button type="submit" variant="primary">Add item</Button>
      <p className="w-full text-[12px] text-faint">New items need prices before they can be planned; add them on the Prices tab. Example: {formatQuantity(500, 'g')} of ghee.</p>
    </form>
  );
}
