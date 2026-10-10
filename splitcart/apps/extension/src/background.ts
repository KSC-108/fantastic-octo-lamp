import { DEFAULT_PACER, Pacer } from './pacer.ts';
import { ADAPTERS } from './adapters/index.ts';
import { fillCarts } from './fill.ts';
import type { CartRequest } from './adapters/types.ts';

let active: Pacer | null = null;

type Message = { type: 'ping' } | { type: 'fill-carts'; orders: CartRequest[] } | { type: 'stop' };

/** Messages come only from the local SplitCart web app (see externally_connectable in the manifest). */
chrome.runtime.onMessageExternal.addListener((message: Message, _sender, sendResponse) => {
  if (message.type === 'ping') {
    sendResponse({ ok: true, adapters: ADAPTERS.map(({ platform, status, notes }) => ({ platform, status, notes })) });
    return false;
  }
  if (message.type === 'stop') {
    active?.stop();
    sendResponse({ ok: true });
    return false;
  }
  if (message.type === 'fill-carts') {
    if (active) {
      sendResponse({ ok: false, error: 'A cart-filling session is already running.' });
      return false;
    }
    active = new Pacer(DEFAULT_PACER);
    fillCarts(message.orders, active, openPlatformTab)
      .then((reports) => sendResponse({ ok: true, reports }))
      .catch((err) => sendResponse({ ok: false, error: String(err) }))
      .finally(() => { active = null; });
    return true; // keep the channel open for the async response
  }
  return false;
});

/** Platform home pages are added with each adapter, together with its host permission. */
const HOME: Record<string, string> = {};

async function openPlatformTab(platform: string): Promise<number> {
  const url = HOME[platform];
  if (!url) throw new Error(`No home page configured for ${platform}`);
  const tab = await chrome.tabs.create({ url, active: false });
  if (tab.id === undefined) throw new Error('Could not open a tab');
  return tab.id;
}
