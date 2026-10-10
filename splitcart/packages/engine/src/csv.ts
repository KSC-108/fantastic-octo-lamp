import type { Listing, ListLine } from './types.ts';
import { parseLineText, parseQuantity } from './units.ts';
import { platformId } from './platforms.ts';

/** RFC 4180-style CSV parsing: quoted fields, escaped quotes, CRLF. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.some((f) => f.trim() !== '')) rows.push(row);
      row = [];
    } else field += ch;
  }
  row.push(field);
  if (row.some((f) => f.trim() !== '')) rows.push(row);
  return rows;
}

export const ITEM_SHEET_HEADERS = [
  'Basket', 'Platform', 'List line', 'Product as listed', 'Brand', 'Pack size', 'Price (Rs)', 'Rating', 'Ratings count', 'In stock', 'Tags',
];

export const ITEM_SHEET_TEMPLATE = [
  ITEM_SHEET_HEADERS.join(','),
  'B01,Zepto,"Paneer 200 g, any brand",Example fresh malai paneer,Example Dairy,200 g,96,4.5,2000,Yes,fresh',
  'B01,Blinkit,"Paneer 200 g, any brand",Example paneer,Other Dairy,200 g,90,4.2,8000,Yes,',
  'B01,Blinkit,"Butter 100 g, only Example Dairy",Example Dairy butter,Example Dairy,100 g,58,4.6,15000,Yes,',
].join('\n');

const COLUMN_KEYS: Record<string, string[]> = {
  basket: ['basket'],
  platform: ['platform'],
  line: ['list line', 'line'],
  product: ['product as listed', 'product', 'title'],
  brand: ['brand'],
  pack: ['pack size', 'pack'],
  price: ['price (rs)', 'price'],
  rating: ['rating'],
  ratingCount: ['ratings count', 'rating count', 'ratings'],
  inStock: ['in stock', 'stock'],
  tags: ['tags', 'attributes'],
};

export interface ImportResult {
  lines: ListLine[];
  listings: Listing[];
  baskets: string[];
  warnings: string[];
}

/**
 * Imports the Phase 0 item sheet. Each row is one product on one platform for one list line.
 * Premium alternatives are simply extra rows under the same list line.
 */
export function importItemSheet(text: string, opts: { basket?: string } = {}): ImportResult {
  const rows = parseCsv(text);
  const warnings: string[] = [];
  if (rows.length < 2) return { lines: [], listings: [], baskets: [], warnings: ['The sheet has no data rows.'] };
  const header = rows[0]!.map((h) => h.trim().toLowerCase());
  const col: Record<string, number> = {};
  for (const [key, names] of Object.entries(COLUMN_KEYS)) col[key] = header.findIndex((h) => names.includes(h));
  for (const required of ['platform', 'line', 'product', 'pack', 'price']) {
    if (col[required]! < 0) warnings.push(`Missing column: ${COLUMN_KEYS[required]![0]}`);
  }
  if (warnings.length > 0) return { lines: [], listings: [], baskets: [], warnings };

  const get = (r: string[], key: string) => (col[key]! >= 0 ? (r[col[key]!] ?? '').trim() : '');
  const baskets = [...new Set(rows.slice(1).map((r) => get(r, 'basket')).filter(Boolean))];
  const lines = new Map<string, ListLine>();
  const listings: Listing[] = [];

  rows.slice(1).forEach((r, i) => {
    const rowNo = i + 2;
    if (opts.basket && get(r, 'basket') && get(r, 'basket') !== opts.basket) return;
    const lineText = get(r, 'line');
    const parsedLine = parseLineText(lineText);
    if (!parsedLine) { warnings.push(`Row ${rowNo}: cannot read the quantity in "${lineText}"`); return; }
    const lineId = slug(`${parsedLine.name}-${parsedLine.quantity}${parsedLine.unit}`);
    if (!lines.has(lineId)) lines.set(lineId, { id: lineId, ...parsedLine });
    const line = lines.get(lineId)!;

    const pack = parseQuantity(get(r, 'pack'));
    if (!pack) { warnings.push(`Row ${rowNo}: cannot read pack size "${get(r, 'pack')}"`); return; }
    if (pack.unit !== line.unit) { warnings.push(`Row ${rowNo}: pack unit ${pack.unit} does not match the list line unit ${line.unit}`); return; }
    const price = Number(get(r, 'price').replace(/[^0-9.]/g, ''));
    if (!(price > 0)) { warnings.push(`Row ${rowNo}: missing price`); return; }
    const rating = Number(get(r, 'rating'));
    const ratingCount = Number(get(r, 'ratingCount').replace(/[^0-9]/g, ''));
    const stock = get(r, 'inStock').toLowerCase();
    const tags = get(r, 'tags');
    listings.push({
      id: `row${rowNo}`,
      lineId,
      platform: platformId(get(r, 'platform')),
      title: get(r, 'product'),
      ...(get(r, 'brand') ? { brand: get(r, 'brand') } : {}),
      packSize: pack.size,
      unit: pack.unit,
      price,
      ...(rating > 0 ? { rating } : {}),
      ...(ratingCount > 0 ? { ratingCount } : {}),
      inStock: !['no', 'n', 'false', '0', 'out of stock'].includes(stock),
      ...(tags ? { attributes: tags.split(/[;|]/).map((t) => t.trim()).filter(Boolean) } : {}),
    });
  });
  return { lines: [...lines.values()], listings, baskets, warnings };
}

export function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}
