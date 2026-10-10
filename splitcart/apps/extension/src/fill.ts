import { Pacer, PacerStopped } from './pacer.ts';
import { adapterFor } from './adapters/index.ts';
import type { AddResult, CartRequest } from './adapters/types.ts';
import { GuardrailError } from './guardrails.ts';

export interface FillReport {
  platform: string;
  status: 'done' | 'adapter-pending' | 'stopped' | 'error';
  results: AddResult[];
  message?: string;
}

/**
 * Fills carts one platform at a time, one item at a time, through the pacer.
 * Stops at the first guardrail violation or verification challenge.
 */
export async function fillCarts(requests: CartRequest[], pacer: Pacer, openTab: (platform: string) => Promise<number>): Promise<FillReport[]> {
  const reports: FillReport[] = [];
  for (const req of requests) {
    const adapter = adapterFor(req.platform);
    if (!adapter?.addToCart || adapter.status !== 'cart-filling') {
      reports.push({ platform: req.platform, status: 'adapter-pending', results: [], message: adapter?.notes ?? 'Unknown platform' });
      continue;
    }
    const results: AddResult[] = [];
    try {
      const tabId = await openTab(req.platform);
      for (const item of req.items) {
        results.push(await pacer.run('add', () => adapter.addToCart!({ pacer, tabId }, item)));
      }
      reports.push({ platform: req.platform, status: 'done', results });
    } catch (err) {
      const stopped = err instanceof PacerStopped || err instanceof GuardrailError;
      reports.push({ platform: req.platform, status: stopped ? 'stopped' : 'error', results, message: String((err as Error).message ?? err) });
      if (stopped) break;
    }
  }
  return reports;
}
