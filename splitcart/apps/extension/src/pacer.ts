/**
 * Paces automated actions like a person shopping: one action at a time, with
 * variable pauses and occasional longer breaks.
 *
 * Purpose: keep the load on each platform at the level of normal manual use.
 * It does not disguise the browser, alter fingerprints, or get past verification
 * challenges. If a platform shows a challenge or an unexpected page, adapters stop
 * and hand control back to you.
 */
export type ActionKind = 'browse' | 'add';

export interface PacerConfig {
  /** Median pause before a browse action (search, open a listing, read the cart). */
  browseMedianMs: number;
  /** Median pause before an add-to-cart action. */
  addMedianMs: number;
  /** Spread of the log-normal pause distribution. */
  sigma: number;
  minGapMs: number;
  maxGapMs: number;
  /** A longer break after this many actions (inclusive range, chosen at random). */
  breakEvery: [number, number];
  breakMs: [number, number];
  /** Hard cap per session; a weekly shop of about 40 items stays well under it. */
  maxActionsPerSession: number;
}

export const DEFAULT_PACER: PacerConfig = {
  browseMedianMs: 2_500,
  addMedianMs: 5_000,
  sigma: 0.45,
  minGapMs: 1_200,
  maxGapMs: 20_000,
  breakEvery: [6, 10],
  breakMs: [15_000, 40_000],
  maxActionsPerSession: 150,
};

export class PacerStopped extends Error {
  constructor(reason: string) {
    super(reason);
    this.name = 'PacerStopped';
  }
}

type Sleep = (ms: number, signal: AbortSignal) => Promise<void>;

const realSleep: Sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new PacerStopped('Stopped'));
    const timer = setTimeout(resolve, ms);
    signal.addEventListener('abort', () => { clearTimeout(timer); reject(new PacerStopped('Stopped')); }, { once: true });
  });

export class Pacer {
  private actions = 0;
  private untilBreak: number;
  private queue: Promise<unknown> = Promise.resolve();
  private readonly controller = new AbortController();
  readonly log: { kind: ActionKind; waitedMs: number }[] = [];

  constructor(
    private readonly config: PacerConfig = DEFAULT_PACER,
    private readonly random: () => number = Math.random,
    private readonly sleep: Sleep = realSleep,
  ) {
    this.untilBreak = this.pickBreak();
  }

  /** Runs `fn` after a human-like pause. Calls are serialised: never two actions at once. */
  run<T>(kind: ActionKind, fn: () => Promise<T>): Promise<T> {
    const next = this.queue.then(async () => {
      if (this.controller.signal.aborted) throw new PacerStopped('Stopped');
      if (this.actions >= this.config.maxActionsPerSession) {
        throw new PacerStopped(`Session limit of ${this.config.maxActionsPerSession} actions reached`);
      }
      let wait = this.gap(kind);
      this.untilBreak -= 1;
      if (this.untilBreak <= 0) {
        wait += this.uniform(this.config.breakMs);
        this.untilBreak = this.pickBreak();
      }
      await this.sleep(wait, this.controller.signal);
      this.actions += 1;
      this.log.push({ kind, waitedMs: Math.round(wait) });
      return fn();
    });
    this.queue = next.catch(() => undefined);
    return next;
  }

  stop(): void {
    this.controller.abort();
  }

  get signal(): AbortSignal {
    return this.controller.signal;
  }

  /** Log-normal pause around the median, clamped to [minGapMs, maxGapMs]. */
  gap(kind: ActionKind): number {
    const median = kind === 'add' ? this.config.addMedianMs : this.config.browseMedianMs;
    const u1 = Math.max(this.random(), 1e-9);
    const u2 = this.random();
    const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
    const ms = median * Math.exp(this.config.sigma * z);
    return Math.min(this.config.maxGapMs, Math.max(this.config.minGapMs, ms));
  }

  private pickBreak(): number {
    return Math.round(this.uniform(this.config.breakEvery));
  }

  private uniform([lo, hi]: [number, number]): number {
    return lo + this.random() * (hi - lo);
  }
}
