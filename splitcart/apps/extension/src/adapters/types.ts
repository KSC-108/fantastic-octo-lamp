import type { Pacer } from '../pacer.ts';

/** What the web app sends: one order per platform from the plan. */
export interface CartRequest {
  platform: string;
  items: { title: string; brand?: string; packSize: string; packs: number; listingUrl?: string }[];
}

export interface AddResult {
  title: string;
  status: 'added' | 'not-found' | 'out-of-stock' | 'price-changed' | 'skipped';
  /** Price seen on the page, so the app can flag drift before you check out. */
  seenPrice?: number;
  note?: string;
}

export interface QuoteLine {
  title: string;
  brand?: string;
  packSize: string;
  price: number;
  rating?: number;
  ratingCount?: number;
  inStock: boolean;
  url?: string;
}

export interface CartSummary {
  subtotal: number;
  fees: Record<string, number>;
  coupon?: number;
  totalBeforePayment: number;
}

export interface AdapterContext {
  pacer: Pacer;
  tabId: number;
}

/**
 * One adapter per platform. An adapter moves through three stages:
 *   pending-recon: not built; the app falls back to a checklist
 *   read-only:     reads quotes and the cart summary
 *   cart-filling:  also adds planned items to the cart
 * Every method must route page actions through ctx.pacer and the guardrails.
 */
export interface PlatformAdapter {
  platform: string;
  name: string;
  status: 'pending-recon' | 'read-only' | 'cart-filling';
  notes: string;
  searchQuotes?(ctx: AdapterContext, query: string): Promise<QuoteLine[]>;
  readCartSummary?(ctx: AdapterContext): Promise<CartSummary>;
  addToCart?(ctx: AdapterContext, item: CartRequest['items'][number]): Promise<AddResult>;
}
