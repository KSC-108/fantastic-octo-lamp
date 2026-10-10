/**
 * Hard limits on what the extension may do. Cart filling only adds items; paying
 * and placing orders always stay with you.
 */
export type AllowedAction = 'search' | 'read-listing' | 'read-cart' | 'add-to-cart';

const ALLOWED = new Set<string>(['search', 'read-listing', 'read-cart', 'add-to-cart']);

const FORBIDDEN_URL = /(checkout|payment|\/pay\b|\/pay\/|place[-_]?order|order[-_]?confirm|\bupi\b|wallet)/i;
const CHALLENGE_TEXT = /(captcha|verify you are human|unusual traffic|are you a robot|access denied)/i;

export class GuardrailError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GuardrailError';
  }
}

export function assertAllowedAction(action: string): asserts action is AllowedAction {
  if (!ALLOWED.has(action)) throw new GuardrailError(`Action "${action}" is not permitted. SplitCart never pays or places orders.`);
}

export function assertSafeUrl(url: string): void {
  if (FORBIDDEN_URL.test(url)) throw new GuardrailError(`Refusing to open ${url}: checkout and payment pages are yours to handle.`);
}

/** True when a page looks like a verification challenge; adapters must stop and hand back to you. */
export function looksLikeChallenge(pageText: string): boolean {
  return CHALLENGE_TEXT.test(pageText);
}
