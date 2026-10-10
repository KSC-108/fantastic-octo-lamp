import { useMemo, useRef, useState } from 'react';
import {
  formatQuantity, importItemSheet, ITEM_SHEET_TEMPLATE, parseQuantity, sampleBasket, scoreListing, PLATFORM_NAMES, type Listing,
} from '@splitcart/engine';
import { Badge, Button, Card, CardHeader, NumberInput, Select, TextInput, Toggle } from '../components/ui.tsx';
import type { AppState, SetState } from '../state.ts';

export function PricesView({ state, setState }: { state: AppState; setState: SetState }) {
  const [lineFilter, setLineFilter] = useState('all');
  const [platformFilter, setPlatformFilter] = useState('all');
  const [notice, setNotice] = useState<{ tone: 'ok' | 'warn'; text: string } | null>(null);
  const [pending, setPending] = useState<{ text: string; baskets: string[] } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { lines, listings, rules } = state.basket;
  const lineName = new Map(lines.map((l) => [l.id, l.name] as const));
  const ruleName = new Map(rules.map((r) => [r.platform, r.name] as const));

  const visible = useMemo(
    () => listings
      .filter((l) => (lineFilter === 'all' || l.lineId === lineFilter) && (platformFilter === 'all' || l.platform === platformFilter))
      .sort((a, b) => (lineName.get(a.lineId) ?? '').localeCompare(lineName.get(b.lineId) ?? '') || a.price / a.packSize - b.price / b.packSize),
    [listings, lineFilter, platformFilter, lineName],
  );

  const update = (id: string, patch: Partial<Listing>) =>
    setState((s) => ({ ...s, basket: { ...s.basket, listings: s.basket.listings.map((l) => (l.id === id ? { ...l, ...patch } : l)) } }));
  const remove = (id: string) =>
    setState((s) => ({ ...s, basket: { ...s.basket, listings: s.basket.listings.filter((l) => l.id !== id) } }));

  const applyImport = (text: string, basket?: string) => {
    const r = importItemSheet(text, basket ? { basket } : {});
    if (r.listings.length === 0) {
      setNotice({ tone: 'warn', text: r.warnings.slice(0, 4).join(' ') || 'No rows could be read.' });
      return;
    }
    setState((s) => ({
      ...s,
      basket: { ...s.basket, lines: r.lines, listings: r.listings },
      source: { kind: 'import', label: `Imported Phase 0 sheet${basket ? `, basket ${basket}` : ''}` },
    }));
    setLineFilter('all');
    setNotice({
      tone: r.warnings.length ? 'warn' : 'ok',
      text: `Imported ${r.listings.length} listings for ${r.lines.length} items.${r.warnings.length ? ` ${r.warnings.length} rows skipped: ${r.warnings.slice(0, 3).join(' ')}` : ''}`,
    });
  };

  const onFile = async (file: File) => {
    const text = await file.text();
    const { baskets } = importItemSheet(text);
    if (baskets.length > 1) setPending({ text, baskets });
    else applyImport(text);
  };

  const download = () => {
    const blob = new Blob([ITEM_SHEET_TEMPLATE + '\n'], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'splitcart-item-sheet.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Import your Phase 0 item sheet"
          meta="One row per product, per platform, per basket. Log premium alternatives as extra rows under the same list line."
          action={
            <div className="flex flex-wrap gap-2">
              <Button onClick={download}>Download template</Button>
              <Button variant="primary" onClick={() => fileRef.current?.click()}>Import CSV</Button>
              <input ref={fileRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void onFile(f); e.target.value = ''; }} />
            </div>
          }
        />
        <div className="space-y-3 px-5 py-4 text-[13px] text-muted">
          <p>
            Columns: Basket, Platform, List line, Product as listed, Brand, Pack size, Price (Rs), Rating, Ratings count, In stock, Tags.
            Write list lines as <span className="font-medium text-ink">Paneer 200 g, any brand</span> or <span className="font-medium text-ink">Butter 100 g, only Dairyfields</span>.
          </p>
          {pending && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg bg-canvas px-3 py-2">
              <span className="text-ink">This sheet has {pending.baskets.length} baskets. Plan which one?</span>
              {pending.baskets.map((b) => (
                <Button key={b} onClick={() => { applyImport(pending.text, b); setPending(null); }}>{b}</Button>
              ))}
            </div>
          )}
          {notice && <p className={notice.tone === 'ok' ? 'text-gain' : 'text-warn'}>{notice.text}</p>}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => { setState((s) => ({ ...s, basket: { ...sampleBasket(), rules: s.basket.rules }, source: { kind: 'sample', label: 'Sample basket with invented prices' } })); setNotice(null); }}>
              Restore sample basket
            </Button>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Listings"
          meta={`${listings.length} listings. Sorted by unit price within each item. Edit any price or stock flag and the plan updates.`}
          action={
            <div className="flex gap-2">
              <Select value={lineFilter} onChange={(e) => setLineFilter(e.target.value)} aria-label="Filter by item">
                <option value="all">All items</option>
                {lines.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </Select>
              <Select value={platformFilter} onChange={(e) => setPlatformFilter(e.target.value)} aria-label="Filter by platform">
                <option value="all">All platforms</option>
                {rules.map((r) => <option key={r.platform} value={r.platform}>{r.name}</option>)}
              </Select>
            </div>
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-[13px]">
            <thead>
              <tr className="border-b border-line text-left text-[12px] uppercase tracking-[0.06em] text-muted">
                <th className="px-5 py-2.5 font-medium">Item</th>
                <th className="px-3 py-2.5 font-medium">Platform</th>
                <th className="px-3 py-2.5 font-medium">Product</th>
                <th className="px-3 py-2.5 font-medium">Pack</th>
                <th className="px-3 py-2.5 font-medium">Price</th>
                <th className="px-3 py-2.5 font-medium">Quality</th>
                <th className="px-3 py-2.5 font-medium">In stock</th>
                <th className="px-5 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {visible.map((l) => {
                const q = scoreListing(l, state.prefs);
                return (
                  <tr key={l.id}>
                    <td className="px-5 py-2 text-muted">{lineName.get(l.lineId) ?? l.lineId}</td>
                    <td className="px-3 py-2">{ruleName.get(l.platform) ?? PLATFORM_NAMES[l.platform] ?? l.platform}</td>
                    <td className="px-3 py-2">
                      <p>{l.title}</p>
                      {l.rating && <p className="text-[12px] text-faint">{l.rating.toFixed(1)} from {l.ratingCount?.toLocaleString('en-IN') ?? '?'} ratings</p>}
                    </td>
                    <td className="px-3 py-2 tabular-nums">{formatQuantity(l.packSize, l.unit)}</td>
                    <td className="px-3 py-2"><NumberInput className="w-20" value={l.price} min={0} onChange={(n) => update(l.id, { price: n ?? 0 })} aria-label={`Price of ${l.title}`} /></td>
                    <td className="px-3 py-2"><Badge tone={q.traits >= 20 ? 'accent' : 'neutral'} title={q.reasons.join(', ') || 'No preferred traits found'}>{q.score.toFixed(0)}</Badge></td>
                    <td className="px-3 py-2"><Toggle label="In stock" checked={l.inStock} onChange={(v) => update(l.id, { inStock: v })} /></td>
                    <td className="px-5 py-2 text-right"><Button variant="ghost" onClick={() => remove(l.id)}>Remove</Button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <AddListing state={state} setState={setState} />
      </Card>
    </div>
  );
}

function AddListing({ state, setState }: { state: AppState; setState: SetState }) {
  const { lines, rules } = state.basket;
  const [lineId, setLineId] = useState(lines[0]?.id ?? '');
  const [platform, setPlatform] = useState(rules[0]?.platform ?? '');
  const [title, setTitle] = useState('');
  const [pack, setPack] = useState('');
  const [price, setPrice] = useState<number | undefined>();
  const [error, setError] = useState('');

  const submit = () => {
    const line = lines.find((l) => l.id === lineId);
    const parsed = parseQuantity(pack);
    if (!line || !title.trim() || !price) return setError('Pick an item and enter a product name and price.');
    if (!parsed) return setError('Pack size should look like 200 g, 1 L or 6 pc.');
    if (parsed.unit !== line.unit) return setError(`${line.name} is measured in ${line.unit}; this pack is in ${parsed.unit}.`);
    setError('');
    setState((s) => ({
      ...s,
      basket: {
        ...s.basket,
        listings: [...s.basket.listings, { id: `manual-${Date.now()}`, lineId, platform, title: title.trim(), packSize: parsed.size, unit: parsed.unit, price, inStock: true }],
      },
    }));
    setTitle('');
    setPrice(undefined);
  };

  return (
    <form className="flex flex-wrap items-end gap-2 border-t border-line px-5 py-3" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <Select value={lineId} onChange={(e) => setLineId(e.target.value)} aria-label="Item">
        {lines.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </Select>
      <Select value={platform} onChange={(e) => setPlatform(e.target.value)} aria-label="Platform">
        {rules.map((r) => <option key={r.platform} value={r.platform}>{r.name}</option>)}
      </Select>
      <TextInput className="max-w-xs" placeholder="Product as listed" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Product" />
      <TextInput className="w-28" placeholder="Pack, e.g. 1 L" value={pack} onChange={(e) => setPack(e.target.value)} aria-label="Pack size" />
      <NumberInput className="w-24" placeholder="Price" value={price} min={0} onChange={setPrice} aria-label="Price" />
      <Button type="submit" variant="primary">Add listing</Button>
      {error && <p className="w-full text-[12.5px] text-warn">{error}</p>}
      {!error && <p className="w-full text-[12px] text-faint">Tip: include traits in the product name, such as organic or cold pressed, so quality is scored.</p>}
    </form>
  );
}
