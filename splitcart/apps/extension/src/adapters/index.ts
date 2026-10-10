import type { PlatformAdapter } from './types.ts';

const RECON = 'Pending Phase 0 checks: desktop web ordering at 400068, whether web carts appear in the phone app, and the terms of use.';

/**
 * Registry of platform adapters. None are implemented yet: building them needs the
 * Phase 0 findings (which sites support desktop ordering, page structure, terms).
 * Until then the web app's "Copy checklist" is the hand-off.
 */
export const ADAPTERS: PlatformAdapter[] = [
  { platform: 'blinkit', name: 'Blinkit', status: 'pending-recon', notes: RECON },
  { platform: 'zepto', name: 'Zepto', status: 'pending-recon', notes: RECON },
  { platform: 'instamart', name: 'Swiggy Instamart', status: 'pending-recon', notes: RECON },
  { platform: 'minutes', name: 'Flipkart Minutes', status: 'pending-recon', notes: RECON },
  { platform: 'amazon-now', name: 'Amazon Now', status: 'pending-recon', notes: RECON },
];

export function adapterFor(platform: string): PlatformAdapter | undefined {
  return ADAPTERS.find((a) => a.platform === platform);
}
